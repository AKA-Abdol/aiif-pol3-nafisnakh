from datetime import date

import pytest

from nafisnakh.core.evidence import Evidence, EvidenceRegistry, extract_numerals


def _add(reg, cid="C_1", slug="cadence"):
    return reg.add(
        cid, slug,
        kind="metric",
        claim_fa="45 روز از آخرین خرید گذشته (میانه شخصی 14 روز)",
        value=45.0, unit="روز", as_of=date(2021, 6, 30),
        window=(date(2021, 1, 1), date(2021, 6, 30)),
        source_rows="فروش:12,13",
        provenance={"formula": "days_since_last / own_median_gap"},
    )


def test_ids_are_stable_and_sequential():
    reg = EvidenceRegistry()
    a, b = _add(reg), _add(reg)
    assert a.id == "EV-C_1-cadence-001"
    assert b.id == "EV-C_1-cadence-002"
    assert a.id in reg and reg.get(b.id) is b


def test_registry_indexes_by_customer():
    reg = EvidenceRegistry()
    _add(reg, "C_1")
    _add(reg, "C_2")
    assert [e.customer_id for e in reg.for_customer("C_2")] == ["C_2"]
    assert set(reg.customers()) == {"C_1", "C_2"}


def test_numerals_fold_persian_digits_and_trailing_zeros():
    assert extract_numerals("۴۵ روز") == {"45"}
    assert extract_numerals("رشد 12.50 درصد") == {"12.5"}
    reg = EvidenceRegistry()
    ev = _add(reg)
    assert {"45", "14"} <= ev.numerals()


def test_json_round_trip(tmp_path):
    reg = EvidenceRegistry()
    _add(reg)
    path = tmp_path / "ev.json"
    reg.dump_json(path)
    import json

    back = EvidenceRegistry.from_records(json.loads(path.read_text(encoding="utf-8")))
    assert len(back) == len(reg)
    assert back.get("EV-C_1-cadence-001").claim_fa == reg.get("EV-C_1-cadence-001").claim_fa


def test_evidence_is_immutable():
    reg = EvidenceRegistry()
    ev = _add(reg)
    with pytest.raises(Exception):
        ev.value = 99  # frozen dataclass


# ------------------------------------------------- locators (PLAN §2, step 1)
@pytest.fixture(scope="module")
def ctx(ds):
    from datetime import date

    from nafisnakh.metrics.base import build_metrics, make_context

    return build_metrics(make_context(ds, as_of=date(2021, 6, 30)))


def test_every_emitted_evidence_carries_a_resolvable_locator(ctx):
    """A recommendation shown to a customer must open down to its records.

    This is the enforcement, not a convention: any new emitter that forgets its
    locator fails here rather than shipping an unopenable claim.
    """
    missing = [e.id for e in ctx.evidence.all() if not e.is_resolvable]
    assert not missing, f"{len(missing)} evidence without a locator, e.g. {missing[:5]}"


def test_every_locator_returns_real_rows(ctx):
    from nafisnakh.core.evidence import resolve

    empty, failed = [], []
    for e in ctx.evidence.all():
        try:
            if len(resolve(e, ctx.ds)) == 0:
                empty.append(e.id)
        except Exception as exc:                       # noqa: BLE001 — report, don't mask
            failed.append(f"{e.id}: {type(exc).__name__} {exc}")
    assert not failed, failed[:5]
    assert not empty, f"{len(empty)} locators resolved to zero rows, e.g. {empty[:5]}"


def test_locator_survives_a_round_trip_through_json(ctx, tmp_path):
    import json

    from nafisnakh.core.evidence import EvidenceRegistry

    path = tmp_path / "ev.json"
    ctx.evidence.dump_json(path)
    restored = EvidenceRegistry.from_records(json.loads(path.read_text(encoding="utf-8")))
    for original in ctx.evidence.all():
        assert restored.get(original.id).locator == original.locator


def test_source_rows_is_derived_from_the_locator_not_written_beside_it():
    """The display string and the pointer cannot drift, because one makes the other."""
    from nafisnakh.io import schema as S
    from nafisnakh.metrics.base import rows_ref

    ref = rows_ref(S.S_COMPLAINTS, ["CMP-0001", "CMP-0002"])
    assert ref.locator["values"] == ["CMP-0001", "CMP-0002"]
    assert ref.locator["key"] == S.K_ID
    assert "CMP-0001" in str(ref)


def test_drill_down_never_shows_rows_the_claim_could_not_have_seen(ctx):
    """Rule #4 governs the display layer too.

    The ungated resolver returned 2022 invoices for a claim computed at
    2021-06-30 — records the number could not have come from, shown to a
    customer as its justification.
    """
    import pandas as pd

    from nafisnakh.core.evidence import SHEET_DATE_COLUMN, resolve

    late = 0
    for e in ctx.evidence.all():
        col = SHEET_DATE_COLUMN.get((e.locator or {}).get("sheet"))
        if not col:
            continue
        rows = resolve(e, ctx.ds)
        if col in rows.columns:
            late += int((pd.to_datetime(rows[col], errors="coerce")
                         > pd.Timestamp(e.as_of)).sum())
    assert late == 0, f"{late} source rows dated after as_of"
