"""Revenue, volume, gross margin, risk-adjusted margin and LTV (PLAN §3.5).

The margin figures here are the backbone of the grow/protect/fix/reduce call,
so two honesty constraints are built in rather than bolted on:

* **Cost basis is always quoted.** Realised cost covers only ~32% of lines; the
  rest falls back to the monthly estimate. Every margin evidence carries its
  realised/estimated mix in ``provenance``.
* **Risk-adjusted margin depends on unanswered questions.** ``wacc_monthly``
  (Q11) and the cost-to-serve rate card (Q12) are configuration assumptions
  today, so the risk-adjusted figures are emitted with ``assumption: true`` and
  confidence 0.6. If Nafis Nakh's cost of capital turns out to be below the 4%
  monthly late charge they actually collect, a slow payer is *net accretive* —
  which moves customers between ``fix`` and ``protect``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..io import schema as S
from .base import MetricContext, metric_table, money, num, pct, span_ref


def _window_agg(lines: pd.DataFrame, start, end, suffix: str) -> pd.DataFrame:
    w = lines.loc[(lines[S.F_DATE] > pd.Timestamp(start)) & (lines[S.F_DATE] <= pd.Timestamp(end))]
    out = w.groupby(S.CUSTOMER_ID).agg(
        **{
            f"qty_{suffix}": (S.F_QTY, "sum"),
            f"revenue_{suffix}": (S.D_REVENUE, "sum"),
            f"margin_{suffix}": (S.D_GROSS_MARGIN, "sum"),
            f"lines_{suffix}": (S.SALES_LINE_ID, "count"),
            f"skus_{suffix}": (S.PRODUCT_ID, "nunique"),
        }
    )
    return out


@metric_table("economics")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    lines = ctx.spine.lines
    as_of = pd.Timestamp(ctx.as_of)

    total = lines.groupby(S.CUSTOMER_ID).agg(
        qty_total=(S.F_QTY, "sum"),
        revenue_total=(S.D_REVENUE, "sum"),
        margin_total=(S.D_GROSS_MARGIN, "sum"),
        lines_total=(S.SALES_LINE_ID, "count"),
        skus_total=(S.PRODUCT_ID, "nunique"),
        returns_qty=(S.RC_RETURN_QTY, "sum"),
        returns_value=(S.RC_RETURN_AMOUNT, "sum"),
    )

    recent_start = as_of - pd.DateOffset(months=st.recent_window_months)
    base_start = recent_start - pd.DateOffset(months=st.baseline_window_months)
    df = (
        total
        .join(_window_agg(lines, recent_start, as_of, "recent"), how="left")
        .join(_window_agg(lines, base_start, recent_start, "baseline"), how="left")
        .fillna({c: 0.0 for c in ("qty_recent", "revenue_recent", "margin_recent",
                                  "lines_recent", "skus_recent", "qty_baseline",
                                  "revenue_baseline", "margin_baseline",
                                  "lines_baseline", "skus_baseline")})
    )

    df["margin_rate"] = df["margin_total"] / df["revenue_total"].replace(0, np.nan)
    df["margin_rate_recent"] = df["margin_recent"] / df["revenue_recent"].replace(0, np.nan)
    df["asp_total"] = df["revenue_total"] / df["qty_total"].replace(0, np.nan)

    # volume trend, normalised per month so a 3m window compares to a 6m baseline
    monthly_recent = df["qty_recent"] / st.recent_window_months
    monthly_base = df["qty_baseline"] / st.baseline_window_months
    df["volume_change_pct"] = np.where(
        monthly_base > 0, monthly_recent / monthly_base - 1.0, np.nan
    )
    df["revenue_share"] = df["revenue_total"] / df["revenue_total"].sum()

    # cost-basis mix per customer — quoted with every margin number
    basis = (
        lines.assign(_r=(lines[S.D_COST_SOURCE] == "realized").astype(float))
        .groupby(S.CUSTOMER_ID)["_r"].mean()
    )
    df["cost_basis_realized_share"] = basis

    # ---- tenure (needs the Jalali fix, PLAN §1.5, or NaN for the 20 real customers)
    cust = ctx.customers
    start = pd.to_datetime(cust[S.C_START_DATE], errors="coerce")
    df["tenure_days"] = (as_of - start.reindex(df.index)).dt.days
    df["segment"] = cust[S.C_SEGMENT].reindex(df.index)

    # ---- risk-adjusted margin (PLAN §3.5)
    pay = ctx.tables.get("payment")
    if pay is not None:
        pay = pay.reindex(df.index)
        late_charge = pay["late_charge_revenue"].fillna(0.0)
        capital_cost = pay["capital_cost"].fillna(0.0)
        bad_debt = pay["bad_debt_provision"].fillna(0.0)
    else:                                   # payment builds first; guard anyway
        late_charge = capital_cost = bad_debt = pd.Series(0.0, index=df.index)

    qual = ctx.tables.get("quality")
    eng = ctx.tables.get("engagement")
    n_complaints = (
        qual["complaints_total"].reindex(df.index).fillna(0.0)
        if qual is not None else pd.Series(0.0, index=df.index)
    )
    n_dev = (
        eng["dev_requests_total"].reindex(df.index).fillna(0.0)
        if eng is not None else pd.Series(0.0, index=df.index)
    )
    # cost-to-serve is priced in median invoices, not in absolute rials (Q12)
    invoice_values = lines.groupby(S.INVOICE_NO)[S.D_REVENUE].sum()
    serve_unit = float(invoice_values.median() or 0.0)

    returns_events = (
        lines.assign(_r=(lines[S.RC_RETURN_QTY] > 0).astype(float))
        .groupby(S.CUSTOMER_ID)["_r"].sum().reindex(df.index).fillna(0.0)
    )
    df["returns_events"] = returns_events
    df["cost_to_serve"] = serve_unit * (
        n_complaints * st.cost_to_serve_complaint_invoices
        + n_dev * st.cost_to_serve_dev_request_invoices
        + returns_events * st.cost_to_serve_return_invoices
    ) + df["returns_value"].fillna(0.0)
    df["cost_to_serve_unit"] = serve_unit
    df["late_charge_revenue"] = late_charge
    df["capital_cost"] = capital_cost
    df["bad_debt_provision"] = bad_debt
    df["risk_adj_margin"] = (
        df["margin_total"] + late_charge - capital_cost - bad_debt - df["cost_to_serve"]
    )
    df["risk_adj_margin_rate"] = (
        df["risk_adj_margin"] / df["revenue_total"].replace(0, np.nan)
    )
    # LTV = tenure-aware cumulative risk-adjusted margin, not cumulative revenue
    years = (df["tenure_days"] / 365.25).replace(0, np.nan)
    df["ltv"] = df["risk_adj_margin"]
    df["ltv_per_year"] = df["risk_adj_margin"] / years

    window = ctx.window(st.long_window_months)
    full_window = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)
    for cid, r in df.iterrows():
        ref = span_ref(S.S_SALES, cid, full_window, int(r.lines_total))
        ctx.emit(
            cid, "revenue",
            f"درآمد کل این مشتری {money(r.revenue_total, st)} ریال از "
            f"{num(r.lines_total)} ردیف فروش است.",
            float(r.revenue_total), unit="ریال", window=full_window, source_rows=ref,
            formula="sum(مبلغ کل)", currency_scale=st.currency_scale,
        )
        if pd.notna(r.margin_rate):
            ctx.emit(
                cid, "margin",
                f"حاشیه سود ناخالص {pct(r.margin_rate)} درصد است "
                f"(پوشش بهای تمام‌شده واقعی {pct(r.cost_basis_realized_share, 0)} درصد).",
                float(r.margin_rate), unit="درصد", window=full_window, source_rows=ref,
                formula="(revenue - unit_cost*qty) / revenue",
                cost_basis=st.cost_basis,
                realized_share=round(float(r.cost_basis_realized_share or 0), 4),
            )
        if pd.notna(r.risk_adj_margin_rate):
            ctx.emit(
                cid, "riskadj",
                f"حاشیه سود ریسک‌تعدیل‌شده {pct(r.risk_adj_margin_rate)} درصد است "
                f"(پس از جریمه دیرکرد، هزینه سرمایه و هزینه خدمت‌رسانی).",
                float(r.risk_adj_margin_rate), unit="درصد", kind="comparison",
                window=full_window, source_rows=ref,
                formula=("gross_margin + late_charge - capital_cost - bad_debt "
                         "- cost_to_serve, /revenue"),
                assumption=True, confidence=0.6,
                wacc_monthly=st.wacc_monthly, late_charge_monthly=st.late_charge_monthly,
                cost_to_serve_unit=round(serve_unit, 1),
                open_questions=["Q11 wacc_monthly", "Q12 cost-to-serve rate card"],
            )
        if pd.notna(r.volume_change_pct):
            ctx.emit(
                cid, "volume",
                f"حجم خرید ماهانه در {st.recent_window_months} ماه اخیر "
                f"{pct(r.volume_change_pct)} درصد نسبت به {st.baseline_window_months} ماه "
                f"قبل از آن تغییر کرده است.",
                float(r.volume_change_pct), unit="درصد", kind="comparison",
                window=window, source_rows=ref,
                formula="qty_recent/months / qty_baseline/months - 1",
            )
    return df
