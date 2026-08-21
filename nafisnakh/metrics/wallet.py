"""Share of wallet and headroom — with the leakage caveat encoded, not hidden.

PLAN §1.2 corrected a headline claim about this sheet, and the correction has to
survive into the code or it will be re-derived by the next reader:

``Nafis_Purchase == 0`` **exactly** when there were no sales that month — 0
exceptions in 7,488 rows, correlation 0.83 with actual monthly sales. So
``wallet_share`` mechanically encodes recency: it is label leakage, and the
published conclusion ("customers leave when Nafis is a minor supplier, not when
they stop buying") is inverted — it *is* "they stopped buying". Among genuinely
active months the share is uniform on [0.25, 0.75], i.e. pure noise; the famous
9.8% mean is an artifact of averaging in 80% zero-months.

Two consequences, both implemented:

1. Share is computed **over active months only**, and every wallet evidence
   carries the leakage caveat in its ``provenance``.
2. ``سهم_سبد`` covers 2021-07 … 2022-06 only, so at the demo anchor
   (``as_of = 2021-06-30``) *nothing in it is visible yet*. Headroom therefore
   falls back to a **peer-capacity estimate**: what a customer of this segment
   and this purchase rhythm would typically buy, versus what they actually buy.
   The fallback is marked ``estimated`` with confidence 0.5 — it is a lead, not
   a measurement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.spine import visible
from ..io import schema as S
from .base import MetricContext, metric_table, money, num, pct, rows_ref

LEAKAGE_CAVEAT = (
    "Nafis_Purchase == 0 exactly when there were no sales that month (0 exceptions "
    "in 7,488 rows), so raw wallet_share encodes recency, not competitive position. "
    "Share here is computed over ACTIVE months only; among those it is uniform on "
    "[0.25, 0.75] in this dataset — treat magnitude as unreliable. PLAN §1.2."
)


@metric_table("wallet")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    index = pd.Index(sorted(set(ctx.spine.customers) | set(ctx.ds.customers[S.CUSTOMER_ID])),
                     name=S.CUSTOMER_ID)
    df = pd.DataFrame(index=index)

    w = visible(ctx.ds.wallet, ctx.as_of).copy()
    df["wallet_rows_visible"] = (
        w.groupby(S.CUSTOMER_ID)[S.MONTH_KEY].count().reindex(index).fillna(0.0)
        if len(w) else 0.0
    )

    if len(w):
        w[S.W_ESTIMATED_TOTAL] = pd.to_numeric(w[S.W_ESTIMATED_TOTAL], errors="coerce")
        w[S.W_NAFIS_PURCHASE] = pd.to_numeric(w[S.W_NAFIS_PURCHASE], errors="coerce")
        active = w.loc[w[S.W_NAFIS_PURCHASE] > 0]          # drop the zero-months
        ag = active.groupby(S.CUSTOMER_ID)
        df["wallet_months_active"] = ag[S.MONTH_KEY].count().reindex(index).fillna(0.0)
        df["estimated_total_purchase"] = ag[S.W_ESTIMATED_TOTAL].mean().reindex(index)
        df["nafis_purchase_mean"] = ag[S.W_NAFIS_PURCHASE].mean().reindex(index)
        df["wallet_share_active"] = (
            df["nafis_purchase_mean"] / df["estimated_total_purchase"].replace(0, np.nan)
        )
        df["main_competitor"] = (
            active.groupby(S.CUSTOMER_ID)[S.W_COMPETITOR]
            .agg(lambda s: s.mode().iat[0] if len(s.mode()) else None).reindex(index)
        )
        df["wallet_source"] = np.where(df["wallet_share_active"].notna(), "reported", "none")
    else:
        for c in ("wallet_months_active", "estimated_total_purchase",
                  "nafis_purchase_mean", "wallet_share_active"):
            df[c] = np.nan
        df["main_competitor"] = None
        df["wallet_source"] = "none"

    # ---- peer-capacity fallback (see the module docstring)
    econ = ctx.tables.get("economics")
    cad = ctx.tables.get("cadence")
    if econ is not None and cad is not None:
        rev = econ["revenue_total"].reindex(index)
        months = (
            ctx.spine.lines.groupby(S.CUSTOMER_ID)[S.D_MONTH].nunique()
            .reindex(index).replace(0, np.nan)
        )
        rev_per_active_month = rev / months
        seg = econ["segment"].reindex(index)
        # capacity proxy: the 75th percentile of revenue-per-active-month inside
        # the customer's own segment. A customer buying far below the peers it
        # resembles has headroom; one at or above it does not.
        peer_p75 = rev_per_active_month.groupby(seg).transform(
            lambda s: s.quantile(0.75)
        )
        df["revenue_per_active_month"] = rev_per_active_month
        df["peer_capacity_per_month"] = peer_p75
        df["capacity_gap_ratio"] = rev_per_active_month / peer_p75.replace(0, np.nan)
        est_share = df["wallet_share_active"]
        df["estimated_share"] = est_share.fillna(df["capacity_gap_ratio"].clip(upper=1.0))
        df["headroom_value"] = (peer_p75 - rev_per_active_month).clip(lower=0.0) * months
        df["headroom_source"] = np.where(
            est_share.notna(), "reported", "peer_capacity_estimate"
        )
    else:
        df["estimated_share"] = df.get("wallet_share_active")
        df["headroom_value"] = np.nan
        df["headroom_source"] = "none"

    window = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)
    for cid, r in df.iterrows():
        reported = r.get("wallet_source") == "reported"
        if reported and pd.notna(r.wallet_share_active):
            ctx.emit(
                cid, "wallet-share",
                f"سهم ما از سبد خرید این مشتری در ماه‌های فعال حدود "
                f"{pct(r.wallet_share_active, 0)} درصد است "
                f"(رقیب اصلی: {r.main_competitor}).",
                float(r.wallet_share_active), unit="درصد", kind="comparison",
                window=window, source_rows=rows_ref(S.S_WALLET, [cid], key=S.CUSTOMER_ID),
                formula="mean(Nafis_Purchase)/mean(Estimated_Total_Purchase) over ACTIVE months",
                caveat=LEAKAGE_CAVEAT, confidence=0.5, assumption=False,
            )
        if pd.notna(r.get("headroom_value")) and r.headroom_value > 0:
            estimated = r.headroom_source == "peer_capacity_estimate"
            ctx.emit(
                cid, "headroom",
                f"ظرفیت رشد برآوردی این مشتری {money(r.headroom_value, st)} ریال است "
                f"({num(r.capacity_gap_ratio, 2)} برابر همتایان هم‌بخش خود خرید می‌کند).",
                float(r.headroom_value), unit="ریال", kind="comparison",
                window=window, source_rows=rows_ref(S.S_SALES, [cid], key=S.CUSTOMER_ID),
                formula=("(peer_p75_revenue_per_active_month − own) × active_months"
                         if estimated else
                         "(Estimated_Total_Purchase − Nafis_Purchase) over active months"),
                confidence=0.5 if estimated else 0.7,
                assumption=estimated,
                source=r.headroom_source,
                caveat=(LEAKAGE_CAVEAT if not estimated else
                        "سهم‌سبد در این تاریخ هنوز در دسترس نیست؛ این عدد برآورد "
                        "مبتنی بر همتایان است، نه اندازه‌گیری."),
            )
    return df
