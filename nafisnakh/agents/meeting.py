"""The meeting brief — seven analysts, one agenda (PLAN §3.10).

What this produces is not a summary of the agents; it is an **agenda**. The
difference matters in the room: a summary tells the sales manager what the system
thinks, an agenda tells them what to do first, second and third, and what they
must not offer until something else is settled.

The order is Python. Blocking findings lead — an open investigation, then an
exhausted credit line — and the rest follow the router's weights. No model
reorders the agenda, for the same reason no model ranks the queue (§3.7): the
manager has to be able to ask "why is this first?" and get an arithmetic answer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ..llm.client import LLMClient, get_client
from ..metrics.base import MetricContext
from .base import AgentFinding, run_agent
from .router import RoutingPlan, route

log = logging.getLogger(__name__)


@dataclass
class Meeting:
    customer_id: str
    as_of: date
    plan: RoutingPlan
    findings: list[AgentFinding] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def blocked_by(self) -> list[AgentFinding]:
        return [f for f in self.findings if f.blocking]

    @property
    def dropped(self) -> list[AgentFinding]:
        return [f for f in self.findings if f.dropped]

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "as_of": self.as_of.isoformat(),
            "routing": self.plan.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
            "errors": self.errors,
        }

    def dump_json(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def to_brief_fa(self) -> str:
        lines = [
            f"دستور جلسه — مشتری {self.customer_id}",
            f"تاریخ مبنا: {self.as_of.isoformat()}",
            "=" * 66,
        ]
        gates = self.plan.gates
        lines.append(
            f"اعتبار: {gates.get('credit_room', '—')} · "
            f"پرونده بررسی باز: {gates.get('open_investigation', '—')} · "
            f"لحن: {gates.get('relationship_stance', '—')}"
        )
        if self.plan.constraints:
            lines.append("")
            lines.append("قیدهایی که به همه تحلیل‌گران داده شد:")
            lines += [f"  - {c}" for c in self.plan.constraints]

        lines.append("")
        lines.append(f"تحلیل‌گران فعال‌شده: {len(self.plan.routed)} از "
                     f"{len(self.plan.routed) + len(self.plan.skipped)}")
        for i, f in enumerate(self.findings, start=1):
            mark = " ⛔" if f.blocking else ""
            lines += [
                "",
                f"{i}. [{f.agent}]{mark} {f.question_fa}",
                f"   چرا ارجاع شد: {f.trigger_fa}",
                f"   چه دید: {' · '.join(f.tools_used)} — {f.tools_reason_fa}",
                f"   یافته: {f.headline_fa}",
            ]
            if f.reasoning_fa:
                lines.append(f"   دلیل: {f.reasoning_fa}")
            if f.recommended_step_fa:
                lines.append(f"   قدم: {f.recommended_step_fa}")
            if f.evidence_ids:
                lines.append(f"   شواهد: {'، '.join(f.evidence_ids)}")

        if self.plan.skipped:
            lines += ["", "تحلیل‌گرانی که فعال نشدند:"]
            lines += [f"  - {name}: {why}" for name, why in self.plan.skipped]
        if self.dropped:
            lines += ["", f"⚠️ {len(self.dropped)} یافته در اعتبارسنجی شواهد رد شد و "
                          "منتشر نشده است."]
        lines += ["", "=" * 66,
                  "ترتیب این دستور جلسه در پایتون تعیین شده است، نه توسط مدل زبانی: "
                  "ابتدا قیدهای بازدارنده، سپس وزن روتر. هیچ عددی در متن بالا نیست که "
                  "در متن شاهد ذکرشده‌اش نیامده باشد."]
        return "\n".join(lines)


def hold_meeting(
    ctx: MetricContext,
    customer_id: str,
    signals: list,
    *,
    client: LLMClient | None = None,
    allow_offline: bool = True,
    only_agents: list[str] | None = None,
) -> Meeting:
    """Route, then run each woken agent. One agent's failure never kills the rest."""
    client = client or get_client(ctx.settings)
    plan = route(ctx, customer_id, signals)
    if only_agents is not None:
        wanted = set(only_agents)
        for r in list(plan.routed):
            if r.spec.name not in wanted:
                plan.routed.remove(r)
                plan.skipped.append((r.spec.name, "با انتخاب کاربر اجرا نشد."))

    meeting = Meeting(customer_id=customer_id, as_of=ctx.as_of, plan=plan)
    for r in plan.routed:
        try:
            meeting.findings.append(run_agent(
                ctx, r.spec, customer_id, r.trigger,
                constraints=plan.constraints, client=client,
                allow_offline=allow_offline,
            ))
        except Exception as exc:                   # noqa: BLE001 — report, don't mask
            log.exception("agent %s failed", r.spec.name)
            meeting.errors[r.spec.name] = f"{type(exc).__name__}: {exc}"
    return meeting


def write_meeting(meeting: Meeting, *, settings, path: Path | None = None) -> Path:
    path = path or Path(settings.out_dir) / (
        f"meeting_{meeting.customer_id}_{meeting.as_of.isoformat()}.txt"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meeting.to_brief_fa(), encoding="utf-8")
    meeting.dump_json(path.with_suffix(".json"))
    return path
