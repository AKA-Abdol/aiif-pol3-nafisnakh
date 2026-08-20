"""The evidence-minting tool layer (step 4).

The layer's contract is narrow and worth testing exactly: a tool hands back
Persian claims and evidence ids, every one of those ids resolves to real rows at
or before ``as_of``, an empty answer explains itself, and calling a tool twice
returns the same ids rather than minting the fact again.
"""

from datetime import date

import pandas as pd
import pytest

from nafisnakh.core.evidence import SHEET_DATE_COLUMN, resolve
from nafisnakh.io import schema as S
from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.tools import all_tools, get_tool, run_tool, tool_schemas

AS_OF = date(2021, 6, 30)
RICH = "C_126481"     # dev requests, complaints, CRM, offers, lab records — all present

EXPECTED = {
    "get_dev_requests", "get_complaints", "get_crm_promises", "get_payment_state",
    "get_lab_band_position", "get_market_context", "get_peer_comparison",
    "get_offer_history",
}


@pytest.fixture(scope="module")
def ctx(ds):
    return build_metrics(make_context(ds, as_of=AS_OF))


@pytest.fixture(scope="module")
def results(ctx):
    return {spec.name: run_tool(ctx, spec.name, RICH) for spec in all_tools()}


def test_all_eight_tools_are_registered():
    assert {spec.name for spec in all_tools()} == EXPECTED


def test_every_tool_has_a_persian_description_and_a_schema():
    for spec in all_tools():
        assert spec.description_fa.strip()
        schema = spec.json_schema()
        assert schema["function"]["name"] == spec.name
        assert "customer_id" in schema["function"]["parameters"]["properties"]
    assert len(tool_schemas()) == len(EXPECTED)


def test_unknown_tool_is_refused():
    with pytest.raises(KeyError):
        get_tool("get_something_else")


def test_every_tool_answers_for_a_rich_customer(results):
    for name, r in results.items():
        assert not r.empty, f"{name} returned nothing for {RICH}"
        assert len(r.claims) == len(r.evidence_ids)


def test_every_minted_id_resolves_to_real_rows(ctx, ds, results):
    """The step-1 contract applied to the agent's whole data surface."""
    seen = 0
    for r in results.values():
        for eid in r.evidence_ids:
            ev = ctx.evidence.get(eid)
            assert ev is not None, eid
            assert ev.customer_id == RICH
            assert ev.is_resolvable, eid
            assert len(resolve(ev, ds)) > 0, eid
            seen += 1
    assert seen > 30


def test_no_tool_evidence_reaches_past_as_of(ctx, ds, results):
    for r in results.values():
        for eid in r.evidence_ids:
            ev = ctx.evidence.get(eid)
            col = SHEET_DATE_COLUMN.get((ev.locator or {}).get("sheet"))
            frame = resolve(ev, ds)
            if not col or col not in frame.columns:
                continue
            stamps = pd.to_datetime(frame[col], errors="coerce").dropna()
            assert (stamps <= pd.Timestamp(AS_OF)).all(), eid


def test_the_model_only_ever_sees_claims_and_ids(results):
    """The prompt payload must not contain a raw figure the model could restate.

    Every numeral in ``to_model_text`` has to come from inside a claim that is
    itself an Evidence — which is what ``aggregate/validate.py`` later checks the
    generated text against.
    """
    from nafisnakh.aggregate.validate import strip_identifiers
    from nafisnakh.core.evidence import extract_numerals

    for name, r in results.items():
        stripped = r.to_model_text()
        for claim in r.claims:
            stripped = stripped.replace(claim, "")
        stripped = stripped.replace(r.note_fa, "")
        # identifiers are citations, not numeric claims — the same exemption the
        # validator applies to generated text
        assert not extract_numerals(strip_identifiers(stripped)), (name, stripped)


def test_payload_is_never_part_of_the_model_text(results):
    for r in results.values():
        assert "payload" not in r.to_model_text()
        assert isinstance(r.payload, dict)


def test_calling_a_tool_twice_returns_the_same_ids(ctx):
    """``ctx.emit`` mints a new id per call, so an unmemoised tool would hand the
    agent two ids for one fact and list it twice on the 360° page."""
    before = len(ctx.evidence)
    first = run_tool(ctx, "get_offer_history", RICH)
    again = run_tool(ctx, "get_offer_history", RICH)
    assert first.evidence_ids == again.evidence_ids
    assert len(ctx.evidence) == before or first is again


def test_an_empty_answer_explains_itself(ctx):
    """An agent handed an empty string invents a reason."""
    quiet = next(
        c for c in ctx.population
        if run_tool(ctx, "get_complaints", c).empty
    )
    r = run_tool(ctx, "get_complaints", quiet)
    assert r.empty and r.empty_reason_fa
    assert "موردی یافت نشد" in r.to_model_text()


def test_dev_request_tool_never_reads_the_outcome_column(ctx, ds):
    """``Outcome_Text`` is independent of ``Status`` (χ², p≈0.94) — a request
    marked ``فنی رد`` carries "sample ready" 55 times."""
    r = run_tool(ctx, "get_dev_requests", RICH)
    texts = set(ds.dev_requests[S.D_OUTCOME].dropna().unique())
    blob = " ".join(r.claims)
    for t in texts:
        assert t not in blob


def test_offer_tool_gates_the_result_on_rule_4(ctx):
    """An offer's `Result` is knowable only from `Decision_Available_At`."""
    r = run_tool(ctx, "get_offer_history", RICH)
    unknown = [o for o in r.payload["offers"] if not o["decision_known"]]
    assert unknown, "expected at least one offer with no knowable decision"
    for o in unknown:
        assert o["result"] is None
    blob = " ".join(r.claims)
    assert "هنوز قابل‌دانستن نیست" in blob


def test_complaint_tool_gates_the_resolution_separately(ctx):
    """Rule #4 applies twice: the complaint from `Available_At`, its answer only
    from `Resolution_Available_At`."""
    r = run_tool(ctx, "get_complaints", RICH)
    for c in r.payload["complaints"]:
        if not c["resolution_known"]:
            assert c["fault_verdict"] is None


def test_market_tool_carries_its_coverage_limit(ctx):
    """130 rows over 7 families for 526 customers, only 59 with any Customer_ID —
    handed over without that caveat, an agent reads them as customer signals."""
    r = run_tool(ctx, "get_market_context", RICH)
    assert "آن را به این مشتری نسبت نده" in r.note_fa
    assert r.payload["family"]


def test_lab_tool_describes_and_refuses_to_explain(ctx):
    """Measured across the sheet, the lab values carry no relation to whether a
    line drew a complaint, so the tool may not be used to explain one."""
    r = run_tool(ctx, "get_lab_band_position", RICH)
    assert "توصیف‌اند، نه تبیین" in r.note_fa
    for band in r.payload["bands"].values():
        assert 0.0 <= band["percentile"] <= 100.0


def test_peer_comparison_names_the_cohort_it_compared_against(ctx):
    """"Compared with whom" is the first thing a customer asks about a percentile."""
    r = run_tool(ctx, "get_peer_comparison", RICH)
    assert r.payload["n_peers"] > 0
    assert any("هم‌بخش" in c for c in r.claims)


def test_tools_reuse_metric_evidence_instead_of_minting_it_twice(ctx):
    """`get_payment_state` mints nothing — the payment metrics already emitted
    every one of those claims, and a second id for one fact is a defect."""
    before = len(ctx.evidence)
    ctx.cache.get("tools", {}).pop(("get_payment_state", RICH, ()), None)
    r = run_tool(ctx, "get_payment_state", RICH)
    assert len(ctx.evidence) == before
    assert r.evidence_ids
