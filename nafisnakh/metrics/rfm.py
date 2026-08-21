"""RFM — recency, frequency, monetary, ranked inside the book (PLAN §3.2).

Why this exists alongside :mod:`nafisnakh.metrics.cadence`, which already knows
when each customer last bought: the two answer different questions and a sales
manager needs both.

* ``cadence`` is **self-relative**. "This customer is 3.2× their own rhythm
  quiet" is the right instrument for *is something wrong here*, and it is why a
  monthly buyer silent 45 days outranks a quarterly buyer silent 80.
* ``rfm`` is **book-relative**. "R2 F5 M5" is the right instrument for *where
  does this account sit among the others*, which is what portfolio decisions —
  who gets the campaign, who gets the visit, who gets nothing — are made on.

Scores are quintiles of the *rank*, not of the raw value, so the distribution is
uniform by construction and a handful of enormous accounts cannot compress
everyone else into one bucket. Ties share a score, which is why the zero-purchase
tail all lands on 1 rather than being split arbitrarily.

The window is the standing long window (12 months) for frequency and monetary;
recency is measured over the whole visible history, because "last bought 400 days
ago" is a fact about the relationship, not about the window.

Everything here is **state**, never outcome — the governing rule for this
dataset (PLAN §1.2). Nothing in this table predicts anything; it describes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..io import schema as S
from .base import (
    MetricContext,
    metric_table,
    money,
    num,
    rows_ref,
    span_ref,
)

# The six states, in the language the sales manager uses. `fm` is the mean of
# the frequency and monetary scores — how much this account is worth having —
# and `r` is how alive it is right now.
SEGMENT_FA = {
    "champion": "قهرمان",
    "promising": "امیدبخش",
    "small_or_new": "کم‌خرید یا تازه‌وارد",
    "at_risk": "در معرض ریزش",
    "hibernating": "خوابیده",
    "needs_attention": "نیازمند توجه",
}
SEGMENT_MEANING_FA = {
    "champion": "هم تازه خرید کرده و هم از نظر تعداد و مبلغ در بالای دفتر است.",
    "promising": "تازه خرید کرده اما هنوز حجمش متوسط است.",
    "small_or_new": "تازه خرید کرده ولی تعداد و مبلغ خریدش پایین دفتر است.",
    "at_risk": "ارزشمند است اما مدت‌هاست خرید نکرده — این پرونده فوریت دارد.",
    "hibernating": "هم مدت‌هاست خرید نکرده و هم حجمش پایین بوده است.",
    "needs_attention": "در میانه دفتر است؛ نه هشدار روشن، نه فرصت روشن.",
}


def _quintile(values: pd.Series, ascending: bool) -> pd.Series:
    """1–5 from the rank, not from the value.

    ``ascending=False`` means *small is good* (recency). Ranking first is what
    keeps one 50× account from flattening the other five hundred into a single
    monetary bucket.
    """
    ranked = values.rank(method="average", pct=True, ascending=ascending)
    # 0 < pct <= 1 → 1..5; ceil so the top rank lands on 5 and nothing lands on 0
    return np.ceil(ranked * 5).clip(1, 5).fillna(1).astype(int)


def segment_of(r: int, f: int, m: int) -> str:
    fm = (f + m) / 2.0
    if r >= 4 and fm >= 4:
        return "champion"
    if r >= 4 and fm <= 2:
        return "small_or_new"
    if r >= 4:
        return "promising"
    if r <= 2 and fm >= 4:
        return "at_risk"
    if r <= 2 and fm <= 2:
        return "hibernating"
    return "needs_attention"


@metric_table("rfm")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    as_of = pd.Timestamp(ctx.as_of)
    lines = ctx.spine.lines
    index = pd.Index(sorted(set(ctx.spine.customers)), name=S.CUSTOMER_ID)

    # The purchase event is the invoice, exactly as in `cadence` — counting
    # sales lines would make a customer who buys ten SKUs at once look ten times
    # more frequent than one who buys the same money in a single SKU.
    orders = (
        lines.groupby([S.CUSTOMER_ID, S.INVOICE_NO], as_index=False)
        .agg(date=(S.F_DATE, "min"), revenue=(S.D_REVENUE, "sum"))
    )
    window = ctx.window(st.long_window_months)
    w_start = pd.Timestamp(window[0])
    recent = orders.loc[orders["date"] > w_start]

    df = pd.DataFrame(index=index)
    df["last_purchase"] = orders.groupby(S.CUSTOMER_ID)["date"].max().reindex(index)
    df["recency_days"] = (as_of - df["last_purchase"]).dt.days
    df["frequency_orders"] = (
        recent.groupby(S.CUSTOMER_ID)[S.INVOICE_NO].nunique().reindex(index).fillna(0.0)
    )
    df["monetary_value"] = (
        recent.groupby(S.CUSTOMER_ID)["revenue"].sum().reindex(index).fillna(0.0)
    )
    # Typical order value is measured over the whole visible history, not the
    # window: it is a property of how this customer buys, and a customer with two
    # orders in the window would otherwise get a number built on two rows.
    df["median_order_value"] = (
        orders.groupby(S.CUSTOMER_ID)["revenue"].median().reindex(index).fillna(0.0)
    )
    df["orders_total"] = (
        orders.groupby(S.CUSTOMER_ID)[S.INVOICE_NO].nunique().reindex(index).fillna(0.0)
    )

    df["r_score"] = _quintile(df["recency_days"], ascending=False)
    df["f_score"] = _quintile(df["frequency_orders"], ascending=True)
    df["m_score"] = _quintile(df["monetary_value"], ascending=True)
    df["rfm_cell"] = (
        df["r_score"].astype(str) + df["f_score"].astype(str) + df["m_score"].astype(str)
    )
    df["rfm_score"] = df[["r_score", "f_score", "m_score"]].sum(axis=1)
    df["rfm_segment"] = [
        segment_of(int(r), int(f), int(m))
        for r, f, m in zip(df["r_score"], df["f_score"], df["m_score"])
    ]
    df["rfm_segment_fa"] = df["rfm_segment"].map(SEGMENT_FA)

    order_ids = orders.sort_values("date").groupby(S.CUSTOMER_ID)[S.INVOICE_NO].apply(list)

    # The drill-down spans the whole visible history, not the 12-month scoring
    # window. For the 77 customers with nothing in the window the window slice is
    # empty, and an evidence that opens onto no rows is exactly what step 1 was
    # built to prevent — while their order history is precisely what makes both
    # "last bought 373 days ago" and "zero orders in the window" true.
    history = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)
    n_lines = lines.groupby(S.CUSTOMER_ID)[S.SALES_LINE_ID].nunique()

    for cid, r in df.iterrows():
        ctx.emit(
            cid, "rfm",
            f"جایگاه این مشتری در دفتر RFM برابر {r.rfm_cell} است "
            f"(تازگی {num(r.r_score)}، تکرار {num(r.f_score)}، مبلغ {num(r.m_score)} از 5) — "
            f"{r.rfm_segment_fa}: {SEGMENT_MEANING_FA[r.rfm_segment]}",
            str(r.rfm_cell), unit=None, kind="comparison", window=history,
            source_rows=span_ref(S.S_SALES, cid, history, int(n_lines.get(cid, 0) or 0)),
            formula=("quintile of rank within the book: recency over all visible "
                     f"history, frequency and monetary over {st.long_window_months} months"),
            segment=r.rfm_segment,
            recency_days=None if pd.isna(r.recency_days) else int(r.recency_days),
            frequency_orders=int(r.frequency_orders),
        )
        if r.median_order_value > 0:
            ctx.emit(
                cid, "order-value",
                f"سفارش معمول این مشتری {money(r.median_order_value, st)} ریال است "
                f"(میانه {num(r.orders_total)} فاکتور).",
                float(r.median_order_value), unit="ریال", window=window,
                source_rows=rows_ref(S.S_INVOICES, order_ids.get(cid, [])[-4:]),
                formula="median(sum of line revenue per invoice)",
            )
    return df
