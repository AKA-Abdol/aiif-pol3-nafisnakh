"""One account's full action, computed on demand and cached to disk (PLAN §3.7).

The daily queue is built for the *top* of the book: :func:`build_actions` ranks
every customer, then draws the line at ``top_n``. That is the right economics for
the morning list — one drafting call per row, and the manager only works the top
— but it leaves a hole the 360° page falls straight into. Open an account sitting
at rank 180 and there is no action for it, no relationship synthesis, and nothing
on the page saying what to do next. Every input is already there; nobody paid the
two calls.

This module pays them, for exactly one account, on an explicit click:

1. **relationship synthesis** — one call, skipped entirely when the account
   already has a row (a queue build in this process put one on the context, or a
   previous click left one on disk);
2. **action drafting** — one call, plus at most one validation retry, exactly as
   the queue does. Same validator, same drop-on-unsupported-numeral rule, same
   credit and investigation gates. Nothing here is a second implementation of
   the queue's logic: it is :func:`build_actions` with ``only=[customer_id]``.

**The result is cached to disk** at ``cache/actions/<as_of>/<customer_id>.json``
and served from there afterwards, so the second click is free — and so is the
first click after a server restart, which the in-memory run cache cannot do.

Two caches are involved and they answer different questions. The one in
:mod:`nafisnakh.llm.client` caches a *model response* keyed on the prompt: it
makes the model call free but still pays the pipeline work around it. This one
caches the *finished action*, so a repeat costs nothing at all.

**Staleness is a fingerprint, not a TTL.** An action is a function of the model
that wrote it and the detector weights that ranked it, and ``POST /feedback``
moves the weights. Both go into a fingerprint stored beside the payload; when the
current fingerprint differs the entry is a miss and the action is recomputed.
Nothing is deleted — a superseded file is simply never read again, which leaves a
record of what the manager was actually shown on the day.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Settings
from ..io import schema as S
from ..llm.client import LLMUnavailable, get_client
from ..metrics.base import jsonable
from .aggregator import build_actions

log = logging.getLogger(__name__)

#: Bumped when the shape of the payload changes, so old files read as misses
#: rather than as a KeyError somewhere in the frontend.
CACHE_VERSION = "1"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


# --------------------------------------------------------------------- cache
def fingerprint(settings: Settings, weights: dict[str, float] | None) -> str:
    """What has to be equal for a cached action to still be the right answer.

    The model, because a different one writes different Persian; the detector
    weights, because feedback moves them and they decide both the ranking and
    the priority band printed on the card.
    """
    payload = "|".join([
        CACHE_VERSION,
        settings.active_model,
        json.dumps(weights or {}, sort_keys=True),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def cache_path(settings: Settings, as_of: date, customer_id: str) -> Path:
    """``cache/actions/<as_of>/<customer_id>.json``.

    The id reaches this function from a URL path segment, so it is checked
    against a conservative pattern rather than trusted: an id that does not match
    is hashed instead of being interpolated, and cannot walk out of the
    directory.
    """
    name = customer_id if _SAFE_ID.match(customer_id) else hashlib.sha256(
        customer_id.encode()
    ).hexdigest()[:32]
    return Path(settings.cache_dir) / "actions" / as_of.isoformat() / f"{name}.json"


def read_cached(
    settings: Settings, as_of: date, customer_id: str,
    *, weights: dict[str, float] | None = None,
) -> dict | None:
    """A previously computed action, or ``None`` for a miss or a stale entry."""
    path = cache_path(settings, as_of, customer_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("corrupt on-demand action cache at %s — recomputing", path)
        return None
    want = fingerprint(settings, weights)
    if payload.get("fingerprint") != want:
        log.info(
            "cached action for %s is stale (model or feedback weights moved)",
            customer_id,
        )
        return None
    return payload


def write_cached(settings: Settings, as_of: date, customer_id: str,
                 payload: dict) -> Path:
    path = cache_path(settings, as_of, customer_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# ------------------------------------------------------------------ counting
class _CountingClient:
    """The shared client, wrapped so the answer can say what the click cost.

    Only :meth:`structured` is intercepted; everything else falls through, so the
    aggregator and the relationship block cannot tell the difference. A response
    served from the prompt cache still counts as a call *made* — it is reported
    separately by its ``source``, which is what distinguishes "we spent money"
    from "we spent a disk read".
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0
        self.sources: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def structured(self, *args, **kwargs):
        result = self._inner.structured(*args, **kwargs)
        self.calls += 1
        self.sources.append(result.source)
        return result


# ----------------------------------------------------------- relationship row
def _row_from_table(ctx, customer_id: str) -> dict | None:
    table = ctx.tables.get("relationship")
    if table is None or not len(table) or customer_id not in table.index:
        return None
    return {k: jsonable(v) for k, v in table.loc[customer_id].to_dict().items()}


def _merge_relationship(ctx, previous: pd.DataFrame | None) -> None:
    """Put back the rows an ``only=`` synthesis dropped.

    :func:`~nafisnakh.llm.blocks.relationship.attach_to_context` *assigns*
    ``ctx.tables["relationship"]``, so running it for one customer replaces the
    whole table. On a one-shot CLI run that is harmless. On the shared API
    context it is not: clicking the button for account B would blank the row a
    queue build had already paid for on account A, and the dossier panel for A
    would go back to saying "not computed yet".
    """
    fresh = ctx.tables.get("relationship")
    if previous is None or not len(previous):
        return
    if fresh is None or not len(fresh):
        ctx.tables["relationship"] = previous
        return
    kept = previous.loc[~previous.index.isin(fresh.index)]
    ctx.tables["relationship"] = pd.concat([kept, fresh]) if len(kept) else fresh


def _synthesise_relationship(ctx, run, quadrants, customer_id, *, client,
                             allow_offline: bool) -> dict | None:
    from ..llm.blocks.relationship import attach_to_context as attach_relationship

    previous = ctx.tables.get("relationship")
    try:
        attach_relationship(
            ctx, run, quadrants, client=client, only=[customer_id],
            allow_rules=allow_offline,
        )
    except LLMUnavailable:
        log.warning("no LLM and offline disabled — no relationship for %s", customer_id)
        _merge_relationship(ctx, previous)
        return None
    row = _row_from_table(ctx, customer_id)
    _merge_relationship(ctx, previous)
    return row


# ------------------------------------------------------------------ payloads
def _payload(
    settings: Settings, as_of: date, customer_id: str, *,
    weights: dict[str, float] | None,
    action: dict | None,
    relationship: dict | None,
    dropped: list | None,
    signals: list[str],
    n_llm_calls: int,
    call_sources: list[str],
) -> dict:
    """The one shape written to disk, whoever produced the action."""
    return {
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "fingerprint": fingerprint(settings, weights),
        "cache_version": CACHE_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.active_model,
        "action": jsonable(action) if action else None,
        "relationship": relationship,
        "dropped": jsonable(dropped or []),
        "signals": signals,
        "n_llm_calls": n_llm_calls,
        "call_sources": call_sources,
    }


def adopt_queue_action(
    settings: Settings,
    as_of: date,
    customer_id: str,
    *,
    action: dict,
    relationship: dict | None = None,
    dropped: list | None = None,
    signals: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """Take over an action the daily queue already built, and cache it.

    Without this the two paths never meet. The queue builds its actions into an
    in-memory ``ActionQueue``; nothing wrote them where the 360° page looks. So
    the accounts *most* likely to be opened — the ones in today's top ten, which
    is the whole point of the list — were exactly the ones whose page offered a
    build button for work that had already been paid for, and pressing it paid
    again for the same answer.

    Adopting costs nothing: the action is already written, this only records it
    under the fingerprint so that both the page and a later restart can find it.
    ``n_llm_calls`` is 0 because *this* step made no calls; what the queue spent
    is the queue's own business.
    """
    payload = _payload(
        settings, as_of, customer_id, weights=weights, action=action,
        relationship=relationship, dropped=dropped, signals=signals or [],
        n_llm_calls=0, call_sources=[],
    )
    write_cached(settings, as_of, customer_id, payload)
    return payload


# ------------------------------------------------------------------- the call
def action_for_customer(
    ctx,
    run,
    quadrants,
    customer_id: str,
    *,
    settings: Settings | None = None,
    weights: dict[str, float] | None = None,
    client=None,
    allow_offline: bool = True,
    refresh: bool = False,
) -> dict:
    """The full action for one account: cached, or computed and then cached.

    ``refresh=True`` recomputes and overwrites even on a fresh cache hit — the
    escape hatch for "the model wrote something wrong, try again". It is the only
    path that can pay twice for the same account, so it is never the default and
    the HTTP layer puts it behind an explicit flag.

    Returns a JSON-ready dict; see :data:`CACHE_VERSION` for what pins its shape.
    """
    st = settings or ctx.settings
    weights = weights if weights is not None else run.weights
    signals = run.by_customer().get(customer_id, [])

    if not refresh:
        hit = read_cached(st, ctx.as_of, customer_id, weights=weights)
        if hit is not None:
            # Re-seat the relationship row on the shared context so the dossier
            # endpoint finds it too, without paying for it a second time.
            if hit.get("relationship") and _row_from_table(ctx, customer_id) is None:
                _seat_relationship(ctx, customer_id, hit["relationship"])
            return {**hit, "served_from": "cache"}

    counting = _CountingClient(client or get_client(st))

    relationship = _row_from_table(ctx, customer_id)
    if relationship is None or refresh:
        relationship = _synthesise_relationship(
            ctx, run, quadrants, customer_id,
            client=counting, allow_offline=allow_offline,
        ) or relationship

    queue = build_actions(
        ctx, run, quadrants, client=counting, only=[customer_id],
        allow_offline=allow_offline, weights=weights,
    )
    action = queue.actions[0].to_dict() if queue.actions else None
    dropped = [d for d in queue.dropped if d.get("customer_id") == customer_id]

    payload = _payload(
        st, ctx.as_of, customer_id, weights=weights, action=action,
        relationship=relationship, dropped=dropped,
        signals=[s.detector for s in signals],
        n_llm_calls=counting.calls, call_sources=counting.sources,
    )
    write_cached(st, ctx.as_of, customer_id, payload)
    return {**payload, "served_from": "computed"}


def _seat_relationship(ctx, customer_id: str, row: dict) -> None:
    """Put a cached relationship row back onto the context's table.

    Without this, a cached action would answer the button but leave the dossier's
    own relationship panel empty until the process happened to rebuild a queue —
    two views of the same customer disagreeing about whether the synthesis
    exists. No evidence is emitted here: the claim behind this row was registered
    when it was first computed, and re-emitting would mint a second id for the
    same fact.
    """
    frame = pd.DataFrame([{S.CUSTOMER_ID: customer_id, **row}]).set_index(S.CUSTOMER_ID)
    existing = ctx.tables.get("relationship")
    ctx.tables["relationship"] = (
        pd.concat([existing.loc[~existing.index.isin(frame.index)], frame])
        if existing is not None and len(existing) else frame
    )


def has_cached_action(settings: Settings, as_of: date, customer_id: str,
                      *, weights: dict[str, float] | None = None) -> bool:
    """Whether a click would be free. Used by the free GET so the page can say so."""
    return read_cached(settings, as_of, customer_id, weights=weights) is not None


def cached_customers(settings: Settings, as_of: date) -> list[str]:
    """Which accounts already have an action on disk for this ``as_of``."""
    directory = Path(settings.cache_dir) / "actions" / as_of.isoformat()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))
