"""Payment detectors #11–#14 (PLAN §3.4).

The interesting one is #14. Because Nafis Nakh really collects 4%/month on
overdue balances (Q10), slow payment is not automatically a loss — it is a loss
only when the firm's own cost of capital exceeds what it collects. This detector
therefore fires on the **net** effect, not on lateness, and says so in its
headline. If Q11 comes back below 4%/month it will fire on almost nobody, and
that will be the correct answer rather than a bug.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...metrics.base import MetricContext, money, num, pct
from ..base import BaseDetector, Signal, annual_revenue, register, scale


@register
class DsoSlippage(BaseDetector):
    """#11 — payment slowing against the customer's own baseline."""

    name = "dso_slippage"
    category = "risk"
    requires = ["payment", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        pay = ctx.table("payment")
        return pay.index[pay["dso_slippage"].notna()]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        pay = self.frame(ctx)
        hits = pay.loc[pay["dso_slippage"] > st.dso_slippage_days]
        out = []
        for cid, r in hits.iterrows():
            extra_days = float(r.dso_slippage)
            exposure = float(r.open_exposure or 0.0)
            out.append(self.signal(
                ctx, cid,
                severity=scale(extra_days, st.dso_slippage_days, 90.0),
                headline_fa=(
                    f"دوره وصول {num(extra_days)} روز نسبت به رفتار قبلی خود این مشتری "
                    f"کندتر شده است ({num(r.dso_baseline)} به {num(r.dso_recent)} روز)."
                ),
                evidence_ids=ctx.ev(cid, "dso-slip", "dso", "exposure"),
                value_at_stake=exposure * (st.wacc_monthly or 0.0) * extra_days / 30.0,
                slippage_days=extra_days,
            ))
        return out


@register
class BouncedCheque(BaseDetector):
    """#12 — a hard signal. One bounced cheque is a fact, not a trend."""

    name = "bounced_cheque"
    category = "risk"
    requires = ["payment", "economics"]
    rare_by_design = True

    def detect(self, ctx: MetricContext) -> list[Signal]:
        pay = self.frame(ctx)
        hits = pay.loc[pay["bounces"] > 0]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.bounces, 1, 5, floor=55.0),
                headline_fa=(
                    f"{num(r.bounces)} فقره چک برگشتی ثبت شده و مانده باز "
                    f"{money(r.open_exposure, ctx.settings)} ریال است."
                ),
                evidence_ids=ctx.ev(cid, "bounce", "exposure", "dso"),
                value_at_stake=float(r.open_exposure or 0.0),
                bounces=float(r.bounces),
            ))
        return out


@register
class CreditExposure(BaseDetector):
    """#13 — open balance against the declared credit limit."""

    name = "credit_exposure"
    category = "risk"
    requires = ["payment", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        pay = ctx.table("payment")
        return pay.index[pay["credit_limit"].fillna(0) > 0]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        pay = self.frame(ctx)
        hits = pay.loc[pay["exposure_ratio"] > st.credit_exposure_ratio]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.exposure_ratio, st.credit_exposure_ratio, 2.0),
                headline_fa=(
                    f"مانده باز {pct(r.exposure_ratio, 0)} درصد سقف اعتبار "
                    f"({money(r.credit_limit, ctx.settings)} ریال) را اشغال کرده است."
                ),
                evidence_ids=ctx.ev(cid, "exposure", "dso"),
                value_at_stake=float(r.open_exposure or 0.0),
                ratio=float(r.exposure_ratio),
            ))
        return out


@register
class LateInterestDrag(BaseDetector):
    """#14 — the **net** finance effect, not lateness.

    ``late_charge_revenue − capital_cost`` against gross margin. Because the 4%
    monthly charge is genuinely collected (Q10), a slow payer can be net
    accretive; this fires only when the net is negative *and* material.
    """

    name = "late_interest_drag"
    category = "efficiency"
    requires = ["payment", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        pay = ctx.table("payment")
        return pay.index[pay["net_finance_effect"].notna()]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        margin = df["margin_total"].replace(0, np.nan)
        drag = -df["net_finance_effect"] / margin.abs()
        hits = df.loc[(df["net_finance_effect"] < 0) & (drag > st.late_interest_drag_pct)]
        out = []
        for cid, r in hits.iterrows():
            share = float(-r.net_finance_effect / abs(r.margin_total)) if r.margin_total else 0.0
            out.append(self.signal(
                ctx, cid,
                severity=scale(share, st.late_interest_drag_pct, 1.5),
                headline_fa=(
                    f"اثر خالص مالی منفی {money(-r.net_finance_effect, ctx.settings)} "
                    f"ریال است و {pct(share, 0)} درصد حاشیه سود ناخالص را می‌بلعد "
                    f"(جریمه دیرکرد ۴٪ ماهانه وصول‌شده، منهای هزینه سرمایه)."
                ),
                evidence_ids=ctx.ev(cid, "finance-net", "margin", "dso", "exposure"),
                value_at_stake=float(-r.net_finance_effect),
                suggested_bucket="fix",
                drag_share=share,
                depends_on_open_questions=["Q11"],
            ))
        return out
