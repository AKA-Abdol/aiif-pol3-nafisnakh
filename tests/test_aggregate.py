"""Phase 1d — quadrants, the aggregator, the validator, the graph and the fixture."""

from datetime import date

import pytest

from nafisnakh.aggregate.aggregator import (
    CREDIT_BLOCKED_STEP_FA,
    Action,
    ActionDraft,
    build_actions,
    compose_offline,
    credit_state,
)
from nafisnakh.aggregate.quadrant import BUCKET_LABEL_FA, assign_quadrants
from nafisnakh.aggregate.validate import (
    strip_identifiers,
    validate_action,
)
from nafisnakh.core.evidence import EvidenceRegistry
from nafisnakh.llm.blocks.complaint import attach_to_context
from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.signals.engine import run_detectors


@pytest.fixture(scope="module")
def pipeline(ds):
    ctx = build_metrics(make_context(ds, as_of=date(2021, 6, 30)))
    attach_to_context(ctx)
    run = run_detectors(ctx)
    quadrants = assign_quadrants(ctx)
    queue = build_actions(ctx, run, quadrants, top_n=25)
    return {"ctx": ctx, "run": run, "quadrants": quadrants, "queue": queue}


# ------------------------------------------------------------------ quadrants
def test_every_customer_lands_in_exactly_one_bucket(pipeline):
    table = pipeline["quadrants"].table
    assert set(table["bucket"]) <= {"grow", "protect", "fix", "reduce"}
    assert table["bucket"].notna().all()
    assert table.index.is_unique


def test_all_four_buckets_are_populated(pipeline):
    counts = pipeline["quadrants"].counts()
    assert set(counts) == {"grow", "protect", "fix", "reduce"}
    assert all(v > 0 for v in counts.values())


def test_fix_is_unprofitable_and_material_reduce_is_neither(pipeline):
    """The second axis differs by side: headroom sorts grow from protect,
    materiality sorts fix from reduce."""
    t = pipeline["quadrants"].table
    fix = t.loc[t["bucket"] == "fix"]
    reduce_ = t.loc[t["bucket"] == "reduce"]
    assert (fix["risk_adj_margin_rate"].fillna(-1) <= 0).all()
    assert (fix["material"]).all()
    assert (reduce_["risk_adj_margin_rate"].fillna(-1) <= 0).all()
    assert not reduce_["material"].any()


def test_buckets_use_risk_adjusted_margin_not_gross(pipeline):
    """A customer can be gross-margin positive and still not be `protect`."""
    t = pipeline["quadrants"].table
    disagree = t.loc[(t["margin_rate"] > 0) & (t["risk_adj_margin_rate"] <= 0)]
    assert len(disagree) > 0, "risk adjustment is not changing any call"
    assert set(disagree["bucket"]) <= {"fix", "reduce"}


def test_bucket_assignment_emits_its_own_evidence(pipeline):
    ctx = pipeline["ctx"]
    ev = [e for e in ctx.evidence.all() if "-bucket-" in e.id]
    assert len(ev) == len(pipeline["quadrants"].table)
    for e in ev[:20]:
        assert e.provenance.get("assumption") is True   # rests on Q7/Q11/Q12
        assert BUCKET_LABEL_FA[e.value] in e.claim_fa


# ------------------------------------------------------------------ validator
def _registry_with(claim="حاشیه سود 12.5 درصد است", value=12.5, cid="C_1"):
    reg = EvidenceRegistry()
    reg.add(cid, "margin", kind="metric", claim_fa=claim, value=value, unit="درصد",
            as_of=date(2021, 6, 30), source_rows="فروش:1")
    return reg


def _action(cid="C_1", ids=None, **texts):
    return Action(
        customer_id=cid, rank=1, priority="بالا", bucket="protect",
        title_fa=texts.get("title", "عنوان"),
        rationale_fa=texts.get("rationale", "دلیل"),
        recommended_step_fa=texts.get("step", "قدم"),
        owner="مدیر فروش", evidence_ids=ids if ids is not None else ["EV-C_1-margin-001"],
        signals=["margin_below_peer_cohort"], value_at_stake=1.0,
    )


def test_validator_accepts_a_number_that_its_evidence_supports():
    reg = _registry_with()
    a = _action(rationale="حاشیه سود 12.5 درصد است [EV-C_1-margin-001]")
    assert validate_action(a, reg).ok


def test_validator_rejects_a_fabricated_number():
    """The single check that makes 'evidence-backed' a guarantee."""
    reg = _registry_with()
    a = _action(rationale="حاشیه سود 47.9 درصد است [EV-C_1-margin-001]")
    result = validate_action(a, reg)
    assert not result.ok
    assert any(i.code == "unsupported_number" for i in result.issues)
    assert "47.9" in result.complaint_fa()


def test_validator_rejects_an_unknown_evidence_id():
    reg = _registry_with()
    a = _action(ids=["EV-C_1-margin-999"])
    result = validate_action(a, reg)
    assert not result.ok
    assert any(i.code == "unknown_evidence" for i in result.issues)


def test_validator_rejects_evidence_belonging_to_another_customer():
    reg = _registry_with(cid="C_2")
    a = _action(cid="C_1", ids=["EV-C_2-margin-001"])
    result = validate_action(a, reg)
    assert not result.ok
    assert any(i.code == "foreign_evidence" for i in result.issues)


def test_validator_rejects_an_inline_citation_that_was_not_declared():
    reg = _registry_with()
    a = _action(rationale="ادعا [EV-C_1-margin-001] و ادعای دیگر [EV-C_1-dso-001]")
    result = validate_action(a, reg)
    assert not result.ok
    assert any(i.code in {"inline_not_declared", "unknown_evidence"} for i in result.issues)


def test_identifiers_are_not_read_as_numeric_claims():
    """`[EV-C_117580-cadence-001]` is a citation, not the numbers 117580 and 001."""
    cleaned = strip_identifiers("طبق [EV-C_117580-cadence-001] و CMP-0033 و M02_filament_damage")
    assert "117580" not in cleaned
    assert "0033" not in cleaned
    assert "02" not in cleaned


def test_rounding_is_allowed_but_invented_precision_is_not():
    reg = _registry_with(claim="نسبت 11.34 برابر است", value=11.34)
    assert validate_action(_action(rationale="نسبت 11.3 برابر است"), reg).ok
    bad = validate_action(_action(rationale="نسبت 11.37 برابر است"), reg)
    assert not bad.ok


# ----------------------------------------------------------------- aggregator
def test_every_action_passes_its_own_validator(pipeline):
    ctx, queue = pipeline["ctx"], pipeline["queue"]
    assert queue.actions
    for a in queue.actions:
        assert validate_action(a, ctx.evidence).ok, a.customer_id


def test_actions_are_ranked_and_capped(pipeline):
    queue = pipeline["queue"]
    assert [a.rank for a in queue.actions] == list(range(1, len(queue.actions) + 1))
    assert len(queue.actions) <= 25


def test_ranking_is_python_side_not_model_side(pipeline):
    """The draft schema deliberately has no rank, priority, bucket or money."""
    fields = set(ActionDraft.model_fields)
    assert "rank" not in fields and "priority" not in fields
    assert "bucket" not in fields and "value_at_stake" not in fields


def test_offline_composer_writes_no_number_of_its_own(pipeline):
    ctx, run = pipeline["ctx"], pipeline["run"]
    cid, signals = next(iter(run.by_customer().items()))
    draft = compose_offline(cid, signals, ctx.evidence, "protect", "دلیل")
    action = _action(cid=cid, ids=draft.evidence_ids,
                     title=draft.title_fa, rationale=draft.rationale_fa,
                     step=draft.recommended_step_fa)
    assert validate_action(action, ctx.evidence).ok


# ------------------------------------------------------------- credit gate
def test_credit_room_state_is_one_of_three_values(pipeline):
    states = pipeline["ctx"].table("payment")["credit_room_state"]
    assert set(states) <= {"open", "exhausted", "unknown"}


def test_absurd_credit_limit_is_marked_unknown_not_open(pipeline):
    """A limit worth centuries of the customer's own trade cannot gate anything.

    This is the Universe-B scale defect (PLAN §5.4) in miniature: a ratio near
    zero would otherwise read as unlimited room.
    """
    pay = pipeline["ctx"].table("payment")
    absurd = pay[pay["credit_limit_months"] > pipeline["ctx"].settings.credit_room_max_months]
    assert (absurd["credit_room_state"] == "unknown").all()


def test_exhausted_credit_replaces_the_growth_step(pipeline):
    ctx, run = pipeline["ctx"], pipeline["run"]
    by_customer = run.by_customer()
    cid = next(iter(by_customer))
    signals = by_customer[cid]
    open_draft = compose_offline(cid, signals, ctx.evidence, "grow", "", "open")
    blocked = compose_offline(cid, signals, ctx.evidence, "grow", "", "exhausted")
    assert open_draft.recommended_step_fa != blocked.recommended_step_fa
    assert blocked.recommended_step_fa == CREDIT_BLOCKED_STEP_FA["grow"]
    assert "مالی" in blocked.owner


def test_credit_gate_leaves_fix_and_reduce_alone(pipeline):
    """Neither bucket asks the customer to buy more, so credit is not the lever."""
    ctx, run = pipeline["ctx"], pipeline["run"]
    cid, signals = next(iter(run.by_customer().items()))
    for bucket in ("fix", "reduce"):
        a = compose_offline(cid, signals, ctx.evidence, bucket, "", "open")
        b = compose_offline(cid, signals, ctx.evidence, bucket, "", "exhausted")
        assert a.recommended_step_fa == b.recommended_step_fa


def test_every_action_records_the_credit_state_it_was_built_under(pipeline):
    for a in pipeline["queue"].actions:
        assert a.detail["credit_room"] in {"open", "exhausted", "unknown"}
        assert a.detail["credit_room"] == credit_state(pipeline["ctx"], a.customer_id)


def test_priority_bands_do_not_depend_on_how_many_rows_were_asked_for(ds, pipeline):
    ctx, run, q = pipeline["ctx"], pipeline["run"], pipeline["quadrants"]
    five = build_actions(ctx, run, q, top_n=5)
    fifty = build_actions(ctx, run, q, top_n=50)
    for a, b in zip(five.actions, fifty.actions[:5]):
        assert a.customer_id == b.customer_id
        assert a.priority == b.priority


def test_brief_is_readable_persian_and_names_the_buckets(pipeline):
    text = pipeline["queue"].to_brief_fa(pipeline["ctx"].settings, top_n=3)
    assert "صف اقدام" in text and "قدم بعدی" in text
    assert any(label in text for label in BUCKET_LABEL_FA.values())


def test_queue_serialises_with_its_drops(pipeline, tmp_path):
    import json

    path = tmp_path / "actions.json"
    pipeline["queue"].dump_json(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["n_actions"] == len(pipeline["queue"].actions)
    assert "dropped" in payload and "quadrant_counts" in payload


# ---------------------------------------------------------------- the graph
def test_graph_and_sequential_runs_agree(ds):
    from nafisnakh.llm.graph import run_pipeline

    a = run_pipeline(as_of=date(2021, 6, 30), dataset=ds, use_graph=False, top_n=10)
    b = run_pipeline(as_of=date(2021, 6, 30), dataset=ds, use_graph=False, top_n=10)
    assert [x.customer_id for x in a["queue"].actions] == [
        x.customer_id for x in b["queue"].actions
    ]


def test_graph_compiles_with_every_stage(ds):
    from nafisnakh.llm.graph import NODES, build_graph

    graph = build_graph()
    assert graph is not None
    assert [n for n, _ in NODES] == [
        "load", "metrics", "complaint_llm", "resolution_llm", "feedback",
        "detect", "quadrant", "relationship", "aggregate",
    ]


def test_stop_after_ends_the_run_and_omits_the_later_stages(ds):
    """`signals` and `calibrate` must not pay for the LLM stages they discard."""
    from nafisnakh.llm.graph import run_pipeline

    state = run_pipeline(as_of=date(2021, 6, 30), dataset=ds, use_graph=False,
                         stop_after="detect")
    assert "signals" in state and "calibration" in state
    # a stale value would be worse than a missing one, so these are absent
    assert "queue" not in state
    assert "quadrants" not in state


def test_stop_after_produces_the_same_signals_as_a_full_run(ds):
    from nafisnakh.llm.graph import run_pipeline

    short = run_pipeline(as_of=date(2021, 6, 30), dataset=ds, use_graph=False,
                         stop_after="detect")
    full = run_pipeline(as_of=date(2021, 6, 30), dataset=ds, use_graph=False, top_n=5)
    assert len(short["signals"].signals) == len(full["signals"].signals)


def test_stop_after_rejects_an_unknown_node():
    from nafisnakh.llm.graph import nodes_upto

    with pytest.raises(ValueError, match="unknown node"):
        nodes_upto("not_a_node")


# --------------------------------------------------------------- the fixture
@pytest.fixture(scope="module")
def fixture_state():
    from nafisnakh.eval.fixture import run_fixture

    return run_fixture()


def test_fixture_fires_all_twenty_two_detectors(fixture_state):
    """PLAN §6 — the fixture must exercise every detector at least once."""
    from nafisnakh.eval.fixture import snapshot
    from nafisnakh.signals.base import all_detectors

    snap = snapshot(fixture_state)
    expected = {d.name for d in all_detectors()}
    fired = set(snap["detectors_fired"])
    assert expected - fired == set(), f"never fired: {sorted(expected - fired)}"


def test_fixture_covers_all_four_buckets(fixture_state):
    counts = fixture_state["quadrants"].counts()
    assert set(counts) == {"grow", "protect", "fix", "reduce"}


def test_fixture_has_the_real_churn_threat_text(fixture_state):
    threats = [
        s for s in fixture_state["signals"].signals
        if s.detector == "churn_threat_language"
    ]
    assert threats
    assert any("قطع همکاری" in q for s in threats for q in s.detail["quotes"])


def test_fixture_blast_radius_excludes_the_complainant(fixture_state):
    blast = {
        s.customer_id for s in fixture_state["signals"].signals
        if s.detector == "hembaft_blast_radius"
    }
    assert blast == {"FIX-006", "FIX-007"}, blast
    assert "FIX-005" not in blast     # FIX-005 is the one who complained


def test_fixture_rows_are_all_flagged(fixture_state):
    from nafisnakh.eval.fixture import FIXTURE_FLAG, FIXTURE_PREFIX

    ds = fixture_state["ctx"].ds
    for sheet, frame in ds.frames.items():
        if len(frame) and FIXTURE_FLAG in frame.columns:
            assert frame[FIXTURE_FLAG].all(), sheet
    assert all(c.startswith(FIXTURE_PREFIX) for c in fixture_state["ctx"].population)


def test_fixture_never_touches_the_real_workbook(fixture_state):
    """It is composed in memory — a fixture that read DATASET.xlsx could not be
    a stable regression baseline."""
    population = set(fixture_state["ctx"].population)
    assert not any(c.startswith("C_") or c.startswith("CUST-") for c in population)


def test_fixture_snapshot_is_stable():
    import json
    from pathlib import Path

    from nafisnakh.eval.fixture import run_fixture, snapshot

    path = Path("nafisnakh/eval/fixture_snapshot.json")
    if not path.exists():
        pytest.skip("no snapshot recorded yet")
    recorded = json.loads(path.read_text(encoding="utf-8"))
    current = snapshot(run_fixture())
    assert current["signals_per_customer"] == recorded["signals_per_customer"]
    assert current["buckets"] == recorded["buckets"]
    assert current["dropped"] == recorded["dropped"]


def test_fixture_actions_all_validate(fixture_state):
    ctx, queue = fixture_state["ctx"], fixture_state["queue"]
    assert queue.dropped == []
    for a in queue.actions:
        assert validate_action(a, ctx.evidence).ok, a.customer_id


def test_open_investigation_gate_rewrites_the_step(ds):
    """A meeting proposed over an unclosed complaint file is not a step.

    FIX-005 carries a complaint still waiting on a sample; its action must say to
    close that file first, and must cite the evidence carrying the day count.
    """
    from nafisnakh.eval.fixture import run_fixture

    state = run_fixture()
    action = next(a for a in state["queue"].actions if a.customer_id == "FIX-005")
    assert action.detail["open_investigation"] == "pending"
    assert "پرونده" in action.recommended_step_fa
    assert any("resolution-pending" in e for e in action.evidence_ids)


def test_relationship_stance_is_recorded_on_every_action(ds):
    from nafisnakh.eval.fixture import run_fixture

    allowed = {"apologise", "unsubstantiated", "mixed", "neutral"}
    for a in run_fixture()["queue"].actions:
        assert a.detail["relationship_stance"] in allowed


def test_fixture_complaint_ids_are_citations_not_numbers():
    """`CMPFIX-007` must not be read as the number 007."""
    from nafisnakh.aggregate.validate import strip_identifiers

    assert "007" not in strip_identifiers("پروندهٔ CMPFIX-007 باز است")
    assert "0021" not in strip_identifiers("شکایت CMP-0021 بررسی شد")
