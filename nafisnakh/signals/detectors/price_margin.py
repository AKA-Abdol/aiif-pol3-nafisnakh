"""Price and margin detectors #7–#10 (PLAN §3.4).

`negative_risk_adj_margin` is the detector that makes the ``fix`` bucket
actionable — high volume with negative risk-adjusted margin is precisely the
"تعداد خرید بالا، سودی ندارند" case the user described. It is also the detector
most exposed to the unanswered Q11/Q12, so its evidence chain carries the
assumption flags all the way through.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...io import schema as S
from ...metrics.base import MetricContext, money, num, pct, span_ref
from ..base import BaseDetector, Signal, annual_revenue, register, scale


@register
class PriceErosion(BaseDetector):
    """#7 — deflated price position falling. Absolute rial trends are inflation,
    not signal (PLAN §1.7): they flag 250 of 254 customers."""

    name = "price_erosion"
    category = "risk"
    requires = ["mix", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        mix = ctx.table("mix")
        return mix.index[mix["price_position_change"].notna()]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        mix = self.frame(ctx)
        hits = mix.loc[mix["price_position_change"] < st.price_erosion_pct]
        out = []
        for cid, r in hits.iterrows():
            revenue = annual_revenue(ctx, cid)
            out.append(self.signal(
                ctx, cid,
                severity=scale(-r.price_position_change, -st.price_erosion_pct, 0.5),
                headline_fa=(
                    f"موقعیت قیمتی تعدیل‌شده {pct(r.price_position_change)} درصد افت "
                    f"کرده است (نسبت به میانگین بازار در همان ماه‌ها، نه ریال مطلق)."
                ),
                evidence_ids=ctx.ev(cid, "price-trend", "price-pos", "margin"),
                value_at_stake=revenue * abs(float(r.price_position_change)),
                change=float(r.price_position_change),
            ))
        return out


@register
class NegativeRiskAdjMargin(BaseDetector):
    """#8 — the ``fix`` trigger: real volume, negative margin once the late
    charge, the cost of capital, bad debt and cost-to-serve are all counted."""

    name = "negative_risk_adj_margin"
    category = "efficiency"
    requires = ["economics", "payment"]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        econ = self.frame(ctx)
        # "meaningful volume" — the top three quartiles of revenue; a tiny
        # account with a negative margin is a `reduce`, not a `fix`.
        cutoff = econ["revenue_total"].quantile(0.25)
        hits = econ.loc[
            (econ["risk_adj_margin"] < 0) & (econ["revenue_total"] > cutoff)
        ]
        out = []
        for cid, r in hits.iterrows():
            loss = abs(float(r.risk_adj_margin))
            out.append(self.signal(
                ctx, cid,
                severity=scale(
                    -float(r.risk_adj_margin_rate or 0), 0.0, 0.25, floor=40.0
                ),
                headline_fa=(
                    f"حاشیه سود ریسک‌تعدیل‌شده منفی است "
                    f"({pct(r.risk_adj_margin_rate)} درصد) در حالی که درآمد "
                    f"{money(r.revenue_total, ctx.settings)} ریال بوده — شرایط قرارداد "
                    f"باید بازنگری شود."
                ),
                evidence_ids=ctx.ev(cid, "riskadj", "margin", "revenue", "finance-net"),
                value_at_stake=loss,
                suggested_bucket="fix",
                risk_adj_margin=float(r.risk_adj_margin),
                depends_on_open_questions=["Q11", "Q12"],
            ))
        return out


@register
class MarginBelowPeerCohort(BaseDetector):
    """#9 — margin percentile inside the customer's own segment × dominant
    family cohort. Being unprofitable *relative to comparable accounts* is a
    negotiating fact; being unprofitable in absolute rials is inflation."""

    name = "margin_below_peer_cohort"
    category = "efficiency"
    requires = ["economics", "mix"]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        out = []
        window = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)
        for cid, r in df.iterrows():
            family = r.get("dominant_family")
            pctile = ctx.cohorts.margin_percentile(
                cid, family if isinstance(family, str) else None
            )
            if pctile is None or pctile >= st.margin_peer_percentile:
                continue
            ev = ctx.emit(
                cid, "margin-cohort",
                f"حاشیه سود این مشتری در صدک {num(pctile, 0)} همتایان هم‌بخش و "
                f"هم‌خانواده کالا قرار دارد (کمتر از صدک "
                f"{num(st.margin_peer_percentile, 0)}).",
                float(pctile), unit="صدک", kind="comparison", window=window,
                source_rows=span_ref(S.S_SALES, cid, window, int(r.get("lines_total", 0) or 0)),
                formula="percentile of customer margin rate within segment × family cohort",
                cohort_family=family,
            )
            out.append(self.signal(
                ctx, cid,
                severity=scale(st.margin_peer_percentile - pctile, 0.0,
                               st.margin_peer_percentile),
                headline_fa=(
                    f"حاشیه سود در صدک {num(pctile, 0)} همتایان است — پایین‌تر از "
                    f"{num(100 - pctile, 0)} درصد مشتریان مشابه."
                ),
                evidence_ids=[ev.id] + ctx.ev(cid, "margin", "price-pos"),
                value_at_stake=annual_revenue(ctx, cid) * 0.1,
                suggested_bucket="fix",
                percentile=pctile,
            ))
        return out


@register
class DiscountWithoutReturn(BaseDetector):
    """#10 — discount given against what it bought.

    ⚠️ PLAN §1.2: the ``آفرها`` sheet has **no association with any outcome** —
    the discount/win correlation of −0.018 is the absence of a generator link,
    not a commercial finding, and must never be presented as one. So this
    detector deliberately does **not** claim discounts are ineffective. It only
    reports the mechanical pairing — discount was granted, volume and margin did
    not move — and leaves causality to the sales manager.
    """

    name = "discount_without_return"
    category = "efficiency"
    requires = ["engagement", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        eng = ctx.table("engagement")
        return eng.index[eng["offers_price_type"] >= ctx.settings.discount_min_offers]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        df = self.frame(ctx)
        hits = df.loc[
            (df["offers_price_type"] >= ctx.settings.discount_min_offers)
            & (df["volume_change_pct"].fillna(0) < 0)
            & (df["discount_pct_mean_price_type"].notna())
        ]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(
                    float(r.discount_pct_mean_price_type or 0) * float(r.offers_price_type),
                    0.02, 0.4, floor=15.0,
                ),
                headline_fa=(
                    f"{num(r.offers_price_type)} پیشنهاد قیمتی با میانگین تخفیف "
                    f"{pct(r.discount_pct_mean_price_type)} درصد ارائه شده، اما حجم خرید "
                    f"در همان دوره {pct(r.volume_change_pct)} درصد تغییر کرده است."
                ),
                evidence_ids=ctx.ev(cid, "offers", "volume", "margin"),
                value_at_stake=annual_revenue(ctx, cid)
                * float(r.discount_pct_mean_price_type or 0),
                direction="static",
                mean_discount=float(r.discount_pct_mean_price_type),
                caveat=("association only — the offers sheet has no measurable link to "
                        "outcome in this dataset (PLAN §1.2); no causal claim is made"),
            ))
        return out
