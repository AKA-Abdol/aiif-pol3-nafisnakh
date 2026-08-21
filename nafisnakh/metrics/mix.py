"""Product mix: family ladder position, deflated price position, SKU breadth.

PLAN §1.7 is the governing rule: **no price metric is ever expressed in absolute
rials.** Trending absolute ASP flags 250 of 254 customers as "raising prices",
which is rial inflation, not a commercial signal. Every price number here is
either the customer's ASP divided by the market ASP that month, or the change in
that ratio against the customer's own baseline.

The family ladder (``schema.FAMILY_LADDER_RANK``) turns ``گروه کالا`` into an
ordinal so a shift from Family_05 toward Family_04 reads as a downgrade.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..io import schema as S
from .base import MetricContext, metric_table, num, pct, span_ref


@metric_table("mix")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    lines = ctx.spine.lines.copy()
    as_of = pd.Timestamp(ctx.as_of)

    lines["_ladder"] = lines[S.P_FAMILY].map(S.FAMILY_LADDER_RANK)
    lines["_ladder_w"] = lines["_ladder"] * lines[S.D_REVENUE]

    recent_start = as_of - pd.DateOffset(months=st.recent_window_months)
    base_start = recent_start - pd.DateOffset(months=st.baseline_window_months)

    def _slice(start, end):
        return lines.loc[(lines[S.F_DATE] > start) & (lines[S.F_DATE] <= end)]

    def _mix(df, suffix):
        g = df.groupby(S.CUSTOMER_ID)
        out = pd.DataFrame({
            f"ladder_{suffix}": g["_ladder_w"].sum() / g[S.D_REVENUE].sum().replace(0, np.nan),
            f"mix_skus_{suffix}": g[S.PRODUCT_ID].nunique(),
            f"families_{suffix}": g[S.P_FAMILY].nunique(),
            f"months_{suffix}": g[S.D_MONTH].nunique(),
        })
        out[f"skus_per_month_{suffix}"] = (
            out[f"mix_skus_{suffix}"] / out[f"months_{suffix}"].replace(0, np.nan)
        )
        return out

    recent = _mix(_slice(recent_start, as_of), "recent")
    baseline = _mix(_slice(base_start, recent_start), "baseline")
    df = recent.join(baseline, how="outer")

    df["ladder_delta"] = df["ladder_recent"] - df["ladder_baseline"]
    df["sku_change_pct"] = np.where(
        df["skus_per_month_baseline"] > 0,
        df["skus_per_month_recent"].fillna(0) / df["skus_per_month_baseline"] - 1.0,
        np.nan,
    )

    # ---- deflated price position (§1.7)
    cm = ctx.cohorts.customer_month.merge(ctx.cohorts.asp_index, on=S.D_MONTH, how="left")
    cm["price_position"] = cm["asp"] / cm["market_asp"]
    cm["_w"] = cm["revenue"]
    cm["_pw"] = cm["price_position"] * cm["_w"]

    def _pos(start, end, suffix):
        w = cm.loc[(cm[S.D_MONTH] > start) & (cm[S.D_MONTH] <= end)]
        g = w.groupby(S.CUSTOMER_ID)
        return (g["_pw"].sum() / g["_w"].sum().replace(0, np.nan)).rename(
            f"price_position_{suffix}"
        )

    df = df.join(_pos(recent_start, as_of, "recent"), how="left")
    df = df.join(_pos(base_start, recent_start, "baseline"), how="left")
    df["price_position_change"] = np.where(
        df["price_position_baseline"] > 0,
        df["price_position_recent"] / df["price_position_baseline"] - 1.0,
        np.nan,
    )
    # overall position, for cross-customer ranking
    g_all = cm.groupby(S.CUSTOMER_ID)
    df["price_position"] = (
        g_all["_pw"].sum() / g_all["_w"].sum().replace(0, np.nan)
    ).reindex(df.index)

    # dominant family, used to pick the peer cohort
    dom = (
        lines.groupby([S.CUSTOMER_ID, S.P_FAMILY])[S.D_REVENUE].sum()
        .reset_index().sort_values(S.D_REVENUE)
        .groupby(S.CUSTOMER_ID).tail(1).set_index(S.CUSTOMER_ID)[S.P_FAMILY]
    )
    df["dominant_family"] = dom.reindex(df.index)

    window = ctx.window(st.recent_window_months + st.baseline_window_months)
    n_lines = lines.groupby(S.CUSTOMER_ID)[S.SALES_LINE_ID].count()

    for cid, r in df.iterrows():
        ref = span_ref(S.S_SALES, cid, window, int(n_lines.get(cid, 0)))
        if pd.notna(r.price_position):
            ctx.emit(
                cid, "price-pos",
                f"موقعیت قیمتی این مشتری {num(r.price_position, 2)} برابر میانگین بازار "
                f"در همان ماه‌ها است (۱ یعنی دقیقاً هم‌سطح بازار).",
                float(r.price_position), unit=None, kind="comparison",
                window=window, source_rows=ref,
                formula="Σ(customer_asp/market_asp × revenue) / Σ revenue  [§1.7]",
                note="deflated; absolute rial ASP is never trended",
            )
        if pd.notna(r.price_position_change):
            ctx.emit(
                cid, "price-trend",
                f"موقعیت قیمتی تعدیل‌شده در {st.recent_window_months} ماه اخیر "
                f"{pct(r.price_position_change)} درصد تغییر کرده است.",
                float(r.price_position_change), unit="درصد", kind="comparison",
                window=window, source_rows=ref,
                formula="price_position_recent / price_position_baseline - 1",
            )
        if pd.notna(r.ladder_delta):
            ctx.emit(
                cid, "ladder",
                f"جایگاه سبد محصول روی نردبان خانواده کالا {num(r.ladder_delta, 2)} پله "
                f"تغییر کرده است (منفی یعنی حرکت به سمت خانواده ارزان‌تر).",
                float(r.ladder_delta), unit="پله", kind="comparison",
                window=window, source_rows=ref,
                formula="value-weighted family ladder rank, recent − baseline",
                ladder=S.FAMILY_LADDER_RANK,
            )
        if pd.notna(r.sku_change_pct):
            ctx.emit(
                cid, "sku-breadth",
                f"تنوع کد کالای خریداری‌شده در ماه {pct(r.sku_change_pct)} درصد تغییر "
                f"کرده است ({num(r.skus_per_month_recent, 1)} در برابر "
                f"{num(r.skus_per_month_baseline, 1)}).",
                float(r.sku_change_pct), unit="درصد", kind="comparison",
                window=window, source_rows=ref,
                formula="skus_per_month_recent / skus_per_month_baseline - 1",
            )
    return df
