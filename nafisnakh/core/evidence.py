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
    # Machine-resolvable pointer to the rows behind this claim. `source_rows` is
    # the human-readable rendering of the same thing and is derived from it, so
    # the two cannot drift. See :func:`resolve` — an action shown to a customer
    # has to be openable down to the records it rests on.
    locator: dict[str, Any] | None = None

    # numbers that legitimately appear in this evidence's own text
    def numerals(self) -> set[str]:
        return extract_numerals(str(self.value)) | extract_numerals(self.claim_fa)

    @property
    def is_resolvable(self) -> bool:
        return bool(self.locator) and self.locator.get("kind") in ("ids", "filter")

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
        locator: dict[str, Any] | None = None,
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
            # store a plain str: RowRef is a carrier for the trip into here, and
            # keeping the subclass on a frozen dataclass breaks asdict()/deepcopy
            source_rows=str(source_rows),
            provenance=provenance or {},
            confidence=confidence,
            # `source_rows` may be a RowRef carrying its own locator; an explicit
            # argument wins so a caller can always be specific.
            locator=locator or getattr(source_rows, "locator", None),
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
                    locator=r.get("locator"),
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


# ------------------------------------------------------------------- resolving
# The natural event date per sheet. Not used for gating — `Available_At` already
# does that — but the regression test uses it to prove no drill-down ever returns
# a row dated after the claim's `as_of`.
SHEET_DATE_COLUMN = {
    "فروش": "تاریخ",
    "فاکتورها": "تاریخ",
    "وصول": "تاریخ رویداد وصول",
    "شکایات": "Created_At",
    "تعاملات_CRM": "Event_Time",
    "درخواست_توسعه": "Created_At",
    "آفرها": "Offer_Date",
}
def resolve(evidence: Evidence, dataset) -> "Any":
    """The actual rows behind one Evidence, as a DataFrame.

    Two locator kinds, because evidence comes in two shapes:

    * ``ids``    — this claim is about these specific records
      (``{"kind": "ids", "sheet": ..., "key": ..., "values": [...]}``).
    * ``filter`` — this claim is an aggregate over a slice
      (``{"kind": "filter", "sheet": ..., "filters": {...},
      "date_column": ..., "date_from": ..., "date_to": ...}``). Storing the slice
      rather than a materialised id list keeps the evidence small while still
      returning exactly the rows the number was computed from.

    Both return real rows from the workbook, which is the point: a
    recommendation shown to a customer has to be openable down to its records.
    """
    import pandas as pd

    from .spine import visible

    loc = evidence.locator
    if not loc:
        raise ValueError(f"{evidence.id} has no locator; it cannot be resolved")
    sheet = loc.get("sheet")
    if sheet not in dataset.frames:
        raise KeyError(f"{evidence.id} points at unknown sheet {sheet!r}")

    # Rule #4 applies to the drill-down exactly as it applied to the calculation.
    # Without it the resolver shows rows dated after `as_of` — records the claim
    # could not have come from, presented to a customer as its justification.
    #
    # `Available_At` alone is the right gate, and it is sufficient: measured
    # across all seven dated sheets it leaves **zero** rows dated after `as_of`.
    # Cutting on the event date as well was *stricter than the metric layer* and
    # emptied a valid DSO locator whose collection events are visible but late.
    df = visible(dataset.frames[sheet], evidence.as_of)

    if loc["kind"] == "ids":
        key, values = loc["key"], loc.get("values") or []
        if key not in df.columns:
            raise KeyError(f"{evidence.id}: {sheet!r} has no column {key!r}")
        return df.loc[df[key].isin(values)]

    if loc["kind"] == "filter":
        mask = pd.Series(True, index=df.index)
        for col, val in (loc.get("filters") or {}).items():
            if col not in df.columns:
                raise KeyError(f"{evidence.id}: {sheet!r} has no column {col!r}")
            mask &= df[col] == val
        date_col = loc.get("date_column")
        if date_col and date_col in df.columns:
            stamps = pd.to_datetime(df[date_col], errors="coerce")
            if loc.get("date_from"):
                mask &= stamps > pd.Timestamp(loc["date_from"])
            if loc.get("date_to"):
                mask &= stamps <= pd.Timestamp(loc["date_to"])
        return df.loc[mask]

    raise ValueError(f"{evidence.id}: unknown locator kind {loc['kind']!r}")
