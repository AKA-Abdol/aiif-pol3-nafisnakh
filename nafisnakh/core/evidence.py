"""The evidence contract (PLAN §3.1, §3.3).

Everything the system will eventually say to a sales manager has to be traceable
to a number that a deterministic function computed from named source rows. An
``Evidence`` is that number plus its Persian sentence, its window, its formula
and the rows it came from. The LLM is handed only ``claim_fa`` strings and
``id``s — it never sees or writes a raw number — and ``aggregate/validate.py``
later refuses any action citing an id that does not exist here.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable, Literal

EvidenceKind = Literal["metric", "event", "text", "comparison"]

# numerals that may appear in generated text without being "a number claim":
# ordinals, years and the like are filtered out by the validator, not here.
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

# claims are written with ASCII digits, but Persian text pasted from the data can
# carry ۰-۹ / ٠-٩; fold them before any numeral comparison.
_DIGIT_FOLD = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGIT_FOLD.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})


def fold_digits(text: str) -> str:
    """Persian/Arabic-Indic digits → ASCII, so numerals compare literally."""
    return str(text).translate(_DIGIT_FOLD)


def extract_numerals(text: str) -> set[str]:
    """Every numeral in a string, normalised (ASCII digits, no separators,
    no trailing zeros) so ``45``, ``45.0`` and ``۴۵`` all compare equal."""
    out = set()
    for raw in NUMBER_RE.findall(fold_digits(text)):
        n = raw.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n or "0")
    return out


@dataclass(frozen=True)
class Evidence:
    """One traceable, display-ready fact about one customer."""

    id: str
    customer_id: str
    kind: EvidenceKind
    claim_fa: str
    value: float | str
    unit: str | None
    as_of: date
    window: tuple[date, date] | None
    source_rows: str
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    # numbers that legitimately appear in this evidence's own text
    def numerals(self) -> set[str]:
        return extract_numerals(str(self.value)) | extract_numerals(self.claim_fa)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["window"] = (
            [self.window[0].isoformat(), self.window[1].isoformat()]
            if self.window
            else None
        )
        return d


class EvidenceRegistry:
    """Append-only store of Evidence, indexed by id and by customer.

    Ids are stable and deterministic: ``EV-<customer>-<slug>-<nnn>``. Stability
    matters because the LLM cache and the golden fixture snapshots key on them.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._by_customer: dict[str, list[str]] = {}
        self._counters: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------- creation
    def next_id(self, customer_id: str, slug: str) -> str:
        key = (customer_id, slug)
        self._counters[key] = self._counters.get(key, 0) + 1
        return f"EV-{customer_id}-{slug}-{self._counters[key]:03d}"

    def add(
        self,
        customer_id: str,
        slug: str,
        *,
        kind: EvidenceKind,
        claim_fa: str,
        value: float | str,
        unit: str | None,
        as_of: date,
        window: tuple[date, date] | None = None,
        source_rows: str = "",
        provenance: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> Evidence:
        ev = Evidence(
            id=self.next_id(customer_id, slug),
            customer_id=customer_id,
            kind=kind,
            claim_fa=claim_fa.strip(),
            value=value,
            unit=unit,
            as_of=as_of,
            window=window,
            source_rows=source_rows,
            provenance=provenance or {},
            confidence=confidence,
        )
        self._by_id[ev.id] = ev
        self._by_customer.setdefault(customer_id, []).append(ev.id)
        return ev

    def extend(self, items: Iterable[Evidence]) -> None:
        for ev in items:
            self._by_id[ev.id] = ev
            self._by_customer.setdefault(ev.customer_id, []).append(ev.id)

    # -------------------------------------------------------------- lookup
    def __contains__(self, evidence_id: str) -> bool:
        return evidence_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)

    def for_customer(self, customer_id: str) -> list[Evidence]:
        return [self._by_id[i] for i in self._by_customer.get(customer_id, [])]

    def many(self, ids: Iterable[str]) -> list[Evidence]:
        return [self._by_id[i] for i in ids if i in self._by_id]

    def customers(self) -> list[str]:
        return list(self._by_customer)

    def all(self) -> list[Evidence]:
        return list(self._by_id.values())

    # ---------------------------------------------------------------- I/O
    def to_records(self) -> list[dict[str, Any]]:
        return [ev.to_dict() for ev in self._by_id.values()]

    def dump_json(self, path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_records(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "EvidenceRegistry":
        reg = cls()
        for r in records:
            window = (
                (date.fromisoformat(r["window"][0]), date.fromisoformat(r["window"][1]))
                if r.get("window")
                else None
            )
            reg.extend([
                Evidence(
                    id=r["id"],
                    customer_id=r["customer_id"],
                    kind=r["kind"],
                    claim_fa=r["claim_fa"],
                    value=r["value"],
                    unit=r.get("unit"),
                    as_of=date.fromisoformat(r["as_of"]),
                    window=window,
                    source_rows=r.get("source_rows", ""),
                    provenance=r.get("provenance", {}),
                    confidence=r.get("confidence", 1.0),
                )
            ])
        return reg


def fmt_num(value: float, digits: int = 1) -> str:
    """Persian-facing number formatting: no thousands separator inside claims
    (the validator compares numerals literally), fixed decimals."""
    if value is None:
        return "-"
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.{digits}f}"
