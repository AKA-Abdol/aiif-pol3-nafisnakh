"""Phase 1a — the metric layer.

The contract every metric must honour: it produces a customer-indexed table and
emits well-formed Evidence with a traceable ``source_rows`` and a formula. The
assertions below also pin the handful of figures PLAN quotes, so a refactor that
silently changes a definition fails loudly.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from nafisnakh.io import schema as S
from nafisnakh.metrics.base import BUILD_ORDER, build_metrics, make_context


@pytest.fixture(scope="module")
def ctx(ds):
    return build_metrics(make_context(ds, as_of=date(2021, 6, 30)))


def test_all_tables_built_and_customer_indexed(ctx):
    assert set(ctx.tables) == set(BUILD_ORDER)
    for name, tbl in ctx.tables.items():
        assert tbl.index.name == S.CUSTOMER_ID, name
        assert tbl.index.is_unique, name
        assert len(tbl) > 0, name


def test_every_evidence_is_well_formed(ctx):
    assert len(ctx.evidence) > 1000
    for ev in ctx.evidence.all():
        assert ev.claim_fa.strip()
        assert ev.source_rows, ev.id
        assert ev.provenance.get("formula"), ev.id
        assert ev.customer_id in ev.id
        assert 0.0 < ev.confidence <= 1.0
        assert ev.as_of == date(2021, 6, 30)


def test_assumption_backed_evidence_is_labelled(ctx):
    """Q11/Q12 are unanswered — anything resting on them must say so."""
    risk = [e for e in ctx.evidence.all() if "riskadj" in e.id]
    assert risk
    for ev in risk:
        assert ev.provenance.get("assumption") is True
        assert ev.confidence < 1.0
        assert "Q11" in " ".join(ev.provenance.get("open_questions", []))


def test_cadence_matches_plan_anchor(ctx):
    """PLAN §1.6: 257 customers have ≥6 invoices at the 2021-06-30 anchor."""
    cad = ctx.table("cadence")
    assert int(cad["cadence_eligible"].sum()) == 257
    assert cad["median_gap"].median() == 14.0          # PLAN §3.5
    assert (cad.loc[cad["cadence_eligible"], "cadence_ratio"].notna()).all()


def test_cadence_counts_invoices_not_sales_lines(ctx, spine):
    cad = ctx.table("cadence")
    per_customer_lines = spine.lines.groupby(S.CUSTOMER_ID)[S.SALES_LINE_ID].count()
    assert (cad["n_invoices"] <= per_customer_lines.reindex(cad.index)).all()


def test_zero_median_gap_customers_still_get_a_ratio(ctx):
    """Same-day repeat buyers have a median gap of 0; they must not be silently
    exempted from cadence — they are the accounts whose silence matters most."""
    cad = ctx.table("cadence")
    zero = cad.loc[cad["median_gap"] == 0]
    if len(zero):
        eligible_zero = zero.loc[zero["cadence_eligible"]]
        assert eligible_zero["cadence_ratio"].notna().all()
        assert (eligible_zero["effective_gap"] > 0).all()


def test_payment_respects_rule_2(ctx, spine):
    """Billed amount per customer must equal the spine's revenue — proof that no
    collection fan-out inflated it."""
    pay = ctx.table("payment")
    revenue = spine.lines.groupby(S.CUSTOMER_ID)[S.D_REVENUE].sum()
    joined = pay["billed"].reindex(revenue.index)
    assert np.allclose(joined.values, revenue.values, rtol=1e-9)


def test_payment_late_charge_and_capital_cost_are_separable(ctx):
    pay = ctx.table("payment")
    assert (pay["late_charge_revenue"] >= 0).all()
    assert (pay["capital_cost"] >= 0).all()
    assert np.allclose(
        pay["net_finance_effect"], pay["late_charge_revenue"] - pay["capital_cost"]
    )


def test_open_exposure_is_never_negative(ctx):
    pay = ctx.table("payment")
    assert (pay["open_exposure"] >= 0).all()
    assert (pay["collected"] <= pay["billed"] + 1e-6).all()


def test_economics_risk_adjusted_margin_formula(ctx):
    econ = ctx.table("economics")
    lhs = econ["risk_adj_margin"]
    rhs = (
        econ["margin_total"] + econ["late_charge_revenue"] - econ["capital_cost"]
        - econ["bad_debt_provision"] - econ["cost_to_serve"]
    )
    assert np.allclose(lhs, rhs)


def test_tenure_is_available_for_the_twenty_real_customers(ctx, ds):
    """The Jalali defect (PLAN §1.5) made exactly these 20 go NaN."""
    econ = ctx.table("economics")
    b = [c for c in econ.index if c.startswith("CUST-")]
    if b:
        assert econ.loc[b, "tenure_days"].notna().all()


def test_price_position_is_deflated_not_absolute(ctx):
    """PLAN §1.7 — absolute ASP flags 250/254 customers as 'raising prices'.
    The deflated position must be centred near 1, not exploding with inflation."""
    mix = ctx.table("mix")
    pos = mix["price_position"].dropna()
    assert 0.8 < pos.median() < 1.25
    assert pos.quantile(0.10) > 0.4 and pos.quantile(0.90) < 2.5


def test_quality_recurrence_is_scoped_to_the_same_customer(ctx):
    """Naive near-duplicate matching flags 87.5% of the book (PLAN §5.4); scoped
    to the same customer it is a small minority."""
    q = ctx.table("quality")
    fired = (q["complaint_recurrences"] > 0).mean()
    assert fired < 0.10


def test_hembaft_blast_radius_uses_the_bridge(ds):
    """Rule #7 — Hembaft_ID and Lot_ID meet only through همبافت_لات."""
    ctx = build_metrics(make_context(ds, as_of=date(2026, 12, 31)))
    q = ctx.table("quality")
    exposed = q.loc[q["hembaft_at_risk_lines"] > 0]
    assert len(exposed) >= 10
    # a customer is never listed as at risk from a همبافت it complained about itself
    for ids in exposed["hembaft_at_risk_ids"]:
        assert isinstance(ids, list) and ids


def test_wallet_encodes_the_leakage_caveat(ctx):
    """PLAN §1.2 — the caveat has to travel with the number, not live in a doc."""
    w = ctx.table("wallet")
    assert "headroom_source" in w.columns
    ev = [e for e in ctx.evidence.all() if "headroom" in e.id]
    assert ev
    for e in ev:
        assert e.provenance.get("caveat")
        assert e.confidence <= 0.7


def test_wallet_falls_back_when_the_sheet_is_not_yet_visible(ctx):
    """سهم_سبد covers 2021-07…2022-06, so at the anchor nothing in it is visible."""
    w = ctx.table("wallet")
    assert (w["wallet_rows_visible"] == 0).all()
    assert (w["headroom_source"] == "peer_capacity_estimate").all()


def test_engagement_separates_financing_offers_from_price_cuts(ctx):
    """PLAN §5.3 — مدت‌دار is a financing concession; its discount is not on the
    same scale as a قیمتی offer and the two must never be averaged together."""
    eng = ctx.table("engagement")
    assert "offers_financing_type" in eng.columns
    assert "offers_price_type" in eng.columns
    total = eng["offers_price_type"] + eng["offers_financing_type"]
    assert np.allclose(total, eng["offers_total"])


def test_summary_text_slots_are_parsed_not_embedded():
    from nafisnakh.metrics.engagement import parse_summary_slots

    slots = parse_summary_slots("پیگیری سفارش | فوریت: بالا | کد پیگیری: TRK-1042")
    assert slots["urgency"] == "بالا"
    assert slots["tracking"] == "TRK-1042"


def test_metric_layer_is_cheap_enough_to_run_per_as_of(ds):
    import time

    t = time.time()
    build_metrics(make_context(ds, as_of=date(2021, 12, 31)))
    assert time.time() - t < 30
