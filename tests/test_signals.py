"""Phase 1b — the 22 detectors and the ranking engine."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.signals.base import Signal, all_detectors, scale
from nafisnakh.signals.engine import (
    BUCKET_WEIGHT,
    calibrate,
    dedupe,
    priority_score,
    run_detectors,
)


@pytest.fixture(scope="module")
def ctx(ds):
    return build_metrics(make_context(ds, as_of=date(2021, 6, 30)))


@pytest.fixture(scope="module")
def run(ctx):
    return run_detectors(ctx)


def test_every_registered_detector_is_accounted_for():
    dets = all_detectors()
    assert len(dets) == 27
    assert len({d.name for d in dets}) == 27
    assert {d.category for d in dets} <= {"risk", "opportunity", "efficiency"}


def test_every_detector_declares_the_tables_it_consumes(ctx):
    for det in all_detectors():
        assert det.requires, det.name
        for table in det.requires:
            assert table in ctx.tables or table.startswith("llm_"), (det.name, table)


def test_no_detector_raised(run):
    assert run.errors == {}


def test_every_signal_cites_evidence_that_exists_and_belongs_to_it(run, ctx):
    assert run.signals
    for s in run.signals:
        assert s.evidence_ids, s.id
        for eid in s.evidence_ids:
            ev = ctx.evidence.get(eid)
            assert ev is not None, f"{s.id} cites unknown {eid}"
            assert ev.customer_id == s.customer_id, f"{s.id} cites another customer"


def test_signals_are_well_formed(run):
    for s in run.signals:
        assert 0 <= s.severity <= 100
        assert s.value_at_stake >= 0
        assert s.headline_fa.strip()
        assert s.direction in {"deteriorating", "improving", "static"}
        assert s.suggested_bucket in {None, "grow", "protect", "fix", "reduce"}
        assert s.first_detected_at == date(2021, 6, 30)


def test_one_signal_per_customer_and_detector(run):
    keys = [(s.customer_id, s.detector) for s in run.signals]
    assert len(keys) == len(set(keys))


def test_dedupe_keeps_the_most_severe():
    def mk(sev):
        return Signal(
            id="SIG-C_1-x", customer_id="C_1", detector="x", category="risk",
            severity=sev, direction="static", headline_fa="h", evidence_ids=[],
            first_detected_at=date(2021, 6, 30), value_at_stake=0.0,
        )

    assert dedupe([mk(10), mk(90), mk(50)])[0].severity == 90


def test_ranking_is_deterministic_and_python_side(run, ctx):
    scores = [priority_score(s, ctx.settings) for s in run.signals]
    assert scores == sorted(scores, reverse=True)
    again = [priority_score(s, ctx.settings) for s in run.signals]
    assert scores == again


def test_ranking_compresses_money_so_severity_keeps_leverage(ctx):
    """PLAN §3.7 — ``log1p`` of the money, not the money itself.

    Doubling the amount at stake must move the score far less than doubling the
    severity, otherwise the queue degenerates into a revenue ranking and the
    sales manager stops seeing urgent problems on mid-sized accounts.
    """

    def mk(stake, sev=50.0):
        return Signal(
            id="SIG-x", customer_id="C_1", detector="d", category="risk",
            severity=sev, direction="static", headline_fa="h", evidence_ids=[],
            first_detected_at=date(2021, 6, 30), value_at_stake=stake,
        )

    base = priority_score(mk(1e8), ctx.settings)
    double_money = priority_score(mk(2e8), ctx.settings)
    double_severity = priority_score(mk(1e8, sev=100.0), ctx.settings)

    assert double_money < base * 1.20          # sub-linear in money
    assert double_severity == pytest.approx(base * 2.0)   # linear in severity


def test_bucket_weights_favour_protect_and_fix_over_reduce():
    assert BUCKET_WEIGHT["protect"] > BUCKET_WEIGHT["grow"] > BUCKET_WEIGHT["reduce"]
    assert BUCKET_WEIGHT["fix"] > BUCKET_WEIGHT["reduce"]


def test_scale_is_clamped():
    assert scale(-100, 0, 10) == 10.0
    assert scale(1000, 0, 10) == 100.0
    assert 10 <= scale(5, 0, 10) <= 100


def test_tiny_eligible_population_is_not_judged(run, ctx):
    """A rate over a handful of customers is not a rate.

    Without this, every subset run produced a wall of "1 fired of 1 eligible =
    100%, too_broad" — false alarms that train the reader to ignore the table.
    """
    from dataclasses import replace

    small = replace(
        run, eligible_counts={name: 3 for name in run.fire_rates},
        fire_rates={name: 1.0 for name in run.fire_rates},
    )
    report = calibrate(small, ctx)
    assert (report.rows["status"] == "insufficient").all()
    assert report.failures.empty
    assert len(report.insufficient) == len(report.rows)


def test_insufficient_is_reported_but_never_a_failure(run, ctx):
    report = calibrate(run, ctx)
    assert "insufficient" not in set(report.failures["status"])


def test_calibration_passes_for_every_detector(run, ctx):
    """PLAN §4, Phase 1b — no detector may fire on >60% or <2% of the customers
    it could possibly fire on. Detectors that are rare by design are exempt
    from the lower bound only."""
    report = calibrate(run, ctx)
    assert len(report.rows) == 27
    assert report.failures.empty, f"\n{report.failures.to_string(index=False)}"


def test_cadence_breach_is_personalised_not_a_global_recency_cutoff(ctx, run):
    cad = ctx.table("cadence")
    fired = {s.customer_id for s in run.signals if s.detector == "cadence_breach"}
    quiet = cad.loc[cad["days_since_last"] > 120]
    # a slow-rhythm customer can be 120 days quiet and correctly NOT fire
    not_fired = [c for c in quiet.index if c not in fired and quiet.loc[c, "cadence_eligible"]]
    assert not_fired, "cadence has degenerated into a global recency rule"


def test_hembaft_blast_radius_fires_where_the_data_supports_it(ds):
    """At the demo anchor no complaint has yet been filed against a همبافت that
    reached another customer; across the full horizon 18 customers are exposed."""
    ctx = build_metrics(make_context(ds, as_of=date(2026, 12, 31)))
    run = run_detectors(ctx)
    blast = [s for s in run.signals if s.detector == "hembaft_blast_radius"]
    assert len(blast) >= 10
    for s in blast:
        assert s.detail["preemptive"] is True
        assert s.detail["hembaft_ids"]
        assert s.suggested_bucket == "protect"


def test_churn_threat_returns_nothing_without_the_llm_block(run):
    """Detector #16 must not fall back to a keyword heuristic — a missing LLM
    block has to be visible as an absent signal, not a silently degraded one."""
    assert not [s for s in run.signals if s.detector == "churn_threat_language"]


def test_negative_margin_detector_flags_its_open_questions(run):
    hits = [s for s in run.signals if s.detector == "negative_risk_adj_margin"]
    assert hits
    for s in hits:
        assert "Q11" in s.detail["depends_on_open_questions"]
        assert s.suggested_bucket == "fix"


def test_discount_detector_makes_no_causal_claim(run):
    """PLAN §1.2 — the offers sheet has no association with outcome. The signal
    may report the pairing but must never assert that discounting failed."""
    hits = [s for s in run.signals if s.detector == "discount_without_return"]
    assert hits
    for s in hits:
        assert "association only" in s.detail["caveat"]


def test_signal_run_serialises(run, tmp_path):
    import json

    path = tmp_path / "signals.json"
    run.dump_json(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["as_of"] == "2021-06-30"
    assert len(payload["signals"]) == len(run.signals)
    assert payload["fire_rates"]


def test_llm_block_only_runs_for_triggered_customers(run, ctx):
    """PLAN §3.8 — the cost control. The metric layer covers everyone; the LLM
    must only see the customers who actually triggered something."""
    triggered = set(run.triggered_customers())
    assert triggered
    assert triggered <= set(ctx.population)


# ---------------------------------------------- resolution block (PLAN §2)
def test_templates_are_matched_after_normalisation():
    """The patterns and the text must go through the same normaliser.

    `normalize_fa` folds hamza (تأیید → تایید) and strips punctuation, so a
    pattern written in raw orthography matches nothing. This exact bug made the
    "claim not substantiated" frame miss all 62 rows it was written for.
    """
    from nafisnakh.llm.blocks.resolution import template_extraction

    raw = "نتایج در محدوده الزام محصول بود و مغایرتی که ادعای مشتری را تأیید کند مشاهده نشد."
    e = template_extraction(raw)
    assert e is not None
    assert e.fault_verdict == "مشتری"
    assert e.initial_claim_overturned is True


def test_awaiting_sample_is_reported_as_pending():
    from nafisnakh.llm.blocks.resolution import template_extraction

    e = template_extraction("تا زمان دریافت نمونه و انجام آزمون تکمیلی، موضوع باز است.")
    assert e is not None and e.investigation_state == "منتظر نمونه یا آزمون"
    assert e.resolution_confirmed is False


def test_unrecognised_prose_escalates_to_the_model():
    """Returning None is what sends Universe-B prose to the LLM."""
    from nafisnakh.llm.blocks.resolution import template_extraction

    assert template_extraction("متنی که هیچ قالب شناخته‌شده‌ای ندارد") is None
    assert template_extraction("") is None
    assert template_extraction(None) is None


def test_resolution_is_gated_on_its_own_availability_stamp(ctx):
    """Rule #4: the answer is knowable from Resolution_Available_At, not before."""
    import pandas as pd
    from nafisnakh.io import schema as S
    from nafisnakh.llm.blocks.resolution import knowable_resolutions

    rows = knowable_resolutions(ctx)
    stamp = pd.to_datetime(rows[S.K_RESOLUTION_AVAILABLE_AT], errors="coerce")
    assert stamp.notna().all()
    assert (stamp <= pd.Timestamp(ctx.as_of)).all()
