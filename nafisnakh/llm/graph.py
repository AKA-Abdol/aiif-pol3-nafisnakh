"""LangGraph wiring of the whole pipeline (PLAN §3.2, Q3).

The pipeline is a straight line today — load → metrics → complaint block →
detectors → quadrants → actions → validate — so a plain function would run it.
It is expressed as a graph anyway for the reasons the plan cares about: each
stage becomes independently addressable and resumable, the state carries the
evidence registry rather than hidden globals, and the branch that Phase 2 needs
(a relationship block that only runs for certain buckets, a retry loop around
the aggregator) attaches without rewriting the flow.

The graph is pure orchestration. Every stage is implemented in its own module
and is separately testable without importing this file.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, TypedDict

from ..aggregate.aggregator import ActionQueue, build_actions
from ..aggregate.quadrant import QuadrantResult, assign_quadrants
from ..config import Settings, get_settings
from ..io.loader import Dataset, load_dataset
from ..metrics.base import MetricContext, build_metrics, make_context
from ..signals.engine import CalibrationReport, SignalRun, calibrate, run_detectors
from ..feedback import FeedbackStore, detector_weights
from .blocks.complaint import attach_to_context
from .blocks.relationship import attach_to_context as attach_relationship

log = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    settings: Settings
    as_of: date
    dataset: Dataset
    ctx: MetricContext
    signals: SignalRun
    calibration: CalibrationReport
    quadrants: QuadrantResult
    queue: ActionQueue
    weights: dict[str, float]
    options: dict[str, Any]


# ------------------------------------------------------------------ the nodes
def node_load(state: PipelineState) -> PipelineState:
    st = state["settings"]
    opts = state.get("options", {})
    ds = load_dataset(st)
    if opts.get("customers") or opts.get("sample"):
        from ..io.loader import subset_dataset

        ds = subset_dataset(
            ds, opts.get("customers"), sample=opts.get("sample", 0) or 0
        )
    return {"dataset": ds}


def node_metrics(state: PipelineState) -> PipelineState:
    ctx = make_context(state["dataset"], as_of=state["as_of"], settings=state["settings"])
    return {"ctx": build_metrics(ctx)}


def node_complaint_llm(state: PipelineState) -> PipelineState:
    opts = state.get("options", {})
    if opts.get("skip_llm"):
        state["ctx"].tables.setdefault("llm_complaints", None)
        log.info("complaint LLM block skipped by option")
        return {"ctx": state["ctx"]}
    attach_to_context(
        state["ctx"],
        allow_rules=opts.get("allow_rules", True),
        universe=opts.get("universe"),
    )
    return {"ctx": state["ctx"]}


def node_feedback(state: PipelineState) -> PipelineState:
    """Load the sales manager's verdicts and turn them into ranking weights.

    No feedback file, or too few events, means an empty mapping — which every
    consumer reads as a weight of 1.0.
    """
    if state.get("options", {}).get("ignore_feedback"):
        return {"weights": {}}
    store = FeedbackStore(settings=state["settings"])
    return {"weights": detector_weights(store, state["settings"])}


def node_detect(state: PipelineState) -> PipelineState:
    run = run_detectors(state["ctx"], weights=state.get("weights"))
    return {"signals": run, "calibration": calibrate(run, state["ctx"])}


def node_quadrant(state: PipelineState) -> PipelineState:
    return {"quadrants": assign_quadrants(state["ctx"])}


def node_relationship(state: PipelineState) -> PipelineState:
    """Phase 2 synthesis, bounded to the accounts that will actually be worked."""
    opts = state.get("options", {})
    if opts.get("skip_relationship"):
        return {"ctx": state["ctx"]}
    attach_relationship(
        state["ctx"], state["signals"], state["quadrants"],
        allow_rules=opts.get("allow_rules", True),
        top_n=opts.get("top_n") or state["settings"].top_n_actions,
    )
    return {"ctx": state["ctx"]}


def node_aggregate(state: PipelineState) -> PipelineState:
    opts = state.get("options", {})
    queue = build_actions(
        state["ctx"], state["signals"], state["quadrants"],
        top_n=opts.get("top_n"),
        allow_offline=opts.get("allow_rules", True),
    )
    return {"queue": queue}


NODES = [
    ("load", node_load),
    ("metrics", node_metrics),
    ("complaint_llm", node_complaint_llm),
    ("feedback", node_feedback),
    ("detect", node_detect),
    ("quadrant", node_quadrant),
    ("relationship", node_relationship),
    ("aggregate", node_aggregate),
]


def build_graph():
    """Compile the LangGraph pipeline."""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)
    for name, fn in NODES:
        g.add_node(name, fn)
    g.add_edge(START, NODES[0][0])
    for (a, _), (b, _) in zip(NODES, NODES[1:]):
        g.add_edge(a, b)
    g.add_edge(NODES[-1][0], END)
    return g.compile()


def run_pipeline(
    *,
    settings: Settings | None = None,
    as_of: date | None = None,
    dataset: Dataset | None = None,
    use_graph: bool = True,
    **options,
) -> PipelineState:
    """Run the whole thing. ``use_graph=False`` runs the same nodes in sequence,
    which is what the tests use so a LangGraph version bump cannot silently
    change what is being tested."""
    st = settings or get_settings()
    state: PipelineState = {
        "settings": st,
        "as_of": as_of or st.as_of,
        "options": options,
    }
    if dataset is not None:
        state["dataset"] = dataset

    if use_graph and dataset is None:
        return dict(build_graph().invoke(state))

    for name, fn in NODES:
        if name == "load" and "dataset" in state:
            continue
        state.update(fn(state))
    return state
