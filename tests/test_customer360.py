"""The 360° customer page (step 3).

The page's one promise is that every claim on it opens onto the rows it rests
on. These tests hold it to that: every evidence id printed anywhere must have a
matching anchor, every anchor must carry real workbook rows, and no row may be
dated after the claim's ``as_of``.
"""

import re
from datetime import date

import pandas as pd
import pytest

from nafisnakh.config import get_settings
from nafisnakh.customer360 import (
    _open_loop_kinds,
    build_state,
    render_customer,
    write_customer_page,
)
from nafisnakh.metrics.base import build_metrics, make_context
from nafisnakh.signals.engine import run_detectors

AS_OF = date(2021, 6, 30)
# one account with all four open loops, one with none — the page has to read
# well in both directions, and "we owe you nothing" is also an answer
BUSY = "C_126481"
QUIET = "C_018229"      # five signals, zero open loops
NO_CRM = "C_054737"     # no CRM interaction at all

EV_RE = re.compile(r"EV-[A-Za-z0-9_\-]+")


@pytest.fixture(scope="module")
def state(ds):
    """The pipeline as the page uses it: whole book, no aggregator, no model."""
    from nafisnakh.aggregate.quadrant import assign_quadrants

    ctx = build_metrics(make_context(ds, as_of=AS_OF))
    run = run_detectors(ctx)
    return {"ctx": ctx, "signals": run, "quadrants": assign_quadrants(ctx), "queue": None}


@pytest.fixture(scope="module")
def page(state, settings):
    return render_customer(BUSY, state, settings=settings)


def test_page_is_self_contained(page):
    """It has to open from an email attachment on a phone with no network."""
    assert "<script src" not in page
    assert "https://" not in page.split("<footer>")[0]
    assert "@import" not in page and "cdn" not in page.lower()


def test_every_evidence_id_on_the_page_has_an_anchor(page):
    """A citation that does not open onto anything is decoration."""
    anchors = set(re.findall(r'<details class="evd" id="(EV-[^"]+)"', page))
    assert anchors
    for eid in set(EV_RE.findall(page)):
        assert eid in anchors, f"{eid} is cited but has no expandable block"


def test_every_anchor_carries_real_rows(page):
    assert "این شاهد به هیچ ردیفی نمی‌رسد" not in page
    assert "ردیف‌ها بازیابی نشد" not in page
    counts = [int(n) for n in re.findall(r"(\d+) ردیف منبع", page)]
    assert len(counts) == page.count('<details class="evd"')
    assert all(c > 0 for c in counts)


def test_the_page_only_shows_this_customer(page, state):
    others = {c for c in EV_RE.findall(page)} - {
        e.id for e in state["ctx"].evidence.for_customer(BUSY)
    }
    assert not others, others


def test_rows_are_never_dated_after_as_of(state, ds):
    """Rule #4 on the drill-down, checked on what the page actually renders."""
    from nafisnakh.core.evidence import SHEET_DATE_COLUMN, resolve

    for ev in state["ctx"].evidence.for_customer(BUSY):
        frame = resolve(ev, ds)
        col = SHEET_DATE_COLUMN.get((ev.locator or {}).get("sheet"))
        if not col or col not in frame.columns:
            continue
        stamps = pd.to_datetime(frame[col], errors="coerce").dropna()
        assert (stamps <= pd.Timestamp(AS_OF)).all(), ev.id


def test_open_loops_are_counted_as_kinds_not_saturated(state):
    """`np.bool_ + np.bool_` is logical OR — the naive sum reports 1 of 4 for an
    account with all four loops open."""
    loops = state["ctx"].table("open_loops")
    assert _open_loop_kinds(loops.loc[BUSY]) == 4
    assert _open_loop_kinds(loops.loc[QUIET]) == 0


def test_a_quiet_account_still_renders_and_says_so(state, settings):
    """"We owe this customer nothing right now" is an answer the sales manager
    needs before a meeting, so the closed loops are stated, not omitted."""
    page = render_customer(QUIET, state, settings=settings)
    assert page.count("موردی باز نیست") >= 2
    assert "اقدام بعدی ثبت نکرده است" in page


def test_an_account_with_no_crm_says_that_rather_than_nothing(state, settings):
    page = render_customer(NO_CRM, state, settings=settings)
    assert "تعامل CRM ثبت‌شده‌ای برای این مشتری نیست" in page


def test_without_the_aggregator_the_page_says_so_rather_than_inventing(page):
    assert "--actions" in page
    assert "قدم بعدی:" not in page.split('<div class="sect">چه چیزی')[0].split(
        '<div class="sect">تصمیم'
    )[1]


def test_unknown_customer_is_refused(state, settings):
    with pytest.raises(KeyError):
        render_customer("C_NOT_A_CUSTOMER", state, settings=settings)


def test_page_writes_to_a_named_file(state, settings, tmp_path):
    path = write_customer_page(
        BUSY, state, settings=settings, path=tmp_path / "p.html", max_rows=3
    )
    text = path.read_text(encoding="utf-8")
    assert path.exists() and len(text) > 10_000
    # max_rows is a display cap, never a change to the underlying count
    assert "ردیف دیگر" in text


def test_build_state_never_subsets_the_book(monkeypatch):
    """The bucket threshold is the book's median revenue and RFM is quintiles of
    the book — a one-customer run would render meaningless numbers."""
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr("nafisnakh.llm.graph.run_pipeline", fake)
    build_state(get_settings(), with_actions=True, customer_id=BUSY)
    assert "customers" not in seen and "sample" not in seen
    assert seen["only"] == [BUSY]          # drafting is narrowed, the run is not
    assert seen["stop_after"] is None


def test_tool_evidence_lands_on_the_page_and_stays_expandable(state, settings):
    """Step 4 into step 3: the tools mint into the same registry, so their
    row-level claims become expandable blocks without the page knowing about
    tools at all — and the grouped section must not cite anything unanchored."""
    from nafisnakh.customer360 import run_all_tools

    ctx = state["ctx"]
    before = len(ctx.evidence.for_customer(BUSY))
    results = run_all_tools(ctx, BUSY)
    assert len(ctx.evidence.for_customer(BUSY)) > before

    page = render_customer(BUSY, state, settings=settings)
    anchors = set(re.findall(r'<details class="evd" id="(EV-[^"]+)"', page))
    for r in results:
        assert r.tool in page
        for eid in r.evidence_ids:
            assert eid in anchors, f"{r.tool} cites {eid} with no expandable block"
    assert "پاسخ ابزارها" in page
