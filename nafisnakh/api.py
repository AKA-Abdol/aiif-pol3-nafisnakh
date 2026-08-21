"""HTTP surface (PLAN §4, Phase 2; Q2 said "convertible to an API later").

The API adds **no logic of its own**. Every endpoint is a thin projection of
something the library already computes, so there is no second implementation of
the ranking, the buckets, the routing or the validation that could drift away
from the CLI's.

Four design points, three of them learned the hard way elsewhere in this project:

* **A run is cached per (as_of, stage).** Stopping at ``quadrant`` costs seconds
  and no model calls; running to ``aggregate`` costs one drafting call per action.
  Serving `/calibration` should not pay for the action queue, so the stage is part
  of the cache key and each endpoint asks for the least it needs.
* **Nothing that spends money is a GET.** A browser refresh must not bill the
  user. `/meeting/plan` is free and is a GET; holding the meeting is a POST.
* **Concurrency.** FastAPI runs sync handlers in a threadpool, so two requests
  arriving for a cold ``as_of`` would otherwise both compute the same pipeline.
  A lock around the miss makes the second wait for the first.
* **Feedback is the only write.** ``POST /feedback`` appends a manager decision
  and invalidates the cache, because the next queue should be ranked with the
  verdict just given.

Run it with `nafisnakh serve`, or:

```bash
uvicorn nafisnakh.api:app --reload
```
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .feedback import FeedbackStore, detector_stats, detector_weights
from .llm.graph import run_pipeline

log = logging.getLogger(__name__)

app = FastAPI(
    title="Nafis Nakh — AI B2B CRM Copilot",
    version="0.2.0",
    description=(
        "صف اقدام مبتنی بر شواهد برای مدیر فروش. هر اقدام به شناسه‌های شاهد ارجاع "
        "می‌دهد، هیچ عددی خارج از شواهد در متن نمی‌آید، و هر شاهد را می‌توان با "
        "‪/evidence/{id}/rows‬ تا ردیف‌های واقعی همان ادعا باز کرد."
    ),
)

#: ``quadrant`` = metrics + LLM blocks + detectors + buckets, no drafting calls.
#: ``None`` = the whole pipeline, including one drafting call per queued action.
Stage = Literal["quadrant", "full"]

_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def _state(as_of: date | None = None, *, stage: Stage = "quadrant",
           top_n: int | None = None):
    st = get_settings()
    as_of = as_of or st.as_of
    top_n = top_n or st.top_n_actions
    key = f"{as_of.isoformat()}|{stage}|{top_n if stage == 'full' else '-'}"
    with _LOCK:
        if key not in _CACHE:
            log.info("computing pipeline for %s", key)
            _CACHE[key] = run_pipeline(
                settings=st, as_of=as_of, top_n=top_n, use_graph=False,
                stop_after=None if stage == "full" else "quadrant",
            )
        return _CACHE[key]


def _invalidate() -> None:
    with _LOCK:
        _CACHE.clear()


def _ctx(as_of: date | None, customer_id: str | None = None):
    state = _state(as_of)
    if customer_id is not None and customer_id not in set(state["ctx"].population):
        raise HTTPException(
            404,
            f"customer {customer_id} has no visible sales line at "
            f"{state['as_of'].isoformat()}",
        )
    return state


def _jsonable(value: Any) -> Any:
    """pandas/numpy scalars and NaN out of a metric row, into JSON."""
    import numpy as np
    import pandas as pd

    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and pd.isna(value):
        return None
    if value is not None and not isinstance(value, (str, int, float, bool)):
        return str(value)
    return value


def _row(state, table: str, customer_id: str) -> dict | None:
    t = state["ctx"].tables.get(table)
    if t is None or customer_id not in t.index:
        return None
    return {k: _jsonable(v) for k, v in t.loc[customer_id].to_dict().items()}


# --------------------------------------------------------------------- models
class ActionOut(BaseModel):
    customer_id: str
    rank: int
    priority: str
    bucket: str
    title_fa: str
    rationale_fa: str
    recommended_step_fa: str
    owner: str
    evidence_ids: list[str]
    signals: list[str]
    value_at_stake: float
    source: str
    detail: dict = Field(default_factory=dict)


class EvidenceOut(BaseModel):
    id: str
    customer_id: str
    kind: str
    claim_fa: str
    value: Any
    unit: str | None
    as_of: str
    window: list[str] | None = None
    source_rows: str
    provenance: dict
    confidence: float
    locator: dict | None = None


class FeedbackIn(BaseModel):
    customer_id: str
    decision: Literal["done", "dismissed", "snoozed", "wrong"]
    detectors: list[str] = Field(default_factory=list)
    reason_fa: str | None = None
    actor: str | None = None
    rank: int | None = None
    bucket: str | None = None


class MeetingIn(BaseModel):
    agents: list[str] | None = Field(
        default=None, description="اگر خالی باشد، هر تحلیل‌گری که روتر بیدار کند"
    )


# ------------------------------------------------------------------ endpoints
@app.get("/health", tags=["system"])
def health() -> dict:
    st = get_settings()
    return {
        "status": "ok",
        "as_of": st.as_of.isoformat(),
        "llm_available": st.llm_available,
        "llm_model": st.active_model,
        "llm_provider": st.active_provider_only or None,
        "cached_runs": sorted(_CACHE),
    }


@app.get("/summary", tags=["system"])
def summary(as_of: date | None = None) -> dict:
    state = _state(as_of)
    run = state["signals"]
    ctx = state["ctx"]
    return {
        "as_of": state["as_of"].isoformat(),
        "customers": len(ctx.population),
        "signals": len(run.signals),
        "triggered_customers": len(run.triggered_customers()),
        "detectors": len(run.fire_rates),
        "quadrants": state["quadrants"].counts(),
        "evidence": len(ctx.evidence),
        "metric_tables": list(ctx.tables),
        "feedback_weights": state.get("weights", {}),
    }


@app.get("/actions", response_model=list[ActionOut], tags=["queue"])
def actions(
    as_of: date | None = None,
    bucket: str | None = Query(None, pattern="^(grow|protect|fix|reduce)$"),
    priority: str | None = None,
    limit: int = Query(25, ge=1, le=200),
) -> list[ActionOut]:
    """The ranked action queue. Costs one drafting call per action on a cold run."""
    queue = _state(as_of, stage="full", top_n=limit)["queue"]
    rows = queue.actions
    if bucket:
        rows = [a for a in rows if a.bucket == bucket]
    if priority:
        rows = [a for a in rows if a.priority == priority]
    return [ActionOut(**a.to_dict()) for a in rows[:limit]]


@app.get("/customers", tags=["customer"])
def customers(
    as_of: date | None = None,
    bucket: str | None = Query(None, pattern="^(grow|protect|fix|reduce)$"),
    segment: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """The book, with just enough per row to pick one to open."""
    state = _state(as_of)
    quad, rfm = state["quadrants"].table, state["ctx"].table("rfm")
    loops = state["ctx"].table("open_loops")
    # the segment lives on `economics`, not on the quadrant table
    econ = state["ctx"].table("economics")
    by_customer = state["signals"].by_customer()
    rows = []
    for cid in state["ctx"].population:
        b = quad.loc[cid, "bucket"] if cid in quad.index else None
        if bucket and b != bucket:
            continue
        seg = econ.loc[cid, "segment"] if cid in econ.index else None
        if segment and seg != segment:
            continue
        rows.append({
            "customer_id": cid,
            "bucket": b,
            "segment": _jsonable(seg),
            "rfm_cell": _jsonable(rfm.loc[cid, "rfm_cell"]) if cid in rfm.index else None,
            "rfm_segment_fa": (_jsonable(rfm.loc[cid, "rfm_segment_fa"])
                               if cid in rfm.index else None),
            "open_loops": (_jsonable(loops.loc[cid, "open_loop_count"])
                           if cid in loops.index else None),
            "signals": len(by_customer.get(cid, [])),
        })
    rows.sort(key=lambda r: (-(r["signals"] or 0), r["customer_id"]))
    return {"as_of": state["as_of"].isoformat(), "total": len(rows),
            "customers": rows[:limit]}


@app.get("/customers/{customer_id}", tags=["customer"])
def customer(customer_id: str, as_of: date | None = None) -> dict:
    """Everything the 360° page is built from, as JSON."""
    state = _ctx(as_of, customer_id)
    ctx, quadrants = state["ctx"], state["quadrants"]
    signals = state["signals"].by_customer().get(customer_id, [])

    relationship = ctx.tables.get("relationship")
    rel = None
    if relationship is not None and len(relationship) and customer_id in relationship.index:
        rel = {k: _jsonable(v) for k, v in relationship.loc[customer_id].to_dict().items()}
    return {
        "customer_id": customer_id,
        "as_of": state["as_of"].isoformat(),
        "bucket": quadrants.bucket_of(customer_id),
        "bucket_reason_fa": (
            quadrants.table.loc[customer_id, "bucket_reason_fa"]
            if customer_id in quadrants.table.index else None
        ),
        "rfm": _row(state, "rfm", customer_id),
        "open_loops": _row(state, "open_loops", customer_id),
        "payment": _row(state, "payment", customer_id),
        "quality": _row(state, "quality", customer_id),
        "signals": [s.to_dict() for s in signals],
        "evidence": [e.to_dict() for e in ctx.evidence.for_customer(customer_id)],
        "relationship": rel,
    }


@app.get("/customers/{customer_id}/page", response_class=HTMLResponse, tags=["customer"])
def customer_page(customer_id: str, as_of: date | None = None,
                  rows: int = Query(25, ge=1, le=200)) -> HTMLResponse:
    """The 360° page, served inline — every claim expandable to its source rows."""
    from .customer360 import render_customer, run_all_tools

    state = _ctx(as_of, customer_id)
    run_all_tools(state["ctx"], customer_id)
    return HTMLResponse(render_customer(
        customer_id, state, settings=state["settings"], max_rows=rows
    ))


# ---------------------------------------------------------------- evidence
@app.get("/evidence/{evidence_id}", response_model=EvidenceOut, tags=["evidence"])
def evidence(evidence_id: str, as_of: date | None = None) -> EvidenceOut:
    ev = _state(as_of)["ctx"].evidence.get(evidence_id)
    if ev is None:
        raise HTTPException(404, f"evidence {evidence_id} not found")
    return EvidenceOut(**ev.to_dict())


@app.get("/evidence/{evidence_id}/rows", tags=["evidence"])
def evidence_rows(evidence_id: str, as_of: date | None = None,
                  limit: int = Query(50, ge=1, le=500)) -> dict:
    """The actual workbook rows behind one claim.

    This is the endpoint the whole evidence contract exists for: a recommendation
    shown to a customer has to be openable down to the records it rests on. The
    drill-down is gated at ``as_of`` by rule #4, exactly as the calculation was.
    """
    from .core.evidence import resolve

    state = _state(as_of)
    ev = state["ctx"].evidence.get(evidence_id)
    if ev is None:
        raise HTTPException(404, f"evidence {evidence_id} not found")
    if not ev.is_resolvable:
        raise HTTPException(409, f"evidence {evidence_id} carries no locator")
    frame = resolve(ev, state["ctx"].ds)
    cols = [c for c in frame.columns if c not in ("_universe", "is_fixture")]
    return {
        "evidence_id": ev.id,
        "claim_fa": ev.claim_fa,
        "as_of": ev.as_of.isoformat(),
        "locator": ev.locator,
        "n_rows": int(len(frame)),
        "columns": cols,
        "rows": [
            {c: _jsonable(v) for c, v in r.items()}
            for _, r in frame.head(limit)[cols].iterrows()
        ],
    }


# ------------------------------------------------------------------- tools
@app.get("/tools", tags=["tools"])
def tools() -> dict:
    """The eight tools an agent may reach the data through, with their schemas."""
    from .tools import all_tools

    return {
        "tools": [
            {"name": t.name, "description_fa": t.description_fa,
             "params": t.params, "schema": t.json_schema()}
            for t in all_tools()
        ]
    }


@app.get("/customers/{customer_id}/tools", tags=["tools"])
def customer_tools(customer_id: str, as_of: date | None = None,
                   tool: str | None = None) -> dict:
    """Exactly what an agent would be handed: claims and evidence ids, no numbers.

    ``payload`` is the Python-side structure and is included here because this is
    an API, not a prompt — it is never rendered into one.
    """
    from .customer360 import run_all_tools
    from .tools import get_tool, run_tool

    state = _ctx(as_of, customer_id)
    ctx = state["ctx"]
    if tool:
        try:
            results = [run_tool(ctx, get_tool(tool).name, customer_id)]
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip('"')) from None
    else:
        results = run_all_tools(ctx, customer_id)
    return {
        "customer_id": customer_id,
        "as_of": state["as_of"].isoformat(),
        "results": [
            {**r.to_dict(), "model_text": r.to_model_text(),
             "payload": _jsonable(r.payload)}
            for r in results
        ],
    }


# ------------------------------------------------------------------ agents
@app.get("/agents", tags=["agents"])
def agents() -> dict:
    from .agents import all_agents

    return {
        "agents": [
            {"name": a.name, "question_fa": a.question_fa, "role_fa": a.role_fa,
             "tools": list(a.tools), "forbidden_fa": a.forbidden_fa}
            for a in all_agents()
        ]
    }


@app.get("/customers/{customer_id}/meeting/plan", tags=["agents"])
def meeting_plan(customer_id: str, as_of: date | None = None) -> dict:
    """Which analysts this file needs and what a meeting would cost — **free**.

    Deliberately a GET while holding the meeting is a POST: the routing decision
    costs nothing and should be refreshable, the meeting costs two model calls per
    woken agent and must not be billed by a browser reload.
    """
    from .agents import route

    state = _ctx(as_of, customer_id)
    return route(state["ctx"], customer_id, state["signals"].signals).to_dict()


@app.post("/customers/{customer_id}/meeting", tags=["agents"])
def hold_meeting_endpoint(customer_id: str, payload: MeetingIn | None = None,
                          as_of: date | None = None) -> dict:
    """Run the woken agents and return the agenda. Costs model calls — hence POST."""
    from .agents import hold_meeting

    state = _ctx(as_of, customer_id)
    meet = hold_meeting(
        state["ctx"], customer_id, state["signals"].signals,
        only_agents=(payload.agents if payload else None),
    )
    return {**meet.to_dict(), "brief_fa": meet.to_brief_fa()}


# ------------------------------------------------------------- calibration
@app.get("/calibration", tags=["system"])
def calibration(as_of: date | None = None) -> dict:
    report = _state(as_of)["calibration"]
    return {
        "as_of": report.as_of.isoformat(),
        "population": report.population,
        "rows": report.rows.to_dict(orient="records"),
        "failures": report.failures["detector"].tolist(),
        "insufficient": report.insufficient["detector"].tolist(),
    }


# ---------------------------------------------------------------- feedback
@app.post("/feedback", tags=["feedback"])
def post_feedback(payload: FeedbackIn, as_of: date | None = None) -> dict:
    """Record a manager decision. This is the only endpoint that writes."""
    state = _state(as_of, stage="full")
    detectors = payload.detectors
    if not detectors:
        action = next(
            (a for a in state["queue"].actions if a.customer_id == payload.customer_id),
            None,
        )
        if action is None:
            raise HTTPException(
                400,
                "no action for this customer in the current queue; pass `detectors` "
                "explicitly to attribute the feedback",
            )
        detectors = action.signals

    store = FeedbackStore(settings=get_settings())
    event = store.record(
        payload.customer_id, payload.decision, detectors,
        as_of=state["as_of"], rank=payload.rank, bucket=payload.bucket,
        reason_fa=payload.reason_fa, actor=payload.actor,
    )
    _invalidate()      # the next queue must be ranked with this verdict included
    return {"recorded": event.to_dict(), "weights": detector_weights(store)}


@app.get("/feedback", tags=["feedback"])
def get_feedback() -> dict:
    store = FeedbackStore(settings=get_settings())
    return {
        "events": len(store.events()),
        "detector_stats": detector_stats(store).to_dict(orient="records"),
        "weights": detector_weights(store),
    }


@app.get("/report", response_class=HTMLResponse, tags=["queue"])
def report(as_of: date | None = None, top: int = Query(25, ge=1, le=200)) -> HTMLResponse:
    """The same artifact the CLI writes, served inline."""
    from .report import render_html

    state = _state(as_of, stage="full", top_n=top)
    return HTMLResponse(render_html(
        state["queue"], state["ctx"], state["quadrants"],
        settings=state["settings"], calibration=state["calibration"], top_n=top,
    ))
