"""The per-account action built on demand, and the disk cache behind it.

Every test here runs the pipeline offline: the stub client below never reaches a
network, so what is exercised is the caching, the fingerprinting and the merge —
not the model.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from nafisnakh.aggregate.aggregator import build_actions
from nafisnakh.aggregate.on_demand import (
    action_for_customer,
    cache_path,
    fingerprint,
    read_cached,
)
from nafisnakh.aggregate.quadrant import assign_quadrants
from nafisnakh.config import get_settings
from nafisnakh.llm.client import LLMResult
from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.signals.engine import priority_score, run_detectors

AS_OF = date(2021, 6, 30)


class StubClient:
    """Always takes the offline path, and counts what was asked of it.

    `structured` is the entire surface the aggregator and the relationship block
    use, so a stub of one method is a complete stand-in — and one that cannot
    accidentally spend money in CI.
    """

    def __init__(self):
        self.calls = 0

    @property
    def available(self) -> bool:
        return False

    def structured(self, system, user, schema, *, fallback=None, use_cache=None):
        self.calls += 1
        assert fallback is not None, "offline path needs a fallback"
        return LLMResult(fallback(), "rules", "rules", "stub")


@pytest.fixture(scope="module")
def pipeline(ds):
    """Metrics → detectors → quadrants. No LLM block: the detectors that need
    `llm_complaints` simply do not fire, which is enough to rank a book."""
    ctx = build_metrics(make_context(ds, as_of=AS_OF))
    run = run_detectors(ctx)
    return {"ctx": ctx, "run": run, "quadrants": assign_quadrants(ctx)}


@pytest.fixture
def tmp_settings(tmp_path):
    return get_settings(cache_dir=tmp_path / "cache", out_dir=tmp_path / "out")


def _ranked(pipeline) -> list[str]:
    st = pipeline["ctx"].settings
    by_customer = pipeline["run"].by_customer()
    return [
        cid for cid, _ in sorted(
            by_customer.items(),
            key=lambda kv: max(priority_score(s, st) for s in kv[1]),
            reverse=True,
        )
    ]


# ----------------------------------------------------------------- the rank fix
def test_only_build_keeps_the_book_position_as_rank(pipeline):
    """An account built alone must not be announced as rank 1 of the book.

    The renumbering pass at the end of `build_actions` exists so a whole-book
    queue reads 1..n with no holes where a draft was dropped. Applied to an
    `only=` build it silently overwrote the very rank the code above it had gone
    out of its way to carry down.
    """
    ranked = _ranked(pipeline)
    assert len(ranked) > 3, "need a book deep enough for this to mean anything"
    target = ranked[3]

    queue = build_actions(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"],
        client=StubClient(), only=[target], allow_offline=True,
    )
    assert queue.actions, "the offline composer always produces a draft"
    assert queue.actions[0].customer_id == target
    assert queue.actions[0].rank == 4


def test_whole_book_build_still_renumbers(pipeline):
    queue = build_actions(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"],
        client=StubClient(), top_n=5, allow_offline=True,
    )
    assert [a.rank for a in queue.actions] == list(range(1, len(queue.actions) + 1))


# -------------------------------------------------------------------- the cache
def test_second_call_is_served_from_disk_and_costs_nothing(pipeline, tmp_settings):
    cid = _ranked(pipeline)[0]

    first_client = StubClient()
    first = action_for_customer(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"], cid,
        settings=tmp_settings, client=first_client,
    )
    assert first["served_from"] == "computed"
    assert first["action"] is not None
    assert first_client.calls > 0

    second_client = StubClient()
    second = action_for_customer(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"], cid,
        settings=tmp_settings, client=second_client,
    )
    assert second["served_from"] == "cache"
    assert second_client.calls == 0, "a cache hit must not touch the client at all"
    assert second["action"] == first["action"]


def test_the_payload_lands_on_disk_as_readable_json(pipeline, tmp_settings):
    cid = _ranked(pipeline)[1]
    action_for_customer(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"], cid,
        settings=tmp_settings, client=StubClient(),
    )
    path = cache_path(tmp_settings, AS_OF, cid)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["customer_id"] == cid
    assert payload["as_of"] == AS_OF.isoformat()
    assert payload["action"]["customer_id"] == cid


def test_moving_the_feedback_weights_invalidates_the_entry(pipeline, tmp_settings):
    cid = _ranked(pipeline)[2]
    action_for_customer(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"], cid,
        settings=tmp_settings, client=StubClient(), weights={},
    )
    assert read_cached(tmp_settings, AS_OF, cid, weights={}) is not None
    # the manager voted; the detector that drove this action is now worth less
    assert read_cached(tmp_settings, AS_OF, cid, weights={"churn_threat_language": 0.5}) is None


def test_fingerprint_moves_with_the_model(tmp_path):
    """A cached action is the text one model wrote; another model is a miss.

    The profile is pinned on both sides because only the `gemini` profile reads
    `llm_model` — under any other profile the override is a documented no-op and
    this test would compare a value with itself.
    """
    base = get_settings(cache_dir=tmp_path, llm_profile="gemini",
                        llm_model="google/gemini-3.7-flash")
    other = get_settings(cache_dir=tmp_path, llm_profile="gemini",
                         llm_model="some/other-model")
    assert base.active_model != other.active_model
    assert fingerprint(base, {}) != fingerprint(other, {})


def test_refresh_pays_again(pipeline, tmp_settings):
    cid = _ranked(pipeline)[0]
    action_for_customer(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"], cid,
        settings=tmp_settings, client=StubClient(),
    )
    client = StubClient()
    again = action_for_customer(
        pipeline["ctx"], pipeline["run"], pipeline["quadrants"], cid,
        settings=tmp_settings, client=client, refresh=True,
    )
    assert again["served_from"] == "computed"
    assert client.calls > 0


def test_a_traversing_id_cannot_escape_the_cache_directory(tmp_settings):
    root = (tmp_settings.cache_dir / "actions" / AS_OF.isoformat()).resolve()
    path = cache_path(tmp_settings, AS_OF, "../../../etc/passwd").resolve()
    assert path.parent == root


# ------------------------------------------------------------- relationship merge
def test_building_one_account_does_not_blank_another(pipeline, tmp_settings):
    """The API shares one context across requests, and `attach_to_context`
    *assigns* the relationship table rather than appending to it."""
    ctx = pipeline["ctx"]
    first, second = _ranked(pipeline)[0], _ranked(pipeline)[1]

    action_for_customer(ctx, pipeline["run"], pipeline["quadrants"], first,
                        settings=tmp_settings, client=StubClient())
    action_for_customer(ctx, pipeline["run"], pipeline["quadrants"], second,
                        settings=tmp_settings, client=StubClient())

    table = ctx.tables.get("relationship")
    assert table is not None
    assert first in table.index, "the first account's synthesis was overwritten"
    assert second in table.index
