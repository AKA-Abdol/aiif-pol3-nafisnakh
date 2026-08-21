"""Peer cohorts — the denominator for every "is this customer unusual?" question.

PLAN §1.7 is the reason this module exists: absolute rial figures are worthless
here (250 of 254 customers "raise prices" if you trend absolute ASP — that is
inflation, not signal). Every price and margin comparison therefore runs against
either the customer's own baseline or a peer cohort.

Two cohort grains:

* **segment × family × month** — the fine grain used for price position and
  margin percentile, per PLAN §3.2.
* **segment** — the fallback when a fine cell is too thin to rank against.

Plus the market-wide monthly ASP index used to deflate prices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..io import schema as S
from .spine import Spine

MIN_COHORT_MEMBERS = 5


@dataclass
class Cohorts:
    """Precomputed cohort tables. All grains keyed on the ``_month`` floor."""

    asp_index: pd.DataFrame          # _month → market ASP (rial/kg)
    customer_month: pd.DataFrame     # customer × month: qty, revenue, margin, asp
    cell_stats: pd.DataFrame         # segment × family × month percentile stats
    segment_stats: pd.DataFrame      # segment × month fallback
    customer_segment: pd.Series      # customer → segment

    def deflated_asp(self, customer_id: str) -> pd.DataFrame:
        """Customer monthly ASP divided by the market ASP that month (§1.7).

        1.0 = priced exactly at the book average that month; the observed
        cross-customer spread is p10 0.75 → p90 1.50.
        """
        cm = self.customer_month
        rows = cm.loc[cm[S.CUSTOMER_ID] == customer_id, [S.D_MONTH, "asp", "qty", "revenue"]]
        out = rows.merge(self.asp_index, on=S.D_MONTH, how="left")
        out["price_position"] = out["asp"] / out["market_asp"]
        return out.sort_values(S.D_MONTH)

    def margin_percentile(self, customer_id: str, family: str | None = None) -> float | None:
        """Where this customer's margin rate sits inside its peer cohort, 0–100."""
        seg = self.customer_segment.get(customer_id)
        if seg is None:
            return None
        cm = self.customer_month
        peers = cm.loc[cm["segment"] == seg]
        if family is not None and "family" in peers.columns:
            fam_peers = peers.loc[peers["family"] == family]
            if fam_peers[S.CUSTOMER_ID].nunique() >= MIN_COHORT_MEMBERS:
                peers = fam_peers
        rates = (
            peers.groupby(S.CUSTOMER_ID)
            .apply(lambda g: g["margin"].sum() / g["revenue"].sum()
                   if g["revenue"].sum() else np.nan, include_groups=False)
            .dropna()
        )
        if customer_id not in rates.index or len(rates) < MIN_COHORT_MEMBERS:
            return None
        return float((rates < rates[customer_id]).mean() * 100.0)


def build_cohorts(spine: Spine, customers: pd.DataFrame) -> Cohorts:
    lines = spine.lines
    seg = (
        customers[[S.CUSTOMER_ID, S.C_SEGMENT]]
        .drop_duplicates(S.CUSTOMER_ID)
        .set_index(S.CUSTOMER_ID)[S.C_SEGMENT]
    )

    # ---- market-wide monthly ASP: the deflator (§1.7)
    monthly = lines.groupby(S.D_MONTH, as_index=False).agg(
        _rev=(S.D_REVENUE, "sum"), _qty=(S.F_QTY, "sum")
    )
    monthly["market_asp"] = monthly["_rev"] / monthly["_qty"].replace(0, np.nan)
    asp_index = monthly[[S.D_MONTH, "market_asp"]]

    # ---- customer × month × family grain
    cm = lines.groupby(
        [S.CUSTOMER_ID, S.D_MONTH, S.P_FAMILY], as_index=False
    ).agg(
        qty=(S.F_QTY, "sum"),
        revenue=(S.D_REVENUE, "sum"),
        margin=(S.D_GROSS_MARGIN, "sum"),
        lines=(S.SALES_LINE_ID, "count"),
        skus=(S.PRODUCT_ID, "nunique"),
    )
    cm = cm.rename(columns={S.P_FAMILY: "family"})
    cm["asp"] = cm["revenue"] / cm["qty"].replace(0, np.nan)
    cm["margin_rate"] = cm["margin"] / cm["revenue"].replace(0, np.nan)
    cm["segment"] = cm[S.CUSTOMER_ID].map(seg)

    # ---- segment × family × month percentile stats
    cell_stats = (
        cm.groupby(["segment", "family", S.D_MONTH])
        .agg(
            n_customers=(S.CUSTOMER_ID, "nunique"),
            asp_p50=("asp", "median"),
            margin_rate_p20=("margin_rate", lambda s: s.quantile(0.20)),
            margin_rate_p50=("margin_rate", "median"),
            margin_rate_p80=("margin_rate", lambda s: s.quantile(0.80)),
        )
        .reset_index()
    )
    segment_stats = (
        cm.groupby(["segment", S.D_MONTH])
        .agg(
            n_customers=(S.CUSTOMER_ID, "nunique"),
            asp_p50=("asp", "median"),
            margin_rate_p20=("margin_rate", lambda s: s.quantile(0.20)),
            margin_rate_p50=("margin_rate", "median"),
        )
        .reset_index()
    )

    return Cohorts(
        asp_index=asp_index,
        customer_month=cm,
        cell_stats=cell_stats,
        segment_stats=segment_stats,
        customer_segment=seg,
    )
