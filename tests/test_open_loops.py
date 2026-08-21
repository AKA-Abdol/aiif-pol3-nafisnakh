"""RFM and the four open-loop detectors (#24–#27).

The point of these tests is not that the numbers are what they are today — it is
that each detector's *defining absence* really is absent in the source rows, and
that the drill-down for each new evidence returns real records.
"""

from datetime import date

import pandas as pd
import pytest

from nafisnakh.core.evidence import resolve
from nafisnakh.core.spine import visible
from nafisnakh.io import schema as S
from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.metrics.rfm import SEGMENT_FA, segment_of
from nafisnakh.signals.engine import calibrate, run_detectors

AS_OF = date(2021, 6, 30)
NEW_DETECTORS = [
    "dev_sample_ready_no_offer",
    "dev_rejected_uncommunicated",
    "crm_promise_outstanding",
    "offer_negotiation_stalled",
]


@pytest.fixture(scope="module")
def ctx(ds):
    return build_metrics(make_context(ds, as_of=AS_OF))


@pytest.fixture(scope="module")
def run(ctx):
    return run_detectors(ctx)


# ------------------------------------------------------------------------ RFM
def test_rfm_scores_are_quintiles_of_the_rank(ctx):
    rfm = ctx.table("rfm")
    for col in ("r_score", "f_score", "m_score"):
        assert set(rfm[col].unique()) <= {1, 2, 3, 4, 5}, col
    # monetary has no mass of ties, so its quintiles must come out even
    counts = rfm["m_score"].value_counts()
    assert counts.max() - counts.min() <= 2


def test_rfm_recency_agrees_with_cadence(ctx):
    """Two tables, one fact. RFM ranks it inside the book and cadence measures it
    against the customer's own rhythm, but 'days since the last purchase' has to
    be the same number in both or one of them is reading the wrong rows."""
    rfm, cad = ctx.table("rfm"), ctx.table("cadence")
    both = rfm.index.intersection(cad.index)
    assert len(both) > 400
    assert (rfm.loc[both, "recency_days"] == cad.loc[both, "days_since_last"]).all()


def test_rfm_recency_ranks_the_right_way_round(ctx):
    """Small recency is *good*. Getting the direction wrong is a silent bug that
    would recommend the campaign to exactly the wrong half of the book."""
    rfm = ctx.table("rfm")
    top = rfm.loc[rfm["r_score"] == 5, "recency_days"].max()
    bottom = rfm.loc[rfm["r_score"] == 1, "recency_days"].min()
    assert top < bottom


def test_rfm_segments_are_named_and_cover_the_book(ctx):
    rfm = ctx.table("rfm")
    assert rfm["rfm_segment"].isin(SEGMENT_FA).all()
    assert rfm["rfm_segment_fa"].notna().all()


def test_segment_boundaries():
    assert segment_of(5, 5, 5) == "champion"
    assert segment_of(1, 5, 5) == "at_risk"
    assert segment_of(1, 1, 1) == "hibernating"
    assert segment_of(5, 1, 1) == "small_or_new"
    assert segment_of(5, 3, 3) == "promising"
    assert segment_of(3, 3, 3) == "needs_attention"


# ------------------------------------------------------------------ open loops
def test_approved_sample_loop_really_has_no_later_offer(ctx, ds):
    """The defining absence, checked against the sheet rather than the table."""
    loops = ctx.table("open_loops")
    dev = visible(ds.dev_requests, AS_OF).set_index(S.D_ID)
    off = visible(ds.offers, AS_OF)
    off = off.loc[pd.to_datetime(off[S.O_DATE], errors="coerce") <= pd.Timestamp(AS_OF)]
    last_offer = off.assign(_d=pd.to_datetime(off[S.O_DATE])).groupby(S.CUSTOMER_ID)["_d"].max()

    checked = 0
    for cid, ids in loops["dev_approved_open_ids"].items():
        for rid in ids:
            row = dev.loc[rid]
            assert row[S.D_STATUS] == S.D_STATUS_APPROVED
            decided = pd.Timestamp(row[S.D_DECISION_AT])
            latest = last_offer.get(cid)
            assert latest is None or pd.isna(latest) or latest <= decided, rid
            checked += 1
    assert checked > 10


def test_rejected_loop_really_has_no_later_crm_contact(ctx, ds):
    loops = ctx.table("open_loops")
    dev = visible(ds.dev_requests, AS_OF).set_index(S.D_ID)
    crm = visible(ds.crm_latest, AS_OF)
    crm = crm.loc[pd.to_datetime(crm[S.X_EVENT_TIME], errors="coerce") <= pd.Timestamp(AS_OF)]
    last_crm = crm.assign(_d=pd.to_datetime(crm[S.X_EVENT_TIME])).groupby(S.CUSTOMER_ID)["_d"].max()

    checked = 0
    for cid, ids in loops["dev_rejected_unspoken_ids"].items():
        for rid in ids:
            row = dev.loc[rid]
            assert row[S.D_STATUS] == S.D_STATUS_REJECTED
            latest = last_crm.get(cid)
            assert latest is None or pd.isna(latest) or latest <= pd.Timestamp(row[S.D_DECISION_AT])
            checked += 1
    assert checked > 10


def test_abandoned_offers_obey_rule_4_not_the_result_column(ctx, ds):
    """An offer is open if its decision was not *knowable* at ``as_of``.

    46 of the 403 open offers at the anchor already carry a ``Result`` in the raw
    sheet. Reading that column would hide them; reading
    ``Decision_Available_At`` keeps them open, which is what the sales manager
    actually saw that day.
    """
    loops = ctx.table("open_loops")
    off = visible(ds.offers, AS_OF).set_index(S.O_ID)
    cited = [oid for ids in loops["offers_abandoned_ids"] for oid in ids]
    assert len(cited) > 100

    stamps = pd.to_datetime(off.loc[cited, S.O_DECISION_AVAILABLE_AT], errors="coerce")
    assert (stamps.isna() | (stamps > pd.Timestamp(AS_OF))).all()

    # and the interesting subset genuinely exists
    already_decided = off.loc[cited, S.O_RESULT].notna().sum()
    assert already_decided > 0

    ages = (pd.Timestamp(AS_OF) - pd.to_datetime(off.loc[cited, S.O_DATE])).dt.days
    validity = pd.to_numeric(off.loc[cited, S.O_VALIDITY_DAYS], errors="coerce")
    assert (ages > validity).all()


def test_next_action_loop_reads_only_the_latest_interaction(ctx, ds):
    """A promise superseded by a later conversation is history, not a loop."""
    loops = ctx.table("open_loops")
    crm = visible(ds.crm_latest, AS_OF)
    crm = crm.loc[pd.to_datetime(crm[S.X_EVENT_TIME], errors="coerce") <= pd.Timestamp(AS_OF)]
    latest = (
        crm.assign(_d=pd.to_datetime(crm[S.X_EVENT_TIME]))
        .sort_values("_d").groupby(S.CUSTOMER_ID).tail(1).set_index(S.CUSTOMER_ID)
    )
    open_rows = loops.loc[loops["next_action_open"].fillna(False)]
    assert len(open_rows) > 100
    for cid, r in open_rows.iterrows():
        assert r.next_action_id == latest.loc[cid, S.X_ID]
        assert r.next_action_type != "بدون اقدام"


def test_untraceable_next_actions_are_marked_unfalsifiable(ctx):
    """Nothing in this workbook records a phone call that produced nothing, so
    the signal must say 'no record', never 'it did not happen'."""
    loops = ctx.table("open_loops")
    phone = loops.loc[loops["next_action_type"] == "پیگیری تلفنی"]
    assert len(phone) > 50
    assert not phone["next_action_trace_exists"].any()
    meeting = loops.loc[loops["next_action_type"] == "جلسه قیمت"]
    assert meeting["next_action_trace_exists"].all()


# -------------------------------------------------------------------- signals
def test_all_four_open_loop_detectors_fire(run):
    fired = {s.detector for s in run.signals}
    for name in NEW_DETECTORS:
        assert name in fired, name


def test_open_loop_detectors_calibrate(run, ctx):
    report = calibrate(run, ctx)
    rows = report.rows.set_index("detector")
    for name in NEW_DETECTORS:
        assert rows.loc[name, "status"] == "ok", rows.loc[name].to_dict()


def test_every_open_loop_evidence_resolves_to_real_rows(ctx, ds):
    """Step 1's contract applied to step 2: a claim a customer may be shown has
    to be openable down to the records it rests on."""
    slugs = ("loop-sample", "loop-rejection", "loop-nextaction", "loop-offer", "rfm")
    seen = {s: 0 for s in slugs}
    for ev in ctx.evidence.all():
        slug = ev.id[len(f"EV-{ev.customer_id}-"):].rsplit("-", 1)[0]
        if slug not in seen:
            continue
        assert ev.is_resolvable, ev.id
        rows = resolve(ev, ds)
        assert len(rows) > 0, ev.id
        seen[slug] += 1
    assert all(v > 0 for v in seen.values()), seen


def test_stalled_offer_signal_makes_no_causal_price_claim(run):
    """PLAN §1.2 — the offers sheet has no association with outcome, so an
    abandoned negotiation may never be reported as a rejected price.

    The outcome enum is matched as whole words: ``رد`` is a substring of
    ``دارد``, and a naive ``in`` test fails every well-formed headline.
    """
    import re

    outcome_words = re.compile(r"(?<!\w)(رد|قبول|منقضی‌شده)(?!\w)")
    hits = [s for s in run.signals if s.detector == "offer_negotiation_stalled"]
    assert hits
    for s in hits:
        assert "§1.2" in s.detail["caveat"]
        assert not outcome_words.search(s.headline_fa), s.headline_fa


def test_open_loop_stakes_declare_where_the_money_came_from(run):
    allowed = {"peer_family_spend", "own_family_revenue",
               "own_typical_order", "annual_revenue_share"}
    for s in run.signals:
        if s.detector in NEW_DETECTORS:
            assert s.detail["stake_basis"] in allowed, s.id


# ------------------------------------------------ detector #28 fixture coverage
def test_fixture_lab_escape_is_preemptive_and_alone(ds):
    """FIX-021 proves the preemptive half of #28: the lab failed the lot six days
    before the purchase, we shipped it, and nobody has complained yet."""
    from nafisnakh.eval.fixture import LAB_REJECTED_LOT, build_fixture
    from nafisnakh.metrics.base import build_metrics, make_context

    fx = build_fixture()
    ctx = build_metrics(make_context(fx.dataset, as_of=fx.as_of))
    hits = [s for s in run_detectors(ctx).signals
            if s.detector == "lab_rejected_lot_shipped"]
    assert len(hits) == 1
    s = hits[0]
    assert s.customer_id == "FIX-021"
    assert s.detail["preemptive"] is True and s.detail["unflagged_lines"] == 1

    lab = fx.dataset.frames[S.S_LOT_QUALITY]
    rejected = lab.loc[lab[S.Q_RESULT] == S.Q_RESULT_REJECTED]
    assert len(rejected) == 1
    assert rejected.iloc[0][S.LOT_ID] == LAB_REJECTED_LOT
