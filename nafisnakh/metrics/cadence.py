"""Personalised purchase rhythm (PLAN §3.5).

Global recency is the wrong instrument here: a monthly buyer silent for 45 days
is critical, a quarterly buyer silent for 90 days is normal. Every cadence
number is therefore expressed against the customer's *own* distribution of
inter-purchase gaps. Median own-gap across the book is 14 days.

The invoice — not the sales line — is the purchase event: one invoice carries
many lines and counting lines would make every customer look hyperactive.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..io import schema as S
from .base import MetricContext, metric_table, num, rows_ref


@metric_table("cadence")
def build(ctx: MetricContext) -> pd.DataFrame:
    lines = ctx.spine.lines
    as_of = pd.Timestamp(ctx.as_of)

    # purchase events = distinct invoices, dated by their first line
    events = (
        lines.groupby([S.CUSTOMER_ID, S.INVOICE_NO], as_index=False)
        .agg(date=(S.F_DATE, "min"), revenue=(S.D_REVENUE, "sum"))
        .sort_values([S.CUSTOMER_ID, "date"])
    )
    events["_gap"] = events.groupby(S.CUSTOMER_ID)["date"].diff().dt.days

    agg = events.groupby(S.CUSTOMER_ID).agg(
        n_invoices=("date", "count"),
        first_purchase=("date", "min"),
        last_purchase=("date", "max"),
        median_gap=("_gap", "median"),
        p80_gap=("_gap", lambda s: s.quantile(0.80)),
        mean_gap=("_gap", "mean"),
        gap_cv=("_gap", lambda s: s.std() / s.mean() if s.mean() else np.nan),
        first_repeat_gap=("_gap", "first"),
    )
    agg["days_since_last"] = (as_of - agg["last_purchase"]).dt.days
    agg["active_days"] = (agg["last_purchase"] - agg["first_purchase"]).dt.days

    # Some customers place several invoices on the same day, so their median gap
    # is 0. Dropping them would silently exempt the fastest-cadence accounts —
    # exactly the ones whose silence matters most — so fall back to the mean gap
    # and floor at one day.
    effective = agg["median_gap"].where(agg["median_gap"] > 0, agg["mean_gap"])
    agg["effective_gap"] = effective.fillna(1.0).clip(lower=1.0)

    # the ratio detector #1 fires on; undefined for customers with too little history
    eligible = agg["n_invoices"] >= ctx.settings.cadence_min_invoices
    agg["cadence_eligible"] = eligible
    agg["cadence_ratio"] = np.where(
        eligible, agg["days_since_last"] / agg["effective_gap"], np.nan
    )
    agg["rhythm_regularity"] = 1.0 / (1.0 + agg["gap_cv"])   # 1 = perfectly regular

    invoice_ids = events.groupby(S.CUSTOMER_ID)[S.INVOICE_NO].apply(list)
    window = ctx.window(ctx.settings.long_window_months)

    for cid, r in agg.iterrows():
        ref = rows_ref(S.S_INVOICES, invoice_ids.get(cid, [])[-4:])
        ctx.emit(
            cid, "cadence-last",
            f"آخرین خرید {num(r.days_since_last)} روز پیش بوده است "
            f"(تاریخ {r.last_purchase.date().isoformat()}).",
            float(r.days_since_last), unit="روز", window=window, source_rows=ref,
            formula="as_of - max(تاریخ فاکتور)", n_invoices=int(r.n_invoices),
        )
        if pd.notna(r.median_gap):
            ctx.emit(
                cid, "cadence-median",
                f"میانه فاصله خرید این مشتری {num(r.median_gap)} روز است "
                f"(بر پایه {num(r.n_invoices)} فاکتور).",
                float(r.median_gap), unit="روز", window=window, source_rows=ref,
                formula="median(diff(invoice dates))",
            )
        if pd.notna(r.cadence_ratio):
            ctx.emit(
                cid, "cadence-ratio",
                f"نسبت سکوت به ریتم شخصی {num(r.cadence_ratio, 2)} برابر است "
                f"({num(r.days_since_last)} روز در برابر ریتم {num(r.effective_gap)} روز).",
                float(r.cadence_ratio), unit=None, kind="comparison",
                window=window, source_rows=ref,
                formula="days_since_last / own_effective_gap (median, else mean, floored at 1)",
            )
    return agg
