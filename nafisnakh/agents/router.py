"""The deterministic router (PLAN §3.10).

No model decides which agents run. Every trigger is Python over metric tables and
the signal run, and the routing decision is printed in full — for each of the
seven agents, either the sentence that woke it or the sentence saying why it
stayed asleep. Three things follow, and all three were the point:

* **The cost of a meeting is knowable before it is paid.** Two calls per woken
  agent, and the count is visible in the plan.
* **"Why did it look at that?" is a decision to read, not a transcript to
  reconstruct.**
* **A quiet account produces a short meeting.** An agent with nothing to say is
  not woken to say it.

The two hard gates travel with the plan as **constraints** and are appended to
every woken agent's prompt. An open investigation outranks the credit gate, for
the reason the aggregator already encodes: telling a customer their credit is
full while we still owe them the result of a complaint is the wrong order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..metrics.base import MetricContext
from .base import AgentSpec, Trigger, all_agents


@dataclass(frozen=True)
class RoutedAgent:
    spec: AgentSpec
    trigger: Trigger


@dataclass
class RoutingPlan:
    customer_id: str
    routed: list[RoutedAgent] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    gates: dict[str, Any] = field(default_factory=dict)

    @property
    def n_llm_calls(self) -> int:
        """Two per woken agent: plan, then answer. Knowable before it is paid."""
        return 2 * len(self.routed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "routed": [
                {"agent": r.spec.name, "reason_fa": r.trigger.reason_fa,
                 "weight": r.trigger.weight, "blocking": r.trigger.blocking,
                 "detail": r.trigger.detail}
                for r in self.routed
            ],
            "skipped": [{"agent": a, "reason_fa": why} for a, why in self.skipped],
            "constraints": self.constraints,
            "gates": self.gates,
            "n_llm_calls": self.n_llm_calls,
        }


# These have to say what the trigger actually tests. A skip reason that describes
# an older version of its trigger is worse than none: it is the one sentence the
# reader has to explain why an analyst stayed silent.
SKIP_REASON_FA = {
    "open_loops": "هیچ تعهد بازی از سمت ما روی این مشتری ثبت نیست.",
    "risk": "هیچ سیگنال ریسکی فعال نشده و لات در معرض خطری ثبت نیست.",
    "opportunity": ("هیچ سیگنال فرصتی فعال نشده و نمونه تأییدشده‌ای هم بدون آفر "
                    "نمانده است."),
    "financial": ("سقف اعتبار باز است، سیگنال مالی فعال نیست، اشغال سقف سنگین نیست و "
                  "اثر خالص مالی منفی نیست — چیزی برای تعیین تکلیف نمانده."),
    "relationship": ("نه شکایت بازی هست، نه شکایتی رد شده، نه بررسی ناتمامی، و نه "
                     "موضعی از سابقه بررسی‌ها — لحن ورود سوال باز نیست."),
    "pricing": "نه سیگنال قیمتی فعال است و نه آفر بی‌پاسخی مانده است.",
    "supply_feasibility": "این مشتری هیچ درخواست توسعه‌ای ثبت نکرده است.",
}


def route(ctx: MetricContext, customer_id: str, signals: list) -> RoutingPlan:
    """Which agents this customer's file actually needs, and why."""
    from ..aggregate.aggregator import (
        CREDIT_NOTE_FA,
        INVESTIGATION_NOTE_FA,
        credit_state,
        investigation_state,
    )

    mine = [s for s in signals if s.customer_id == customer_id]
    plan = RoutingPlan(customer_id=customer_id)

    credit = credit_state(ctx, customer_id)
    investigation = investigation_state(ctx, customer_id)
    plan.gates = {
        "credit_room": credit,
        "open_investigation": investigation.get("state", "clear"),
        "relationship_stance": investigation.get("stance", "neutral"),
    }
    # Order matters and is not cosmetic: an unfinished investigation outranks a
    # full credit line, because telling a customer their credit is exhausted
    # while we still owe them the result of their complaint is the wrong order.
    if investigation.get("pending"):
        plan.constraints.append(INVESTIGATION_NOTE_FA["pending"])
    if credit in CREDIT_NOTE_FA and credit != "open":
        plan.constraints.append(CREDIT_NOTE_FA[credit])

    for spec in all_agents():
        trigger = spec.trigger(ctx, customer_id, mine)
        if trigger is None:
            plan.skipped.append((spec.name, SKIP_REASON_FA.get(spec.name, "شرط فعال‌شدن برقرار نبود.")))
        else:
            plan.routed.append(RoutedAgent(spec=spec, trigger=trigger))

    # Blocking findings lead; after that, the router's own weights. Nothing here
    # is decided by a model — the same input always produces the same agenda.
    plan.routed.sort(key=lambda r: (not r.trigger.blocking, -r.trigger.weight,
                                    r.spec.name))
    return plan
