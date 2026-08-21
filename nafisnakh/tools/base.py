"""The tool contract — what an agent is allowed to see (PLAN §3.1, step 4).

A tool answers one question about one customer. What it hands back is **not** a
dict of numbers: it is a list of Persian claims, each already registered as an
:class:`~nafisnakh.core.evidence.Evidence` with a locator, plus the ids. That is
the whole point of the layer. The agent in step 5 reasons over sentences and
cites ids; it never sees a bare figure it could restate, round, or combine into
a number nobody computed — and ``aggregate/validate.py`` still refuses any
action whose text contains a numeral absent from its cited evidence.

So a tool result has two faces:

* :meth:`ToolResult.to_model_text` — claims and ids. This is what goes into a
  prompt.
* :attr:`ToolResult.payload` — the structured rows, for Python: the 360° page,
  the tests, a future API. **Never rendered into a prompt.**

Three rules every tool obeys:

1. **Nothing after ``as_of``.** Tools read through ``core.spine.visible`` or off
   metric tables that already did, so rule #4 holds without each tool restating it.
2. **An empty answer is an answer.** ``empty_reason_fa`` says *why* there is
   nothing, because an agent handed an empty string invents a reason.
3. **Coverage limits travel with the data.** ``note_fa`` carries what the sheet
   cannot support — the market sheet has 130 rows for 526 customers, and a tool
   that returns it silently invites the agent to over-read it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..metrics.base import MetricContext


@dataclass(frozen=True)
class ToolResult:
    tool: str
    customer_id: str
    claims: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    note_fa: str = ""
    empty_reason_fa: str = ""

    @property
    def empty(self) -> bool:
        return not self.evidence_ids

    def to_model_text(self) -> str:
        """Claims and ids only — the sole thing a prompt is ever given."""
        head = f"ابزار: {self.tool} · مشتری {self.customer_id}"
        if self.empty:
            reason = self.empty_reason_fa or "موردی یافت نشد."
            return f"{head}\nموردی یافت نشد: {reason}"
        lines = [head]
        for eid, claim in zip(self.evidence_ids, self.claims):
            lines.append(f"[{eid}] {claim}")
        if self.note_fa:
            lines.append(f"یادداشت: {self.note_fa}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description_fa: str
    fn: Callable[..., ToolResult]
    params: dict[str, str] = field(default_factory=dict)

    def json_schema(self) -> dict[str, Any]:
        """OpenAI/OpenRouter function-calling shape, for step 5's binding."""
        props = {
            "customer_id": {"type": "string", "description": "شناسه مشتری"},
            **{k: {"type": "integer", "description": v} for k, v in self.params.items()},
        }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description_fa,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": ["customer_id"],
                },
            },
        }


_REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, description_fa: str, **params: str):
    """Register a tool. ``params`` documents the optional integer arguments."""

    def wrap(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        if name in _REGISTRY:
            raise ValueError(f"duplicate tool name {name!r}")
        _REGISTRY[name] = ToolSpec(name=name, description_fa=description_fa,
                                   fn=fn, params=params)
        return fn

    return wrap


def all_tools() -> list[ToolSpec]:
    from . import customer  # noqa: F401 — import for side-effect registration

    return list(_REGISTRY.values())


def get_tool(name: str) -> ToolSpec:
    from . import customer  # noqa: F401

    if name not in _REGISTRY:
        raise KeyError(f"unknown tool {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def tool_schemas() -> list[dict[str, Any]]:
    return [spec.json_schema() for spec in all_tools()]


def run_tool(ctx: MetricContext, name: str, customer_id: str, **kwargs) -> ToolResult:
    """Call a tool, memoised on the context.

    Memoising is not an optimisation, it is correctness: ``ctx.emit`` mints a new
    id on every call, so a tool invoked twice would hand the agent two different
    ids for the same fact and the 360° page would list it twice. One call per
    (tool, customer, arguments) per context.
    """
    spec = get_tool(name)
    key = (name, customer_id, tuple(sorted(kwargs.items())))
    cached = ctx.cache.setdefault("tools", {})
    if key not in cached:
        cached[key] = spec.fn(ctx, customer_id, **kwargs)
    return cached[key]
