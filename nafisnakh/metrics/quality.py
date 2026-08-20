"""Complaints, returns, and the همبافت blast radius.

Two integration rules shape this module:

* **Rule #3** — complaints reach sales lines only through the ``اتصال_شکایت``
  bridge. Never join ``شکایات`` to ``فروش`` on ``Product_ID``.
* **Rule #7** — ``Hembaft_ID`` and ``Lot_ID`` are independent identifiers that
  meet only through ``همبافت_لات``. Blast radius groups on ``Hembaft_ID``,
  never on ``Lot_ID``.

**Blast radius** (detector #18) is the differentiator: when one customer
complains about a همبافت, every *other* customer shipped from that same همبافت
is carrying a complaint that has not been filed yet. Nobody asked for this.

Recurrence is scoped to the *same customer* and the same mechanism. PLAN §5.4:
67% of universe-A complaint bodies are verbatim duplicates, so a naive
"cosine > 0.75 against any earlier complaint" flags 87.5% of the book; scoped
properly it is 8.7%.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.spine import visible
from ..io import schema as S
from .base import MetricContext, days_since, metric_table, money, num, pct, rows_ref


def hembaft_exposure(ctx: MetricContext) -> pd.DataFrame:
    """Sales lines expanded to their همبافت, via the bridge only (rule #7).

    Returns one row per (Hembaft_ID, Customer_ID, Sales_Line_ID) that was
    visible at ``as_of``.
    """
    bridge = visible(ctx.ds.hembaft_lot, ctx.as_of)[
        [S.HEMBAFT_LOT_KEY, S.HEMBAFT_ID, S.LOT_ID]
    ].drop_duplicates()
    lines = ctx.spine.lines[
        [S.SALES_LINE_ID, S.CUSTOMER_ID, S.LOT_ID, S.F_DATE, S.F_QTY, S.D_REVENUE]
    ]
    return bridge.merge(lines, on=S.LOT_ID, how="inner")


@metric_table("quality")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    as_of = pd.Timestamp(ctx.as_of)
    index = pd.Index(sorted(set(ctx.spine.customers) | set(ctx.ds.customers[S.CUSTOMER_ID])),
                     name=S.CUSTOMER_ID)

    comp = visible(ctx.ds.complaints, ctx.as_of).copy()
    comp = comp.loc[pd.to_datetime(comp[S.K_CREATED_AT], errors="coerce") <= as_of]
    comp["_severity_rank"] = comp[S.K_SEVERITY].map(
        {v: i for i, v in enumerate(S.SEVERITY_ORDER)}
    )
    comp["_resolved"] = pd.to_datetime(comp[S.K_RESOLVED_AT], errors="coerce")
    comp["_created"] = pd.to_datetime(comp[S.K_CREATED_AT], errors="coerce")
    comp["_open"] = comp["_resolved"].isna() | (comp["_resolved"] > as_of)
    comp["_age_days"] = np.where(
        comp["_open"], (as_of - comp["_created"]).dt.days,
        (comp["_resolved"] - comp["_created"]).dt.days,
    )

    g = comp.groupby(S.CUSTOMER_ID)
    df = pd.DataFrame(index=index)
    df["complaints_total"] = g[S.K_ID].count().reindex(index).fillna(0.0)
    df["complaints_open"] = g["_open"].sum().reindex(index).fillna(0.0)
    df["complaints_critical"] = (
        comp.loc[comp[S.K_SEVERITY] == "بحرانی"].groupby(S.CUSTOMER_ID)[S.K_ID].count()
        .reindex(index).fillna(0.0)
    )
    df["complaint_severity_max"] = g["_severity_rank"].max().reindex(index)
    df["complaint_last_at"] = g["_created"].max().reindex(index)
    df["days_since_complaint"] = days_since(as_of, df["complaint_last_at"])
    df["oldest_open_age_days"] = (
        comp.loc[comp["_open"]].groupby(S.CUSTOMER_ID)["_age_days"].max()
        .reindex(index)
    )
    df["resolution_days_median"] = (
        comp.loc[~comp["_open"]].groupby(S.CUSTOMER_ID)["_age_days"].median()
        .reindex(index)
    )

    # ---- recurrence, scoped to the same customer and the same title (§5.4).
    # The *mechanism*-level version of this runs in the LLM block; the title
    # here is the deterministic floor it improves on.
    comp_sorted = comp.sort_values([S.CUSTOMER_ID, "_created"])
    comp_sorted["_prev"] = comp_sorted.groupby([S.CUSTOMER_ID, "_title_norm"])["_created"].shift()
    comp_sorted["_gap"] = (comp_sorted["_created"] - comp_sorted["_prev"]).dt.days
    rec = comp_sorted.loc[comp_sorted["_gap"].between(0, st.complaint_recurrence_days)]
    df["complaint_recurrences"] = (
        rec.groupby(S.CUSTOMER_ID)[S.K_ID].count().reindex(index).fillna(0.0)
    )

    # ---- returns, through the bridge (rule #3) and from realised cost records
    lines = ctx.spine.lines
    shipped = lines.groupby(S.CUSTOMER_ID)[S.F_QTY].sum().reindex(index)
    returned = lines.groupby(S.CUSTOMER_ID)[S.RC_RETURN_QTY].sum().reindex(index).fillna(0.0)
    df["qty_shipped"] = shipped
    df["qty_returned"] = returned
    df["return_rate"] = returned / shipped.replace(0, np.nan)
    df["returns_value"] = (
        lines.groupby(S.CUSTOMER_ID)[S.RC_RETURN_AMOUNT].sum().reindex(index).fillna(0.0)
    )

    link = visible(ctx.ds.complaint_link, ctx.as_of, S.KL_AVAILABLE_AT)
    df["complaint_lines_linked"] = (
        link.groupby(S.CUSTOMER_ID)[S.SALES_LINE_ID].nunique().reindex(index).fillna(0.0)
    )
    df["complaint_open_results"] = (
        link.loc[link[S.KL_RESULT] == "باز"].groupby(S.CUSTOMER_ID)[S.K_ID]
        .nunique().reindex(index).fillna(0.0)
    )

    # ---- همبافت blast radius (rule #7, detector #18)
    exposure = hembaft_exposure(ctx)
    complained_hembaft = pd.concat([
        link[S.HEMBAFT_ID].dropna(),
        comp[S.K_HEMBAFT_REF].dropna().astype(str),
    ]).astype(str).unique()
    exposure["hembaft_key"] = exposure[S.HEMBAFT_ID].astype(str)
    complainants = (
        link.dropna(subset=[S.HEMBAFT_ID])
        .assign(hembaft_key=lambda d: d[S.HEMBAFT_ID].astype(str))
        .groupby("hembaft_key")[S.CUSTOMER_ID].apply(set)
    )
    hit = exposure.loc[exposure["hembaft_key"].isin(set(complained_hembaft))].copy()
    hit["is_complainant"] = [
        key in complainants.index and cust in complainants[key]
        for key, cust in zip(hit["hembaft_key"], hit[S.CUSTOMER_ID])
    ]
    at_risk = hit.loc[~hit["is_complainant"]]
    df["hembaft_at_risk_lines"] = (
        at_risk.groupby(S.CUSTOMER_ID)[S.SALES_LINE_ID].nunique().reindex(index).fillna(0.0)
    )
    df["hembaft_at_risk_qty"] = (
        at_risk.groupby(S.CUSTOMER_ID)[S.F_QTY].sum().reindex(index).fillna(0.0)
    )
    df["hembaft_at_risk_value"] = (
        at_risk.groupby(S.CUSTOMER_ID)[S.D_REVENUE].sum().reindex(index).fillna(0.0)
    )
    df["hembaft_at_risk_ids"] = (
        at_risk.groupby(S.CUSTOMER_ID)["hembaft_key"].apply(lambda s: sorted(set(s)))
        .reindex(index).apply(lambda v: v if isinstance(v, list) else [])
    )

    window = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)
    comp_ids = g[S.K_ID].apply(list)
    rec_ids = rec.groupby(S.CUSTOMER_ID)[S.K_ID].apply(list)

    for cid, r in df.iterrows():
        if r.complaints_total > 0:
            ref = rows_ref(S.S_COMPLAINTS, comp_ids.get(cid, []))
            ctx.emit(
                cid, "complaints",
                f"{num(r.complaints_total)} شکایت ثبت شده است که "
                f"{num(r.complaints_open)} مورد هنوز باز است.",
                float(r.complaints_total), unit="مورد", kind="event",
                window=window, source_rows=ref, formula="count(شکایات) [rule #3]",
            )
            if pd.notna(r.oldest_open_age_days):
                ctx.emit(
                    cid, "complaint-age",
                    f"قدیمی‌ترین شکایت باز {num(r.oldest_open_age_days)} روز است "
                    f"(میانه رسیدگی در کل دفتر {st.unresolved_aging_days} روز).",
                    float(r.oldest_open_age_days), unit="روز", kind="comparison",
                    window=window, source_rows=ref,
                    formula="as_of − Created_At for unresolved complaints",
                )
        if r.complaint_recurrences > 0:
            ctx.emit(
                cid, "complaint-repeat",
                f"{num(r.complaint_recurrences)} شکایت تکراری با همان عنوان و همان مشتری "
                f"در بازه {st.complaint_recurrence_days} روزه ثبت شده است.",
                float(r.complaint_recurrences), unit="مورد", kind="event",
                window=window, source_rows=rows_ref(S.S_COMPLAINTS, rec_ids.get(cid, [])),
                formula="same customer + same normalised title within N days",
                caveat="67% of universe-A bodies are verbatim duplicates; scoping to the "
                       "same customer is what keeps this at 8.7% rather than 87.5%",
            )
        if pd.notna(r.return_rate) and r.return_rate > 0:
            ctx.emit(
                cid, "returns",
                f"نرخ برگشتی {pct(r.return_rate, 2)} درصد وزن ارسالی است "
                f"({money(r.returns_value, st)} ریال).",
                float(r.return_rate), unit="درصد", window=window,
                source_rows=rows_ref(S.S_COST_REAL, [cid]),
                formula="Σ مقدار برگشتی / Σ مقدار",
            )
        if r.hembaft_at_risk_lines > 0:
            ids = r.hembaft_at_risk_ids
            ctx.emit(
                cid, "hembaft-risk",
                f"این مشتری از همبافت {', '.join(ids)} کالا دریافت کرده است که مشتری "
                f"دیگری روی همان همبافت شکایت ثبت کرده — {num(r.hembaft_at_risk_qty)} "
                f"کیلوگرم در معرض خطر.",
                float(r.hembaft_at_risk_qty), unit="کیلوگرم", kind="event",
                window=window,
                source_rows=rows_ref(S.S_HEMBAFT_LOT, ids),
                formula="complaint → Hembaft_ID → همبافت_لات → Lot_ID → فروش [rule #7]",
                hembaft_ids=ids,
            )
    return df
