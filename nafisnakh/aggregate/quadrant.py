"""The four buckets: grow · protect · fix · reduce (PLAN §0).

The user's strategy in their own words:

> هدف اصلی بیزینس درآمد بیشتر است … یکی از اهداف کلی ما این است که **تعداد
> مشتریان را کمتر ولی حاشیه سود را بیشتر و ثابت نگه داریم**.

Two axes decide the bucket, and both are deliberately chosen:

* **Profitability** is *risk-adjusted* margin, not gross margin. A customer who
  pays gross margin back in cost-to-serve and tied-up capital is not profitable,
  and calling them profitable is how a book fills up with accounts nobody wants.
* **The second axis differs by side.** For a profitable customer the question is
  "is there more to get?" → headroom, which sorts grow from protect. For an
  unprofitable one the question is "is this worth fixing?" → materiality, which
  sorts fix from reduce. A big unprofitable account is a contract to renegotiate;
  a small one is energy to stop spending.

Every assignment carries its own evidence and a Persian reason string, so the
bucket is never a bare label on a slide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ..io import schema as S
from ..metrics.base import MetricContext, money, num, pct, rows_ref

Bucket = Literal["grow", "protect", "fix", "reduce"]

BUCKET_LABEL_FA = {
    "grow": "رشد",
    "protect": "حفظ",
    "fix": "اصلاح",
    "reduce": "کاهش",
}
BUCKET_MEANING_FA = {
    "grow": "سودده است و جای رشد دارد — انرژی فروش اینجا بازده دارد.",
    "protect": "سودده و کم‌دردسر است — فقط باید مراقبش بود.",
    "fix": "حجم واقعی دارد اما سودی نمی‌دهد — شرایط قرارداد باید تغییر کند.",
    "reduce": "هم خرید کم است هم سود — پیشنهاد ویژه و انرژی فروش برایش صرف نشود.",
}


@dataclass
class QuadrantResult:
    table: pd.DataFrame
    profit_threshold: float
    materiality_threshold: float
    headroom_threshold: float

    def counts(self) -> dict[str, int]:
        return self.table["bucket"].value_counts().to_dict()

    def bucket_of(self, customer_id: str) -> Bucket | None:
        if customer_id not in self.table.index:
            return None
        return self.table.loc[customer_id, "bucket"]


def assign_quadrants(ctx: MetricContext) -> QuadrantResult:
    econ = ctx.table("economics")
    wallet = ctx.table("wallet").reindex(econ.index)
    st = ctx.settings

    df = pd.DataFrame(index=econ.index)
    df["revenue_total"] = econ["revenue_total"]
    df["risk_adj_margin"] = econ["risk_adj_margin"]
    df["risk_adj_margin_rate"] = econ["risk_adj_margin_rate"]
    df["margin_rate"] = econ["margin_rate"]
    df["headroom_value"] = wallet["headroom_value"]
    df["capacity_gap_ratio"] = wallet["capacity_gap_ratio"]
    df["headroom_source"] = wallet["headroom_source"]

    profit_threshold = 0.0
    materiality_threshold = float(econ["revenue_total"].median())
    headroom_threshold = float(st.wallet_headroom_share_max)

    profitable = df["risk_adj_margin_rate"].fillna(-1.0) > profit_threshold
    material = df["revenue_total"] >= materiality_threshold
    has_headroom = df["capacity_gap_ratio"].fillna(1.0) < headroom_threshold

    df["bucket"] = np.select(
        [
            profitable & has_headroom,
            profitable & ~has_headroom,
            ~profitable & material,
        ],
        ["grow", "protect", "fix"],
        default="reduce",
    )
    df["bucket_label_fa"] = df["bucket"].map(BUCKET_LABEL_FA)
    df["profitable"] = profitable
    df["material"] = material
    df["has_headroom"] = has_headroom

    reasons = []
    window = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)
    for cid, r in df.iterrows():
        if r.bucket == "grow":
            reason = (
                f"حاشیه سود ریسک‌تعدیل‌شده {pct(r.risk_adj_margin_rate)} درصد مثبت است و "
                f"تنها {pct(r.capacity_gap_ratio, 0)} درصد سطح خرید همتایان را دارد."
            )
        elif r.bucket == "protect":
            reason = (
                f"حاشیه سود ریسک‌تعدیل‌شده {pct(r.risk_adj_margin_rate)} درصد مثبت است و "
                f"سطح خرید نزدیک به ظرفیت همتایان است."
            )
        elif r.bucket == "fix":
            reason = (
                f"درآمد {money(r.revenue_total, ctx.settings)} ریال است اما حاشیه سود "
                f"ریسک‌تعدیل‌شده {pct(r.risk_adj_margin_rate)} درصد — حجم هست، سود نیست."
            )
        else:
            reason = (
                f"هم درآمد پایین است ({money(r.revenue_total, ctx.settings)} ریال) و هم "
                f"حاشیه سود ریسک‌تعدیل‌شده {pct(r.risk_adj_margin_rate)} درصد."
            )
        reasons.append(reason)
        ctx.emit(
            cid, "bucket",
            f"دسته‌بندی: {BUCKET_LABEL_FA[r.bucket]} — {reason}",
            r.bucket, unit=None, kind="comparison", window=window,
            source_rows=rows_ref(S.S_SALES, [cid], key=S.CUSTOMER_ID),
            formula=("risk_adj_margin_rate > 0 × (capacity_gap_ratio < "
                     f"{headroom_threshold} | revenue ≥ median)"),
            assumption=True, confidence=0.6,
            open_questions=["Q7 real cost data", "Q11 wacc_monthly", "Q12 cost-to-serve"],
        )
    df["bucket_reason_fa"] = reasons
    return QuadrantResult(
        table=df,
        profit_threshold=profit_threshold,
        materiality_threshold=materiality_threshold,
        headroom_threshold=headroom_threshold,
    )
