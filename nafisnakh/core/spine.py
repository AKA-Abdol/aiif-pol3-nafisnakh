"""The sales spine — one row per sales line, with cost, margin and as-of gating.

This is the single table every metric reads from. Two integration rules are
enforced structurally here rather than left to each caller:

* **Rule #2** — ``فروش`` is never joined to ``وصول``. Collections are aggregated
  to invoice grain first (:func:`invoice_collections`), so a customer with five
  collection events on one invoice cannot fan its sales lines out five-fold.
* **Rule #6** — realised and estimated cost are separate; realised wins. Every
  row records which basis produced its margin in ``_cost_source`` so any margin
  figure can be quoted with its coverage (realised covers only ~32% of lines).

Rule #4 (``Available_At``) is applied as a *visibility* filter: at a given
``as_of`` the system may only use rows it would actually have known about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..config import Settings, get_settings
from ..io import schema as S
from ..io.loader import Dataset
from ..io.normalize import month_floor


def _as_ts(d: date | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(d)


def visible(df: pd.DataFrame, as_of: date, column: str = S.AVAILABLE_AT) -> pd.DataFrame:
    """Integration rule #4 — a record is usable only from its ``Available_At`` on.

    Rows with a missing ``Available_At`` are kept: absence means the source had
    no visibility stamp, not that the row is invisible.
    """
    if column not in df.columns:
        return df
    stamp = pd.to_datetime(df[column], errors="coerce")
    return df.loc[stamp.isna() | (stamp <= _as_ts(as_of))]


def unit_cost_table(ds: Dataset, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Realised (line-grain) and planned (product × month) unit cost, both gated."""
    realized = visible(ds.cost_realized, as_of)
    realized = (
        realized.groupby(S.SALES_LINE_ID, as_index=False)
        .agg(
            **{
                S.RC_UNIT_COST: (S.RC_UNIT_COST, "mean"),
                S.RC_RETURN_QTY: (S.RC_RETURN_QTY, "sum"),
                S.RC_RETURN_AMOUNT: (S.RC_RETURN_AMOUNT, "sum"),
            }
        )
    )
    planned = visible(ds.cost_planned, as_of)
    # keep the latest estimate version per product × month
    planned = (
        planned.sort_values([S.PRODUCT_ID, S.MONTH_KEY, S.PC_VERSION])
        .groupby([S.PRODUCT_ID, S.MONTH_KEY], as_index=False)
        .tail(1)[[S.PRODUCT_ID, S.MONTH_KEY, S.PC_UNIT_COST]]
    )
    return realized, planned


@dataclass
class Spine:
    """Sales lines + cost + margin, plus the invoice-grain collection table."""

    lines: pd.DataFrame
    invoice_payments: pd.DataFrame
    as_of: date
    settings: Settings

    @property
    def customers(self) -> list[str]:
        return sorted(self.lines[S.CUSTOMER_ID].dropna().unique().tolist())

    def customer(self, customer_id: str) -> pd.DataFrame:
        return self.lines.loc[self.lines[S.CUSTOMER_ID] == customer_id]

    def window(self, months: int, end: date | None = None) -> pd.DataFrame:
        end_ts = _as_ts(end or self.as_of)
        start = end_ts - pd.DateOffset(months=months)
        d = self.lines[S.F_DATE]
        return self.lines.loc[(d > start) & (d <= end_ts)]

    def cost_coverage(self) -> dict[str, float]:
        n = len(self.lines)
        if not n:
            return {}
        return (
            self.lines[S.D_COST_SOURCE].value_counts(normalize=True).round(4).to_dict()
        )


def invoice_collections(ds: Dataset, as_of: date) -> pd.DataFrame:
    """Integration rule #2 — collapse ``وصول`` to one row per invoice *before*
    anything touches it. Returns amount collected, weighted days-late, bounce
    flag, first/last event dates and due date per invoice.
    """
    col = visible(ds.collections, as_of)
    col = col.copy()
    col[S.V_AMOUNT] = pd.to_numeric(col[S.V_AMOUNT], errors="coerce").fillna(0.0)
    col[S.V_DAYS_LATE] = pd.to_numeric(col[S.V_DAYS_LATE], errors="coerce")
    col["_bounced"] = (col[S.V_BOUNCED] == S.BOUNCED_YES).astype(int)
    col["_late_x_amount"] = col[S.V_DAYS_LATE] * col[S.V_AMOUNT]

    agg = col.groupby(S.INVOICE_NO, as_index=False).agg(
        _collected=(S.V_AMOUNT, "sum"),
        _late_x_amount=("_late_x_amount", "sum"),
        _days_late_mean=(S.V_DAYS_LATE, "mean"),
        _days_late_max=(S.V_DAYS_LATE, "max"),
        _bounces=("_bounced", "sum"),
        _events=(S.V_ID, "count"),
        _due_date=(S.V_DUE_DATE, "min"),
        _first_event=(S.V_EVENT_DATE, "min"),
        _last_event=(S.V_EVENT_DATE, "max"),
        _invoice_date=(S.V_INVOICE_DATE, "min"),
        **{S.CUSTOMER_ID: (S.CUSTOMER_ID, "first")},
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        agg["_days_late_wavg"] = np.where(
            agg["_collected"] > 0, agg["_late_x_amount"] / agg["_collected"], np.nan
        )
    return agg.drop(columns=["_late_x_amount"])


def build_spine(
    ds: Dataset, as_of: date | None = None, settings: Settings | None = None
) -> Spine:
    st = settings or ds.settings or get_settings()
    as_of = as_of or st.as_of

    sales = visible(ds.sales, as_of).copy()
    sales[S.F_DATE] = pd.to_datetime(sales[S.F_DATE], errors="coerce")
    sales = sales.loc[sales[S.F_DATE] <= _as_ts(as_of)]

    for c in (S.F_QTY, S.F_UNIT_PRICE, S.F_AMOUNT):
        sales[c] = pd.to_numeric(sales[c], errors="coerce")
    sales[S.D_MONTH] = month_floor(sales[S.F_DATE])
    sales["_month_key"] = sales[S.D_MONTH].dt.strftime("%Y-%m")

    # ---- product attributes (dimension join, no fan-out: Product_ID is a PK)
    prod = ds.products[[S.PRODUCT_ID, S.P_QUALITY_CLASS, S.P_SUBGROUP]].drop_duplicates(
        S.PRODUCT_ID
    )
    sales = sales.merge(prod, on=S.PRODUCT_ID, how="left", suffixes=("", "_prod"))

    # ---- cost (rule #6: realised wins, and we record which basis was used)
    realized, planned = unit_cost_table(ds, as_of)
    sales = sales.merge(realized, on=S.SALES_LINE_ID, how="left")

    plan_key = planned.rename(columns={S.MONTH_KEY: "_month_key"})
    # Month_Key in the planned-cost sheet may be "2020-05" or "2020-05-01"
    plan_key["_month_key"] = plan_key["_month_key"].astype(str).str.slice(0, 7)
    sales = sales.merge(plan_key, on=[S.PRODUCT_ID, "_month_key"], how="left")

    realized_cost = pd.to_numeric(sales[S.RC_UNIT_COST], errors="coerce")
    planned_cost = pd.to_numeric(sales[S.PC_UNIT_COST], errors="coerce")
    if st.cost_basis == "realized_only":
        unit_cost = realized_cost
        source = np.where(realized_cost.notna(), "realized", "none")
    else:
        unit_cost = realized_cost.fillna(planned_cost)
        source = np.where(
            realized_cost.notna(),
            "realized",
            np.where(planned_cost.notna(), "estimated", "none"),
        )
    sales[S.D_UNIT_COST] = unit_cost
    sales[S.D_COST_SOURCE] = source

    sales[S.D_REVENUE] = sales[S.F_AMOUNT]
    sales[S.D_GROSS_MARGIN] = sales[S.D_REVENUE] - sales[S.D_UNIT_COST] * sales[S.F_QTY]

    sales[S.RC_RETURN_QTY] = pd.to_numeric(
        sales.get(S.RC_RETURN_QTY), errors="coerce"
    ).fillna(0.0)
    sales[S.RC_RETURN_AMOUNT] = pd.to_numeric(
        sales.get(S.RC_RETURN_AMOUNT), errors="coerce"
    ).fillna(0.0)

    payments = invoice_collections(ds, as_of)
    return Spine(lines=sales, invoice_payments=payments, as_of=as_of, settings=st)
