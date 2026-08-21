"""Purchase-behaviour detectors #1–#6 (PLAN §3.4).

Every threshold here is a *default* from config, and the calibration pass in
``signals/engine.py`` checks that none of them fires on more than 60% or fewer
than 2% of the book at the anchor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...io import schema as S
from ...metrics.base import MetricContext, num, pct
from ..base import BaseDetector, Signal, annual_revenue, register, scale


@register
class CadenceBreach(BaseDetector):
    """#1 — silence measured against the customer's **own** rhythm, never a
    global recency cutoff. A monthly buyer 45 days quiet is critical; a
    quarterly buyer 90 days quiet is normal."""

    name = "cadence_breach"
    category = "risk"
    requires = ["cadence", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        cad = ctx.table("cadence")
        return cad.index[cad["cadence_eligible"].fillna(False)]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        cad = self.frame(ctx)
        hits = cad.loc[
            cad["cadence_eligible"].fillna(False)
            & (cad["cadence_ratio"] > st.cadence_breach_ratio)
        ]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.cadence_ratio, st.cadence_breach_ratio, 8.0),
                headline_fa=(
                    f"سکوت خرید {num(r.cadence_ratio, 1)} برابر ریتم شخصی این مشتری "
                    f"({num(r.days_since_last)} روز بدون خرید)."
                ),
                evidence_ids=ctx.ev(cid, "cadence-ratio", "cadence-last", "cadence-median"),
                value_at_stake=annual_revenue(ctx, cid),
                suggested_bucket=None,
                ratio=float(r.cadence_ratio), days_since_last=float(r.days_since_last),
            ))
        return out


@register
class VolumeDecline(BaseDetector):
    """#2 — monthly volume in the recent window against the prior baseline."""

    name = "volume_decline"
    category = "risk"
    requires = ["economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        econ = ctx.table("economics")
        return econ.index[econ["volume_change_pct"].notna()]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        econ = self.frame(ctx)
        hits = econ.loc[econ["volume_change_pct"] < st.volume_decline_pct]
        out = []
        for cid, r in hits.iterrows():
            lost = max(float(r.revenue_baseline or 0.0) / st.baseline_window_months
                       - float(r.revenue_recent or 0.0) / st.recent_window_months, 0.0)
            out.append(self.signal(
                ctx, cid,
                severity=scale(-r.volume_change_pct, -st.volume_decline_pct, 1.0),
                headline_fa=(
                    f"حجم خرید ماهانه {pct(r.volume_change_pct)} درصد افت کرده است."
                ),
                evidence_ids=ctx.ev(cid, "volume", "revenue"),
                value_at_stake=lost * 12.0,
                change=float(r.volume_change_pct),
            ))
        return out


@register
class VolumeSurge(BaseDetector):
    """#3 — growth is an opportunity **and** a credit/capacity question. The
    signal deliberately carries both so the sales manager checks the limit
    before promising the tonnage."""

    name = "volume_surge"
    category = "opportunity"
    requires = ["economics", "payment"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        econ = ctx.table("economics")
        return econ.index[econ["volume_change_pct"].notna()]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        hits = df.loc[df["volume_change_pct"] > st.volume_surge_pct]
        out = []
        for cid, r in hits.iterrows():
            exposure_ratio = r.get("exposure_ratio")
            credit_flag = bool(pd.notna(exposure_ratio) and exposure_ratio > 0.6)
            gained = max(float(r.revenue_recent or 0.0) / st.recent_window_months
                         - float(r.revenue_baseline or 0.0) / st.baseline_window_months, 0.0)
            head = f"حجم خرید ماهانه {pct(r.volume_change_pct)} درصد رشد کرده است."
            if credit_flag:
                head += (
                    f" هم‌زمان {pct(exposure_ratio, 0)} درصد سقف اعتبار اشغال شده — "
                    "پیش از تعهد حجم بیشتر، اعتبار و ظرفیت بررسی شود."
                )
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.volume_change_pct, st.volume_surge_pct, 2.0),
                direction="improving",
                headline_fa=head,
                evidence_ids=ctx.ev(cid, "volume", "revenue", "exposure"),
                value_at_stake=gained * 12.0,
                suggested_bucket="grow",
                change=float(r.volume_change_pct), credit_check=credit_flag,
            ))
        return out


@register
class FirstOrderNoRepeat(BaseDetector):
    """#4 — onboarding failure: one invoice ever, and now well past the point at
    which a customer who was going to come back would have."""

    name = "first_order_no_repeat"
    category = "risk"
    requires = ["cadence", "economics"]
    rare_by_design = True

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        cad = self.frame(ctx)
        # what "coming back" normally looks like across the book
        book_first_repeat = ctx.table("cadence")["first_repeat_gap"].median()
        threshold = float(book_first_repeat or 30) * st.first_repeat_gap_multiple
        hits = cad.loc[(cad["n_invoices"] == 1) & (cad["days_since_last"] > threshold)]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.days_since_last, threshold, threshold * 6),
                headline_fa=(
                    f"تنها یک فاکتور ثبت شده و {num(r.days_since_last)} روز است که "
                    f"خرید دومی انجام نشده (میانه بازگشت در کل دفتر "
                    f"{num(book_first_repeat)} روز) — شکست در جذب."
                ),
                evidence_ids=ctx.ev(cid, "cadence-last", "revenue"),
                value_at_stake=annual_revenue(ctx, cid),
                suggested_bucket="reduce",
                threshold_days=threshold,
            ))
        return out


@register
class MixDowngrade(BaseDetector):
    """#5 — the value-weighted position of the basket on the family price ladder
    is sliding toward cheaper families."""

    name = "mix_downgrade"
    category = "risk"
    requires = ["mix", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        mix = ctx.table("mix")
        return mix.index[mix["ladder_delta"].notna()]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        mix = self.frame(ctx)
        hits = mix.loc[mix["ladder_delta"] < -st.mix_downgrade_steps]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(-r.ladder_delta, st.mix_downgrade_steps, 3.0),
                headline_fa=(
                    f"سبد خرید {num(-r.ladder_delta, 1)} پله روی نردبان خانواده کالا "
                    f"به سمت محصولات ارزان‌تر جابه‌جا شده است."
                ),
                evidence_ids=ctx.ev(cid, "ladder", "price-pos"),
                value_at_stake=annual_revenue(ctx, cid) * 0.15,
                delta=float(r.ladder_delta),
            ))
        return out


@register
class SkuNarrowing(BaseDetector):
    """#6 — fewer distinct products per month means we are losing share of their
    line even while the tonnage still looks acceptable."""

    name = "sku_narrowing"
    category = "risk"
    requires = ["mix", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        mix = ctx.table("mix")
        return mix.index[
            (mix["skus_per_month_baseline"] >= 2)
            & (mix["skus_per_month_recent"].fillna(0) > 0)
        ]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        mix = self.frame(ctx)
        # Only customers who are *still buying* — a customer who stopped
        # entirely is a cadence breach, not a narrowing basket, and counting
        # them here would double-charge the same fact to two detectors.
        hits = mix.loc[
            (mix["sku_change_pct"] < st.sku_narrowing_pct)
            & (mix["skus_per_month_baseline"] >= 2)
            & (mix["skus_per_month_recent"].fillna(0) > 0)
        ]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(-r.sku_change_pct, -st.sku_narrowing_pct, 1.0),
                headline_fa=(
                    f"تنوع کد کالای ماهانه {pct(r.sku_change_pct)} درصد کاهش یافته "
                    f"({num(r.skus_per_month_baseline, 1)} به "
                    f"{num(r.skus_per_month_recent, 1)}) — از دست دادن سهم از خط تولید مشتری."
                ),
                evidence_ids=ctx.ev(cid, "sku-breadth", "revenue"),
                value_at_stake=annual_revenue(ctx, cid) * 0.2,
                change=float(r.sku_change_pct),
            ))
        return out
