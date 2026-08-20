"""HTTP surface (PLAN §4, Phase 2; Q2 said "convertible to an API later").

The API deliberately adds **no logic of its own**. Every endpoint is a thin
projection of something the library already computes, so there is no second
implementation of the ranking, the buckets or the validation that could drift
away from the CLI's.

Two design points:

* **The pipeline is computed once per ``as_of`` and cached in-process.** A run
  is a few seconds and the result is immutable for a given anchor, so serving it
  per request would be waste, and recomputing mid-session would let two callers
  see two different queues for the same date.
* **Feedback is the only write.** ``POST /feedback`` appends a manager decision
  and invalidates the cache, because the next queue should be ranked with the
  verdict that was just given. Nothing else mutates state.

Run it with:

```bash
uvicorn nafisnakh.api:app --reload
```
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .config import get_settings
from .feedback import FeedbackStore, detector_stats, detector_weights
from .llm.graph import run_pipeline

log = logging.getLogger(__name__)

app = FastAPI(
    title="Nafis Nakh — AI B2B CRM Copilot",
    version="0.1.0",
    description=(
        "صف اقدام مبتنی بر شواهد برای مدیر فروش. هر اقدام به شناسه‌های شاهد ارجاع "
        "می‌دهد و هیچ عددی خارج از شواهد در متن نمی‌آید."
    ),
)

_CACHE: dict[str, Any] = {}


def _state(as_of: date | None = None, top_n: int | None = None):
    st = get_settings()
    key = f"{(as_of or st.as_of).isoformat()}|{top_n or st.top_n_actions}"
    if key not in _CACHE:
        log.info("computing pipeline for %s", key)
        _CACHE[key] = run_pipeline(
            settings=st, as_of=as_of or st.as_of,
            top_n=top_n or st.top_n_actions, use_graph=False,
        )
    return _CACHE[key]


def _invalidate() -> None:
    _CACHE.clear()


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


class EvidenceOut(BaseModel):
    id: str
    customer_id: str
    kind: str
    claim_fa: str
    value: Any
    unit: str | None
    as_of: str
    source_rows: str
    provenance: dict
    confidence: float


class FeedbackIn(BaseModel):
    customer_id: str
    decision: Literal["done", "dismissed", "snoozed", "wrong"]
    detectors: list[str] = Field(default_factory=list)
    reason_fa: str | None = None
    actor: str | None = None
    rank: int | None = None
    bucket: str | None = None


# ------------------------------------------------------------------ endpoints
@app.get("/health")
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


@app.get("/summary")
def summary(as_of: date | None = None) -> dict:
    state = _state(as_of)
    run, queue = state["signals"], state["queue"]
    return {
        "as_of": state["as_of"].isoformat(),
        "customers": len(state["ctx"].population),
        "signals": len(run.signals),
        "triggered_customers": len(run.triggered_customers()),
        "quadrants": state["quadrants"].counts(),
        "actions": len(queue.actions),
        "dropped_in_validation": len(queue.dropped),
        "evidence": len(state["ctx"].evidence),
        "feedback_weights": state.get("weights", {}),
    }


@app.get("/actions", response_model=list[ActionOut])
def actions(
    as_of: date | None = None,
    bucket: str | None = Query(None, pattern="^(grow|protect|fix|reduce)$"),
    priority: str | None = None,
    limit: int = Query(25, ge=1, le=200),
) -> list[ActionOut]:
    queue = _state(as_of, top_n=limit)["queue"]
    rows = queue.actions
    if bucket:
        rows = [a for a in rows if a.bucket == bucket]
    if priority:
        rows = [a for a in rows if a.priority == priority]
    return [ActionOut(**a.to_dict()) for a in rows[:limit]]


@app.get("/customers/{customer_id}")
def customer(customer_id: str, as_of: date | None = None) -> dict:
    state = _state(as_of)
    ctx, run = state["ctx"], state["signals"]
    signals = run.by_customer().get(customer_id)
    quadrants = state["quadrants"]
    if signals is None and customer_id not in quadrants.table.index:
        raise HTTPException(404, f"customer {customer_id} not found at this as_of")

    relationship = ctx.tables.get("relationship")
    rel = None
    if relationship is not None and len(relationship) and customer_id in relationship.index:
        rel = {
            k: (v.tolist() if hasattr(v, "tolist") else v)
            for k, v in relationship.loc[customer_id].to_dict().items()
        }
    return {
        "customer_id": customer_id,
        "bucket": quadrants.bucket_of(customer_id),
        "bucket_reason_fa": (
            quadrants.table.loc[customer_id, "bucket_reason_fa"]
            if customer_id in quadrants.table.index else None
        ),
        "signals": [s.to_dict() for s in (signals or [])],
        "evidence": [e.to_dict() for e in ctx.evidence.for_customer(customer_id)],
        "relationship": rel,
        "action": next(
            (a.to_dict() for a in state["queue"].actions if a.customer_id == customer_id),
            None,
        ),
    }


@app.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def evidence(evidence_id: str, as_of: date | None = None) -> EvidenceOut:
    ev = _state(as_of)["ctx"].evidence.get(evidence_id)
    if ev is None:
        raise HTTPException(404, f"evidence {evidence_id} not found")
    return EvidenceOut(**ev.to_dict())


@app.get("/calibration")
def calibration(as_of: date | None = None) -> dict:
    report = _state(as_of)["calibration"]
    return {
        "as_of": report.as_of.isoformat(),
        "population": report.population,
        "rows": report.rows.to_dict(orient="records"),
        "failures": report.failures["detector"].tolist(),
    }


@app.post("/feedback")
def post_feedback(payload: FeedbackIn, as_of: date | None = None) -> dict:
    """Record a manager decision. This is the only endpoint that writes."""
    state = _state(as_of)
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


@app.get("/feedback")
def get_feedback() -> dict:
    store = FeedbackStore(settings=get_settings())
    stats = detector_stats(store)
    return {
        "events": len(store.events()),
        "detector_stats": stats.to_dict(orient="records"),
        "weights": detector_weights(store),
    }


@app.get("/report", response_class=None)
def report(as_of: date | None = None, top: int = Query(25, ge=1, le=200)):
    """The same artifact the CLI writes, served inline."""
    from fastapi.responses import HTMLResponse

    from .report import render_html

    state = _state(as_of, top_n=top)
    return HTMLResponse(render_html(
        state["queue"], state["ctx"], state["quadrants"],
        settings=state["settings"], calibration=state["calibration"], top_n=top,
    ))
