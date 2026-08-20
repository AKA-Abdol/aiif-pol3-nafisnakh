"""Payment behaviour: DSO, late-charge revenue, capital cost, bounces, exposure.

Integration rule #2 governs this whole module — ``فروش`` and ``وصول`` hang off
the invoice at different grains and must never be joined directly. Everything
here starts from :func:`~nafisnakh.core.spine.invoice_collections`, which has
already collapsed collections to one row per invoice.

The economics are asymmetric and that asymmetry is the point (PLAN §3.5, Q10):
Nafis Nakh charges **4% per month on the outstanding balance and collects it**.
Slowness therefore earns compensating revenue; what it really costs is the
firm's own cost of capital over the same days. Whether a slow payer is net
accretive or net dilutive depends entirely on ``wacc_monthly`` — still Q11.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..io import schema as S
from .base import MetricContext, metric_table, money, num, pct, rows_ref


@metric_table("payment")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    as_of = pd.Timestamp(ctx.as_of)

    # invoice totals from the spine (sales side)
    inv = ctx.spine.lines.groupby(
        [S.CUSTOMER_ID, S.INVOICE_NO], as_index=False
    ).agg(invoice_total=(S.D_REVENUE, "sum"), invoice_date=(S.F_DATE, "min"))

    # collections, already at invoice grain — rule #2 satisfied structurally
    pay = ctx.spine.invoice_payments.drop(columns=[S.CUSTOMER_ID], errors="ignore")
    inv = inv.merge(pay, on=S.INVOICE_NO, how="left")
    inv["_collected"] = inv["_collected"].fillna(0.0)
    inv["_bounces"] = inv["_bounces"].fillna(0.0)
    inv["open_amount"] = (inv["invoice_total"] - inv["_collected"]).clip(lower=0.0)

    # days money was tied up: to the collection event, or to as_of while open
    inv["_days_to_collect"] = (inv["_last_event"] - inv["invoice_date"]).dt.days
    inv["_days_open"] = (as_of - inv["invoice_date"]).dt.days
    inv["_days_late"] = inv["_days_late_wavg"].fillna(inv["_days_late_mean"])

    # 4%/month on the balance, actually collected (Q10) — compensating revenue
    inv["_late_charge"] = (
        (inv["_days_late"].fillna(0.0) / 30.0) * st.late_charge_monthly * inv["_collected"]
    )
    wacc = st.wacc_monthly or 0.0
    inv["_capital_cost"] = (
        (inv["_days_to_collect"].fillna(0.0) / 30.0) * wacc * inv["_collected"]
        + (inv["_days_open"].clip(lower=0).fillna(0.0) / 30.0) * wacc * inv["open_amount"]
    )

    g = inv.groupby(S.CUSTOMER_ID)
    df = g.agg(
        invoices=(S.INVOICE_NO, "nunique"),
        billed=("invoice_total", "sum"),
        collected=("_collected", "sum"),
        open_exposure=("open_amount", "sum"),
        bounces=("_bounces", "sum"),
        collection_events=("_events", "sum"),
        late_charge_revenue=("_late_charge", "sum"),
        capital_cost=("_capital_cost", "sum"),
        days_late_max=("_days_late_max", "max"),
    )
    # amount-weighted DSO and days-late — a single big slow invoice should dominate
    def _wavg(gr, value_col, weight_col):
        w = gr[weight_col]
        v = gr[value_col]
        m = v.notna() & (w > 0)
        return float((v[m] * w[m]).sum() / w[m].sum()) if m.any() else np.nan

    df["dso"] = g.apply(lambda gr: _wavg(gr, "_days_to_collect", "_collected"),
                        include_groups=False)
    df["days_late_avg"] = g.apply(lambda gr: _wavg(gr, "_days_late", "_collected"),
                                  include_groups=False)
    df["collection_rate"] = df["collected"] / df["billed"].replace(0, np.nan)
    df["bounce_rate"] = df["bounces"] / df["collection_events"].replace(0, np.nan)

    # DSO drift against the customer's own earlier behaviour, not a global norm
    recent_start = as_of - pd.DateOffset(months=st.baseline_window_months)
    recent = inv.loc[inv["invoice_date"] > recent_start]
    older = inv.loc[inv["invoice_date"] <= recent_start]
    df["dso_recent"] = recent.groupby(S.CUSTOMER_ID).apply(
        lambda gr: _wavg(gr, "_days_to_collect", "_collected"), include_groups=False
    ).reindex(df.index)
    df["dso_baseline"] = older.groupby(S.CUSTOMER_ID).apply(
        lambda gr: _wavg(gr, "_days_to_collect", "_collected"), include_groups=False
    ).reindex(df.index)
    df["dso_slippage"] = df["dso_recent"] - df["dso_baseline"]

    # credit exposure against the declared limit
    limits = pd.to_numeric(
        ctx.customers[S.C_CREDIT_LIMIT], errors="coerce"
    ).reindex(df.index)
    df["credit_limit"] = limits
    df["exposure_ratio"] = df["open_exposure"] / limits.replace(0, np.nan)
    df["payment_terms_days"] = pd.to_numeric(
        ctx.customers[S.C_PAYMENT_TERMS], errors="coerce"
    ).reindex(df.index)

    # bad-debt provision: the customer's own bounce rate when observed, else the
    # book rate from config — an assumption until Q12 is answered
    book_rate = st.bad_debt_rate or 0.0
    df["bad_debt_rate_used"] = df["bounce_rate"].fillna(book_rate).clip(lower=book_rate)
    df["bad_debt_provision"] = df["bad_debt_rate_used"] * df["open_exposure"]
    df["net_finance_effect"] = df["late_charge_revenue"] - df["capital_cost"]

    # ---- credit room: how much of the declared limit is still usable.
    # `exposure_ratio` alone cannot gate an action, because a limit that is
    # absurd relative to the customer's own trade produces a ratio near zero and
    # would read as "plenty of room". `credit_room_state` therefore carries an
    # explicit `unknown` for limits that fail the scale guard (PLAN §5.4).
    months_active = (
        ctx.spine.lines.groupby(S.CUSTOMER_ID)[S.D_MONTH].nunique()
        .reindex(df.index).replace(0, np.nan)
    )
    revenue_total = (
        ctx.spine.lines.groupby(S.CUSTOMER_ID)[S.D_REVENUE].sum().reindex(df.index)
    )
    df["credit_limit_months"] = limits / (revenue_total / months_active).replace(0, np.nan)
    df["credit_room_value"] = (limits - df["open_exposure"]).clip(lower=0.0)
    usable = limits.notna() & (limits > 0) & (
        df["credit_limit_months"].isna()
        | (df["credit_limit_months"] <= st.credit_room_max_months)
    )
    df["credit_room_state"] = np.where(
        ~usable, "unknown",
        np.where(df["exposure_ratio"].fillna(0.0) >= st.credit_exposure_ratio,
                 "exhausted", "open"),
    )

    invoice_ids = inv.groupby(S.CUSTOMER_ID)[S.INVOICE_NO].apply(list)
    bounced_inv = (
        inv.loc[inv["_bounces"] > 0].groupby(S.CUSTOMER_ID)[S.INVOICE_NO].apply(list)
    )
    window = (ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of)

    for cid, r in df.iterrows():
        ref = rows_ref(S.S_COLLECTIONS, invoice_ids.get(cid, [])[-4:])
        if pd.notna(r.dso):
            ctx.emit(
                cid, "dso",
                f"میانگین وزنی دوره وصول {num(r.dso)} روز است "
                f"(شرایط قرارداد {num(r.payment_terms_days)} روز).",
                float(r.dso), unit="روز", window=window, source_rows=ref,
                formula="Σ(days_to_collect × collected) / Σ collected  [rule #2]",
            )
        if pd.notna(r.dso_slippage):
            ctx.emit(
                cid, "dso-slip",
                f"دوره وصول در {st.baseline_window_months} ماه اخیر "
                f"{num(r.dso_slippage)} روز نسبت به رفتار قبلی خود مشتری تغییر کرده است.",
                float(r.dso_slippage), unit="روز", kind="comparison",
                window=window, source_rows=ref,
                formula="dso_recent - dso_baseline (own baseline, not a global norm)",
            )
        if r.open_exposure > 0:
            ctx.emit(
                cid, "exposure",
                f"مانده باز {money(r.open_exposure, st)} ریال است"
                + (f" و {pct(r.exposure_ratio, 0)} درصد سقف اعتبار را اشغال کرده است."
                   if pd.notna(r.exposure_ratio) else "."),
                float(r.open_exposure), unit="ریال", window=window, source_rows=ref,
                formula="Σ max(invoice_total - collected, 0)",
                exposure_ratio=None if pd.isna(r.exposure_ratio) else round(float(r.exposure_ratio), 3),
            )
        if r.credit_room_state == "open" and r.credit_room_value > 0:
            # Stated as a share of the limit, not in rials. 29% of these values
            # are under 50,000 and the project-wide M scale (PLAN §5.4) would
            # print them as "0.0M" — a claim that says "there is room" while
            # showing zero. The share is scale-free and is the quantity that
            # actually decides the action; the absolute stays in provenance.
            free = max(0.0, 1.0 - float(r.exposure_ratio or 0.0))
            ctx.emit(
                cid, "credit-room",
                f"{pct(free, 0)} درصد سقف اعتبار این مشتری هنوز آزاد است.",
                round(free, 4), unit="درصد", kind="comparison",
                window=window, source_rows=ref,
                formula="1 − open_exposure / Credit_Limit",
                room_value=round(float(r.credit_room_value), 0),
                credit_limit=(None if pd.isna(r.credit_limit)
                              else round(float(r.credit_limit), 0)),
                credit_limit_months=(None if pd.isna(r.credit_limit_months)
                                     else round(float(r.credit_limit_months), 1)),
            )
        if r.bounces > 0:
            ctx.emit(
                cid, "bounce",
                f"{num(r.bounces)} فقره چک برگشتی ثبت شده است.",
                float(r.bounces), unit="فقره", kind="event", window=window,
                source_rows=rows_ref(S.S_COLLECTIONS, bounced_inv.get(cid, [])),
                formula="count(چک برگشتی = بله)",
            )
        if abs(float(r.net_finance_effect or 0)) > 0:
            ctx.emit(
                cid, "finance-net",
                f"اثر خالص مالی (جریمه دیرکرد منهای هزینه سرمایه) "
                f"{money(r.net_finance_effect, st)} ریال است.",
                float(r.net_finance_effect), unit="ریال", kind="comparison",
                window=window, source_rows=ref,
                formula=("Σ(days_late/30 × 4% × collected) "
                         "− Σ(days_tied/30 × wacc × amount)"),
                assumption=True, confidence=0.6,
                late_charge_monthly=st.late_charge_monthly, wacc_monthly=st.wacc_monthly,
                open_questions=["Q11 wacc_monthly"],
            )
    return df
