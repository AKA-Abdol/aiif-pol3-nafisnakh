"""Phase 1c — taxonomy, the complaint block, and the golden set.

No live model call is made anywhere in this file (Q14: no key yet). What is
tested is everything around the call: the deterministic taxonomy, the offline
guard, the cache, the evidence the block emits, and the scorer's honesty about
what a rules run does and does not prove.
"""

from datetime import date

import pandas as pd
import pytest
from pydantic import BaseModel

from nafisnakh.eval.golden import (
    TARGET_CHURN_RECALL,
    TARGET_MECHANISM_ACCURACY,
    load_golden,
    run_eval,
    score,
)
from nafisnakh.io import schema as S
from nafisnakh.llm.blocks.complaint import (
    ComplaintExtraction,
    extract_complaints,
    rule_extraction,
)
from nafisnakh.llm.client import LLMClient, LLMUnavailable
from nafisnakh.llm.taxonomy import (
    MECHANISMS,
    TITLE_TO_MECHANISM,
    UNKNOWN,
    coverage_report,
    mechanism_for_title,
)

CENTREPIECE = (
    "نخ در بعضي جاها سيمي ميباشد و همچنين پرز  شديد نيز در بعضي بسته ها وجود دارد."
    "اين مشکل تکراري ميباشد و قبلا هم وجود داشته و مشتري اعلام نموده که درصورت تکرار "
    "قطع همکاري ميکند.مشتري عکس ارسال نموده است"
)


# ------------------------------------------------------------------ taxonomy
def test_all_forty_five_titles_map_to_ten_mechanisms(ds):
    assert len(MECHANISMS) == 10
    assert len(TITLE_TO_MECHANISM) == 45
    titles = sorted(ds.complaints[S.K_TITLE].dropna().unique())
    assert len(titles) == 45
    report = coverage_report(titles)
    assert report["unmapped"] == []
    assert report["n_mapped"] == 45


def test_title_lookup_is_orthography_insensitive():
    """`بد پيچي` (Arabic ي) and `بدپیچی بسته` are the same mechanism written
    differently — which is exactly why clustering the 45 gets 36% purity."""
    assert mechanism_for_title("بد پيچي") == mechanism_for_title("بدپیچی بسته")
    assert mechanism_for_title("فیلامنت و پرز") == mechanism_for_title("پارگی فیلامنت")
    assert mechanism_for_title("عنوانی که وجود ندارد") == UNKNOWN
    assert mechanism_for_title(None) == UNKNOWN


def test_every_mechanism_is_reachable_from_some_title():
    reachable = set(TITLE_TO_MECHANISM.values())
    assert reachable == set(MECHANISMS)


# -------------------------------------------------------------- offline guard
def test_client_refuses_to_invent_a_response_without_a_key(settings):
    class Tiny(BaseModel):
        a: int

    client = LLMClient(settings)
    if client.available:
        pytest.skip("a real key is configured; the offline guard cannot be tested")
    with pytest.raises(LLMUnavailable):
        client.structured("s", "u", Tiny)
    result = client.structured("s", "u", Tiny, fallback=lambda: Tiny(a=1))
    assert result.source == "rules"
    assert result.confidence_multiplier < 1.0


def test_cache_round_trip(settings, tmp_path):
    class Tiny(BaseModel):
        a: int

    client = LLMClient(settings.model_copy(update={"cache_dir": tmp_path}))
    h = client.prompt_hash("sys", "user", "Tiny")
    assert client.read_cache(h) is None
    client.write_cache(h, {"a": 7})
    result = client.structured("sys", "user", Tiny)
    assert result.source == "cached" and result.value.a == 7


def test_prompt_hash_is_stable_and_content_sensitive(settings):
    c = LLMClient(settings)
    assert c.prompt_hash("a", "b", "S") == c.prompt_hash("a", "b", "S")
    assert c.prompt_hash("a", "b", "S") != c.prompt_hash("a", "b!", "S")


# ------------------------------------------------------- the centrepiece text
def test_the_demo_centrepiece_yields_its_three_hidden_facts():
    """PLAN §1.3 — a churn threat, a repeat claim and photographic evidence, all
    in one sentence, none of them in any structured column."""
    e = rule_extraction("فیلامنت و پرز", CENTREPIECE, "کم")
    assert e.churn_threat is True
    assert e.churn_threat_quote_fa and "قطع همکاری" in e.churn_threat_quote_fa
    assert e.repeat_claim is True
    assert e.evidence_supplied is True
    assert e.escalation_level == "تشدید"
    assert e.mechanism == "M02_filament_damage"


def test_extraction_schema_constrains_its_fields():
    with pytest.raises(Exception):
        ComplaintExtraction(
            mechanism="M01_package_formation", mechanism_confidence=1.5,
            churn_threat=False, repeat_claim=False, financial_demand=False,
            escalation_level="عادی", attributed_fault="تولید",
            evidence_supplied=False, summary_fa="x",
        )
    with pytest.raises(Exception):
        ComplaintExtraction(
            mechanism="M01_package_formation", mechanism_confidence=0.5,
            churn_threat=False, repeat_claim=False, financial_demand=False,
            escalation_level="خیلی زیاد",     # not in the enum
            attributed_fault="تولید", evidence_supplied=False, summary_fa="x",
        )


# ---------------------------------------------------------------- the block
def test_block_runs_over_the_forty_and_tags_its_source(ds):
    comp = ds.complaints
    b = comp.loc[comp["_universe"] == "B"]
    out = extract_complaints(b, settings=ds.settings)
    assert len(out) == 40
    assert set(out["extraction_source"]) <= {"rules", "cached", "live"}
    assert out["mechanism"].notna().all()


def test_block_emits_evidence_that_names_its_source(ds):
    from nafisnakh.llm.blocks.complaint import attach_to_context
    from nafisnakh.metrics.base import build_metrics, make_context

    ctx = build_metrics(make_context(ds, as_of=date(2026, 12, 31)))
    before = len(ctx.evidence)
    attach_to_context(ctx, universe="B")
    assert "llm_complaints" in ctx.tables
    assert len(ctx.evidence) > before
    llm_ev = [e for e in ctx.evidence.all() if "llm-" in e.id]
    assert llm_ev
    for e in llm_ev:
        assert e.provenance["extraction_source"] in {"rules", "cached", "live"}
        if e.provenance["extraction_source"] == "rules":
            assert e.confidence <= 0.6


def test_churn_detector_fires_once_the_block_has_run(ds):
    """Detector #16 exists only because an LLM reads the prose."""
    from nafisnakh.llm.blocks.complaint import attach_to_context
    from nafisnakh.metrics.base import build_metrics, make_context
    from nafisnakh.signals.engine import run_detectors

    ctx = build_metrics(make_context(ds, as_of=date(2026, 12, 31)))
    attach_to_context(ctx, universe="B")
    run = run_detectors(ctx)
    threats = [s for s in run.signals if s.detector == "churn_threat_language"]
    assert len(threats) == 1
    s = threats[0]
    assert s.severity >= 90          # repeat claim + threat
    assert s.detail["repeat_claim"] is True
    assert s.suggested_bucket == "protect"
    assert s.evidence_ids


# --------------------------------------------------------------- golden set
def test_golden_set_covers_all_forty_with_complete_labels():
    g = load_golden()
    assert len(g.rows) == 40
    required = {
        "mechanism", "churn_threat", "repeat_claim", "financial_demand",
        "escalation_level", "attributed_fault", "evidence_supplied",
        "hembaft_mentioned", "summary_fa",
    }
    for row in g.rows:
        assert required <= set(row["labels"]), row["complaint_id"]
        assert "reviewed" in row and "ambiguous" in row
        assert row["labels"]["mechanism"] in MECHANISMS


def test_golden_set_is_marked_unreviewed_until_the_user_signs_off():
    """Q8 — I propose the labels; the user reviews and corrects them."""
    g = load_golden()
    assert g.reviewed_count == 0 or g.reviewed_count == 40
    assert g.ambiguous_count > 0, "no row flagged ambiguous looks like overconfidence"


def test_scorer_reports_the_title_baseline_alongside_accuracy():
    report = run_eval()
    assert report.n_rows == 40
    assert report.mechanism["accuracy"] >= TARGET_MECHANISM_ACCURACY
    assert "title_baseline_accuracy" in report.mechanism
    assert "lift_over_title_baseline" in report.mechanism


def test_scorer_refuses_to_certify_a_rules_run():
    """A rules run scores the title lookup, not a model. Calling that a pass
    would certify something that was never tested."""
    report = run_eval()
    if not report.is_model_run:
        assert report.passes_targets is False
        assert "قابل صدور نیست" in report.to_text()


def test_scorer_says_when_a_field_has_no_positives():
    report = run_eval()
    fin = report.booleans["financial_demand"]
    assert fin["positives_in_gold"] == 0
    assert fin["recall"] is None
    assert fin["note"]


def test_churn_recall_target_is_met_on_the_golden_set():
    report = run_eval()
    recall = report.booleans["churn_threat"]["recall"]
    assert recall is not None and recall >= TARGET_CHURN_RECALL
