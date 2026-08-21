"""The HTTP surface.

Two things these tests protect, beyond "the routes answer":

* **The API adds no logic.** Every endpoint has to agree with the library
  function behind it, or there are two implementations of the same rule and one
  of them will drift.
* **Nothing that spends money is a GET.** A browser refresh must not bill the
  user, so holding a meeting is a POST and the routing plan — which costs
  nothing — is the GET.
"""

import pytest

fastapi = pytest.importorskip("fastapi", reason="the `api` extra is not installed")

from fastapi.testclient import TestClient          # noqa: E402

from nafisnakh.api import app                       # noqa: E402

BUSY = "C_126481"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health_reports_the_anchor_and_the_model(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["as_of"] == "2021-06-30"
    assert body["llm_model"]


def test_summary_agrees_with_the_library(client, ds):
    """If these two ever disagree, the API has grown logic of its own."""
    from datetime import date

    from nafisnakh.metrics.base import build_metrics, make_context

    body = client.get("/summary").json()
    ctx = build_metrics(make_context(ds, as_of=date(2021, 6, 30)))
    assert body["customers"] == len(ctx.population)
    assert body["detectors"] == 28
    assert sum(body["quadrants"].values()) == body["customers"]


def test_customer_list_filters_and_carries_the_new_tables(client):
    body = client.get("/customers", params={"limit": 5, "segment": "A"}).json()
    assert body["customers"]
    for row in body["customers"]:
        assert row["segment"] == "A"
        assert row["rfm_cell"] and row["rfm_segment_fa"]
        assert row["open_loops"] is not None


def test_customer_detail_has_everything_the_page_is_built_from(client):
    body = client.get(f"/customers/{BUSY}").json()
    for key in ("bucket", "rfm", "open_loops", "payment", "quality",
                "signals", "evidence"):
        assert body[key] is not None, key
    assert body["signals"] and body["evidence"]


def test_unknown_customer_is_404_not_an_empty_page(client):
    assert client.get("/customers/C_NOPE").status_code == 404
    assert client.get("/customers/C_NOPE/page").status_code == 404
    assert client.get("/customers/C_NOPE/meeting/plan").status_code == 404


def test_evidence_carries_its_locator_over_the_wire(client):
    body = client.get(f"/customers/{BUSY}").json()
    ev = next(e for e in body["evidence"] if e["locator"])
    detail = client.get(f"/evidence/{ev['id']}").json()
    assert detail["locator"] == ev["locator"]


def test_evidence_rows_returns_the_actual_records(client):
    """The endpoint the whole evidence contract exists for."""
    body = client.get(f"/evidence/EV-{BUSY}-loop-offer-001/rows",
                      params={"limit": 3}).json()
    assert body["n_rows"] > 0
    assert body["rows"] and len(body["rows"]) <= 3
    assert "Offer_ID" in body["columns"]
    # rule #4 on the drill-down: nothing dated after the claim's as_of
    for row in body["rows"]:
        assert row["Offer_Date"] <= body["as_of"]


def test_missing_evidence_is_404(client):
    assert client.get("/evidence/EV-NOPE").status_code == 404
    assert client.get("/evidence/EV-NOPE/rows").status_code == 404


def test_tool_catalogue_matches_the_registry(client):
    from nafisnakh.tools import all_tools

    names = {t["name"] for t in client.get("/tools").json()["tools"]}
    assert names == {t.name for t in all_tools()}


def test_customer_tools_return_claims_and_ids(client):
    body = client.get(f"/customers/{BUSY}/tools",
                      params={"tool": "get_payment_state"}).json()
    result = body["results"][0]
    assert result["evidence_ids"] and result["claims"]
    assert "ابزار: get_payment_state" in result["model_text"]


def test_unknown_tool_is_404(client):
    assert client.get(f"/customers/{BUSY}/tools",
                      params={"tool": "get_nothing"}).status_code == 404


def test_agent_roster_matches_the_registry(client):
    from nafisnakh.agents import all_agents

    names = {a["name"] for a in client.get("/agents").json()["agents"]}
    assert names == {a.name for a in all_agents()}


def test_meeting_plan_is_free_and_holding_it_is_not(client):
    """The routing decision should be refreshable; the meeting should not be
    billed by a browser reload."""
    plan = client.get(f"/customers/{BUSY}/meeting/plan").json()
    assert plan["routed"] and plan["n_llm_calls"] == 2 * len(plan["routed"])
    assert client.get(f"/customers/{BUSY}/meeting").status_code == 405

    body = client.post(f"/customers/{BUSY}/meeting",
                       json={"agents": ["financial"]}).json()
    assert [f["agent"] for f in body["findings"]] == ["financial"]
    assert "دستور جلسه" in body["brief_fa"]


def test_calibration_reports_every_detector(client):
    body = client.get("/calibration").json()
    assert len(body["rows"]) == 28
    assert body["failures"] == []


def test_the_360_page_is_served_inline_and_is_self_contained(client):
    r = client.get(f"/customers/{BUSY}/page")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "پرونده ۳۶۰ مشتری" in r.text
    assert '<details class="evd"' in r.text
    assert "<script src" not in r.text


def test_feedback_without_attribution_is_refused(client):
    """Feedback that cannot be attributed to a detector teaches the ranking
    nothing, so it is rejected rather than silently stored."""
    r = client.post("/feedback", json={"customer_id": "C_NOPE", "decision": "done"})
    assert r.status_code == 400
