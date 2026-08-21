"""Agent contract and the two-phase runner (PLAN §3.10, step 5).

An agent answers one question about one customer, using its own subset of the
tool layer. It is deliberately **not** a free-running tool loop, and the reason
is worth stating because it is a design choice, not a limitation:

* an unbounded loop costs an unpredictable number of paid calls per customer;
* its cache key grows with the conversation, so re-runs stop being free;
* and "why did it look at that?" becomes a transcript to read rather than a
  decision to inspect.

Instead each agent runs in two structured calls, both cached like every other
call in this package:

1. **plan** — the agent is shown the tools it *may* use, with their Persian
   descriptions, and the router's reason for waking it. It answers which tools it
   wants and why. This is where "the agent decides what to look at" actually
   happens, and the answer is recorded.
2. **answer** — the agent is given the output of exactly those tools — claims and
   evidence ids, never numbers — and returns its finding.

Offline both phases degrade explicitly: plan falls back to *all* of the agent's
tools, answer falls back to a deterministic Persian composer, and the finding is
tagged ``source="rules"`` so nothing pretends a model wrote it.

Every finding then goes through the same validator the aggregator uses: a numeral
in the text that is absent from the cited evidence drops the finding. An agent
gets no exemption from the rule that the model never writes numbers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ..llm.client import LLMClient, LLMUnavailable, get_client
from ..metrics.base import MetricContext
from ..tools import get_tool, run_tool

log = logging.getLogger(__name__)

MAX_TOOLS_PER_AGENT = 4


@dataclass(frozen=True)
class Trigger:
    """Why the router woke this agent — deterministic, and always shown."""

    reason_fa: str
    weight: float = 1.0
    blocking: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentFinding:
    agent: str
    customer_id: str
    question_fa: str
    trigger_fa: str
    headline_fa: str
    reasoning_fa: str
    recommended_step_fa: str
    evidence_ids: list[str]
    tools_used: list[str]
    tools_reason_fa: str
    blocking: bool = False
    weight: float = 1.0
    source: str = "rules"
    dropped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolPlan(BaseModel):
    """Phase 1 — what this agent wants to look at, and why."""

    tools: list[str] = Field(description="نام ابزارهایی که لازم داری، از همان فهرست")
    why_fa: str = Field(description="در یک جمله بگو چرا همین‌ها")


class AgentAnswer(BaseModel):
    """Phase 2 — the finding. No numbers: the model writes reasoning only."""

    headline_fa: str = Field(description="یک جمله؛ مهم‌ترین چیزی که یافتی")
    reasoning_fa: str = Field(
        description="دلیل، با ارجاع درون‌متنی به شناسه‌های شاهد مثل [EV-...]"
    )
    recommended_step_fa: str = Field(description="یک قدم مشخص و قابل انجام")
    evidence_ids: list[str] = Field(description="فقط شناسه‌هایی که واقعاً استفاده کردی")


@dataclass(frozen=True)
class AgentSpec:
    name: str
    question_fa: str
    role_fa: str
    tools: tuple[str, ...]
    trigger: Callable[[MetricContext, str, list], Trigger | None]
    #: what this agent may never say, appended to its prompt verbatim
    forbidden_fa: str = ""


_REGISTRY: dict[str, AgentSpec] = {}


def register(spec: AgentSpec) -> AgentSpec:
    if spec.name in _REGISTRY:
        raise ValueError(f"duplicate agent {spec.name!r}")
    for t in spec.tools:
        get_tool(t)          # fail at import time, not mid-meeting
    _REGISTRY[spec.name] = spec
    return spec


def all_agents() -> list[AgentSpec]:
    from . import roster  # noqa: F401 — import for side-effect registration

    return list(_REGISTRY.values())


def get_agent(name: str) -> AgentSpec:
    from . import roster  # noqa: F401

    if name not in _REGISTRY:
        raise KeyError(f"unknown agent {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


# --------------------------------------------------------------------- prompts
SYSTEM_TEMPLATE = """تو یکی از تحلیل‌گران تیم فروش شرکت نفیس نخ (تولیدکننده نخ POY) هستی.

نقش تو: {role_fa}
سوالی که فقط تو باید جواب بدهی: {question_fa}

قواعد سختگیرانه:
- **هیچ عددی ننویس که در متن شواهد داده‌شده نیامده باشد.** اگر عددی لازم داری، همان
  عبارت شاهد را بیاور و شناسه‌اش را ذکر کن.
- به هر ادعا شناسه شاهد را به شکل [EV-...] بچسبان. فقط از شناسه‌های همین ورودی.
- از حوزه خودت خارج نشو؛ تحلیل‌گران دیگر بخش‌های دیگر را پوشش می‌دهند.
- قدم پیشنهادی باید مشخص باشد (تماس، جلسه، بازنگری قرارداد، اقدام فنی)، نه توصیه کلی.
{forbidden}{constraints}"""

PLAN_SYSTEM = """تو یکی از تحلیل‌گران تیم فروش نفیس نخ هستی.

نقش تو: {role_fa}
سوال تو: {question_fa}

فهرست ابزارهایی که مجاز به استفاده از آنها هستی در ادامه می‌آید. فقط نام ابزارهایی را
برگردان که برای جواب دادن به سوال خودت واقعاً لازم داری — نه بیشتر. حداکثر {max_tools}
ابزار."""


def _constraints_block(constraints: list[str]) -> str:
    """Constraints bind the agent; they do not become its output.

    Without the second sentence every one of the seven analysts closes its
    recommendation by restating the same credit and investigation caveats, and
    the agenda reads as one paragraph copied seven times. They are printed once,
    at the top of the brief, by :meth:`Meeting.to_brief_fa`.
    """
    if not constraints:
        return ""
    lines = "\n".join(f"- {c}" for c in constraints)
    return (
        "\n\nقیدهایی که باید رعایت کنی:\n" + lines
        + "\n\nاین قیدها یک بار در بالای دستور جلسه نوشته می‌شوند. آنها را در متن خودت "
          "تکرار نکن؛ فقط رعایتشان کن — یعنی قدمی پیشنهاد نده که این قیدها اجازه‌اش را "
          "نمی‌دهند."
    )


# ----------------------------------------------------------------- the runner
def run_agent(
    ctx: MetricContext,
    spec: AgentSpec,
    customer_id: str,
    trigger: Trigger,
    *,
    constraints: list[str] | None = None,
    client: LLMClient | None = None,
    allow_offline: bool = True,
) -> AgentFinding:
    """Plan, then answer. Both phases cached; both degrade explicitly."""
    client = client or get_client(ctx.settings)
    constraints = constraints or []

    chosen, why = _plan(client, spec, customer_id, trigger, allow_offline)
    results = [run_tool(ctx, name, customer_id) for name in chosen]
    # An agent that looked and found nothing must say so; feeding it an empty
    # block invites it to reason from memory instead of from the book.
    tool_text = "\n\n".join(r.to_model_text() for r in results) or "هیچ داده‌ای برنگشت."

    system = SYSTEM_TEMPLATE.format(
        role_fa=spec.role_fa, question_fa=spec.question_fa,
        forbidden=(f"- {spec.forbidden_fa}\n" if spec.forbidden_fa else ""),
        constraints=_constraints_block(constraints),
    )
    user = (
        f"مشتری: {customer_id}\n"
        f"چرا این پرونده به تو ارجاع شده: {trigger.reason_fa}\n\n"
        f"داده‌هایی که ابزارهای خودت برگرداندند:\n{tool_text}"
    )
    available = {eid for r in results for eid in r.evidence_ids}

    try:
        res = client.structured(
            system, user, AgentAnswer,
            fallback=(lambda: _compose_offline(spec, trigger, results))
            if allow_offline else None,
        )
    except LLMUnavailable:
        log.warning("no LLM and offline disabled — skipping agent %s", spec.name)
        raise

    answer: AgentAnswer = res.value
    cited = [e for e in answer.evidence_ids if e in available]
    finding = AgentFinding(
        agent=spec.name, customer_id=customer_id, question_fa=spec.question_fa,
        trigger_fa=trigger.reason_fa, headline_fa=answer.headline_fa,
        reasoning_fa=answer.reasoning_fa,
        recommended_step_fa=answer.recommended_step_fa,
        evidence_ids=cited, tools_used=list(chosen), tools_reason_fa=why,
        blocking=trigger.blocking, weight=trigger.weight, source=res.source,
    )
    return _validated(finding, ctx)


def _plan(client, spec, customer_id, trigger, allow_offline) -> tuple[list[str], str]:
    catalogue = "\n".join(
        f"- {name}: {get_tool(name).description_fa}" for name in spec.tools
    )
    system = PLAN_SYSTEM.format(role_fa=spec.role_fa, question_fa=spec.question_fa,
                                max_tools=MAX_TOOLS_PER_AGENT)
    user = (f"مشتری: {customer_id}\n"
            f"چرا این پرونده به تو ارجاع شده: {trigger.reason_fa}\n\n"
            f"ابزارهای مجاز:\n{catalogue}")
    try:
        res = client.structured(
            system, user, ToolPlan,
            fallback=(lambda: ToolPlan(tools=list(spec.tools),
                                       why_fa="بدون مدل — همه ابزارهای مجاز اجرا شدند."))
            if allow_offline else None,
        )
    except LLMUnavailable:
        raise
    # the model may name a tool it was not given; the roster is the authority
    chosen = [t for t in res.value.tools if t in spec.tools][:MAX_TOOLS_PER_AGENT]
    return (chosen or list(spec.tools)[:MAX_TOOLS_PER_AGENT]), res.value.why_fa


def _compose_offline(spec, trigger, results) -> AgentAnswer:
    """Deterministic Persian, built only from claims that already exist."""
    claims = [(eid, claim) for r in results
              for eid, claim in zip(r.evidence_ids, r.claims)]
    if not claims:
        return AgentAnswer(
            headline_fa=f"برای «{spec.question_fa}» داده‌ای در این تاریخ نیست.",
            reasoning_fa=trigger.reason_fa,
            recommended_step_fa="پیش از تصمیم، داده این حوزه تکمیل شود.",
            evidence_ids=[],
        )
    head = claims[0]
    body = " ".join(f"{claim} [{eid}]" for eid, claim in claims[:3])
    return AgentAnswer(
        headline_fa=head[1],
        reasoning_fa=body,
        recommended_step_fa=f"این موضوع در جلسه بعدی طرح شود: {spec.question_fa}",
        evidence_ids=[eid for eid, _ in claims[:3]],
    )


def _validated(finding: AgentFinding, ctx: MetricContext) -> AgentFinding:
    """The aggregator's rule, applied to agents too.

    A finding whose text carries a numeral absent from its cited evidence is not
    softened or re-prompted here — it is emptied, and what was dropped is recorded
    on the finding so the meeting brief can show that the system chose to say
    nothing rather than say something unsupported.
    """
    from ..aggregate.validate import validate_action

    texts = [finding.headline_fa, finding.reasoning_fa, finding.recommended_step_fa]
    result = validate_action(finding, ctx.evidence, texts=texts)
    if result.ok:
        return finding
    finding.dropped = [i.detail for i in result.issues]
    finding.headline_fa = (
        f"یافته این تحلیل‌گر منتشر نشد: متنی تولید شد که پشتوانه شاهدی نداشت "
        f"({finding.agent})."
    )
    finding.reasoning_fa = " · ".join(finding.dropped)
    finding.recommended_step_fa = ""
    return finding
