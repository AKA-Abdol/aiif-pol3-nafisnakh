"""Seven agents, a deterministic router, one agenda (step 5).

The router is the part worth testing hardest: it is pure Python, it decides what
a meeting costs, and it is the thing a sales manager will be asked to trust when
they ask "why did it look at that?". The agents themselves are tested through
their offline path, so the suite never needs a key to prove the wiring.
"""

from datetime import date

import pytest

from nafisnakh.agents import all_agents, get_agent, hold_meeting, route
from nafisnakh.agents.base import AgentAnswer, Trigger, run_agent
from nafisnakh.aggregate.quadrant import assign_quadrants
from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.signals.engine import run_detectors
from nafisnakh.tools import get_tool

AS_OF = date(2021, 6, 30)
BUSY = "C_126481"          # exhausted credit, open investigation, all four loops
EXPECTED = {
    "open_loops", "risk", "opportunity", "financial", "relationship", "pricing",
    "supply_feasibility",
}


@pytest.fixture(scope="module")
def ctx(ds):
    """Metrics plus the resolution block.

    The router reads the investigation state and the relationship stance, both of
    which come out of `llm_resolutions`. Testing without it would exercise a
    degraded router rather than the real one — and the block is template-first,
    so it costs nothing offline.
    """
    from nafisnakh.llm.blocks.resolution import attach_to_context

    ctx = build_metrics(make_context(ds, as_of=AS_OF))
    attach_to_context(ctx, allow_rules=True)
    return ctx


@pytest.fixture(scope="module")
def signals(ctx):
    run = run_detectors(ctx)
    assign_quadrants(ctx)
    return run.signals


# ------------------------------------------------------------------- roster
def test_all_seven_agents_are_registered():
    assert {a.name for a in all_agents()} == EXPECTED


def test_every_agent_declares_real_tools_and_persian_prompts():
    for spec in all_agents():
        assert spec.tools, spec.name
        for t in spec.tools:
            get_tool(t)                       # raises if the tool does not exist
        assert spec.question_fa.strip() and spec.role_fa.strip()
        # each agent carries the claim it must not make — the dataset's limits
        # enforced at the prompt, not only in review
        assert spec.forbidden_fa.strip(), spec.name


def test_unknown_agent_is_refused():
    with pytest.raises(KeyError):
        get_agent("marketing")


# ------------------------------------------------------------------- router
def test_routing_is_deterministic(ctx, signals):
    a = route(ctx, BUSY, signals).to_dict()
    b = route(ctx, BUSY, signals).to_dict()
    assert a == b


def test_every_agent_is_either_woken_with_a_reason_or_skipped_with_one(ctx, signals):
    plan = route(ctx, BUSY, signals)
    assert {r.spec.name for r in plan.routed} | {n for n, _ in plan.skipped} == EXPECTED
    for r in plan.routed:
        assert r.trigger.reason_fa.strip()
    for _name, why in plan.skipped:
        assert why.strip()


def test_cost_is_knowable_before_it_is_paid(ctx, signals):
    plan = route(ctx, BUSY, signals)
    assert plan.n_llm_calls == 2 * len(plan.routed)


def test_blocking_gates_lead_the_agenda(ctx, signals):
    """An exhausted credit line is not one opinion among seven."""
    plan = route(ctx, BUSY, signals)
    assert plan.gates["credit_room"] == "exhausted"
    assert plan.routed[0].spec.name == "financial"
    assert plan.routed[0].trigger.blocking


def test_an_open_investigation_outranks_the_credit_gate(ctx, signals):
    """Telling a customer their credit is full while we still owe them the result
    of their complaint is the wrong order — the aggregator already encodes this,
    and the router has to carry the same order into every agent's prompt."""
    plan = route(ctx, BUSY, signals)
    assert plan.gates["open_investigation"] == "pending"
    assert len(plan.constraints) == 2
    assert "پروندهٔ شکایت" in plan.constraints[0]
    assert "سقف اعتبار" in plan.constraints[1]


def test_the_router_discriminates_across_the_book(ctx, signals):
    """A router that wakes everyone for everybody is not routing.

    These are the measured shares at the demo anchor, not targets: what the
    assertion protects is that no agent has collapsed into "always" or "never".
    """
    counts = {name: 0 for name in EXPECTED}
    woken = []
    for cid in ctx.population:
        plan = route(ctx, cid, signals)
        woken.append(len(plan.routed))
        for r in plan.routed:
            counts[r.spec.name] += 1
    n = len(ctx.population)
    assert min(woken) >= 1 and max(woken) <= len(EXPECTED)
    assert 3.0 < sum(woken) / n < 5.5
    for name, hits in counts.items():
        assert 0 < hits < n, f"{name} fires on {hits}/{n} — it decides nothing"


def test_only_agents_narrows_the_meeting(ctx, signals):
    meet = hold_meeting(ctx, BUSY, signals, only_agents=["financial"])
    assert [f.agent for f in meet.findings] == ["financial"]
    assert any(why == "با انتخاب کاربر اجرا نشد." for _n, why in meet.plan.skipped)


# ------------------------------------------------------------------- agents
def test_offline_findings_are_built_only_from_existing_claims(ctx, signals):
    """No key, no invention: the deterministic composer may only rearrange text
    that is already an Evidence, and the finding says it came from rules."""
    meet = hold_meeting(ctx, BUSY, signals)
    assert meet.errors == {}
    assert meet.findings
    for f in meet.findings:
        assert f.source in {"rules", "cached", "live"}
        for eid in f.evidence_ids:
            ev = ctx.evidence.get(eid)
            assert ev is not None and ev.customer_id == BUSY
            assert ev.is_resolvable


def test_an_agent_only_ever_cites_evidence_its_own_tools_returned(ctx, signals):
    """An agent that cites outside its remit is reasoning from something it was
    not shown."""
    meet = hold_meeting(ctx, BUSY, signals)
    for f in meet.findings:
        spec = get_agent(f.agent)
        assert set(f.tools_used) <= set(spec.tools)
        allowed = {
            eid for tool in f.tools_used
            for eid in __import__(
                "nafisnakh.tools", fromlist=["run_tool"]
            ).run_tool(ctx, tool, BUSY).evidence_ids
        }
        assert set(f.evidence_ids) <= allowed, f.agent


def test_a_finding_with_an_unsupported_number_is_emptied_not_softened(ctx, signals):
    """The aggregator's rule, applied to agents. The system says nothing rather
    than something unsupported, and records that it chose to."""
    from nafisnakh.agents.base import _validated, AgentFinding

    finding = AgentFinding(
        agent="financial", customer_id=BUSY, question_fa="q", trigger_fa="t",
        headline_fa="مانده باز 999 میلیارد ریال است.", reasoning_fa="",
        recommended_step_fa="", evidence_ids=[], tools_used=[], tools_reason_fa="",
    )
    out = _validated(finding, ctx)
    assert out.dropped
    assert "منتشر نشد" in out.headline_fa
    assert out.recommended_step_fa == ""


def test_the_plan_phase_cannot_reach_a_tool_the_agent_was_not_given(ctx, signals):
    """The roster is the authority, not the model's answer."""
    from nafisnakh.agents.base import _plan

    class FakeClient:
        def structured(self, system, user, schema, *, fallback=None, use_cache=None):
            from nafisnakh.llm.client import LLMResult

            return LLMResult(
                ToolPlanStub(tools=["get_payment_state", "get_complaints"],
                             why_fa="بهانه"),
                "live", "fake", "h",
            )

    from nafisnakh.agents.base import ToolPlan as ToolPlanStub

    spec = get_agent("supply_feasibility")     # may use dev requests + lab only
    chosen, _why = _plan(FakeClient(), spec, BUSY,
                         Trigger(reason_fa="t"), allow_offline=True)
    assert set(chosen) <= set(spec.tools)
    assert chosen                              # and never empties itself


def test_meeting_brief_and_json_round_trip(ctx, signals, tmp_path):
    from nafisnakh.agents import write_meeting

    meet = hold_meeting(ctx, BUSY, signals, only_agents=["financial", "risk"])
    path = write_meeting(meet, settings=ctx.settings, path=tmp_path / "m.txt")
    text = path.read_text(encoding="utf-8")
    assert "دستور جلسه" in text and BUSY in text
    assert "تحلیل‌گرانی که فعال نشدند" in text
    assert path.with_suffix(".json").exists()

    import json

    payload = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["as_of"] == AS_OF.isoformat()
    assert payload["routing"]["n_llm_calls"] == 2 * len(meet.plan.routed)
