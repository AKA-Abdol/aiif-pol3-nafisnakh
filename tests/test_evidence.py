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
