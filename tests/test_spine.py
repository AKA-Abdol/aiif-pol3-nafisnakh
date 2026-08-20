"""Regression tests against the prior-run baselines in PLAN §5.5."""

import numpy as np

from nafisnakh.io import schema as S


def test_spine_row_count_and_revenue(full_spine):
    assert len(full_spine.lines) == 52_987
    assert len(full_spine.customers) == 644
    revenue_m = full_spine.lines[S.D_REVENUE].sum() / 1e6
    assert abs(revenue_m - 4_422.7) < 0.5


def test_cost_basis_coverage_matches_baseline(full_spine):
    cov = full_spine.cost_coverage()
    assert abs(cov["realized"] - 0.322) < 0.002
    assert abs(cov["estimated"] - 0.678) < 0.002


def test_blended_gross_margin_matches_baseline(full_spine):
    lines = full_spine.lines
    gm = lines[S.D_GROSS_MARGIN].sum() / lines[S.D_REVENUE].sum()
    assert abs(gm - 0.1009) < 0.0005
    assert int((lines[S.D_GROSS_MARGIN] < 0).sum()) == 10_405


def test_rule_2_no_fanout_from_collections(full_spine, ds):
    """Integration rule #2 — the one that silently destroys analyses.

    Collections are aggregated to invoice grain, so joining them back onto the
    spine must not create a single extra row.
    """
    assert full_spine.invoice_payments[S.INVOICE_NO].is_unique
    before = len(full_spine.lines)
    joined = full_spine.lines.merge(
        full_spine.invoice_payments.drop(columns=[S.CUSTOMER_ID]),
        on=S.INVOICE_NO,
        how="left",
    )
    assert len(joined) == before
    # and the naive join really would have fanned out — this is why the rule exists
    naive = full_spine.lines.merge(
        ds.collections[[S.INVOICE_NO, S.V_AMOUNT]], on=S.INVOICE_NO, how="left"
    )
    assert len(naive) > before


def test_collections_baselines(full_spine):
    pay = full_spine.invoice_payments
    assert abs(np.nanmedian(pay["_days_late_mean"]) - 23) <= 2
    assert pay["_bounces"].sum() == 93


def test_as_of_gating_shrinks_the_book(ds):
    from datetime import date

    from nafisnakh.core.spine import build_spine

    early = build_spine(ds, as_of=date(2021, 6, 30))
    late = build_spine(ds, as_of=date(2026, 12, 31))
    assert len(early.lines) < len(late.lines)
    assert early.lines[S.F_DATE].max() <= np.datetime64("2021-06-30")


def test_available_at_is_respected(ds):
    from datetime import date

    from nafisnakh.core.spine import visible

    gated = visible(ds.sales, date(2021, 6, 30))
    stamp = gated[S.AVAILABLE_AT]
    assert (stamp.isna() | (stamp <= np.datetime64("2021-06-30"))).all()
