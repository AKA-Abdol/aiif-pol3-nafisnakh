"""The metric layer's shared context and registry.

Detectors are nothing but metric consumers (PLAN Q4), so the metric layer is a
strict prerequisite for the signal engine. This module holds the pieces they
share: the context object, the builder registry, and the helpers that keep
every emitted :class:`~nafisnakh.core.evidence.Evidence` traceable.

Design rules enforced here:

* A metric table is customer-grained and indexed by ``Customer_ID``.
* Every value a detector may cite has a matching Evidence with a Persian claim,
  a window, the rows it came from and the formula that produced it.
* Values derived from an unanswered open question (Q11 ``wacc_monthly``,
  Q12 cost-to-serve) carry ``assumption: true`` in their provenance and a
  confidence below 1.0. Nothing silently pretends to be measured.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..config import Settings
from ..core.cohort import Cohorts
from ..core.evidence import Evidence, EvidenceRegistry
from ..core.spine import Spine
from ..io import schema as S
from ..io.loader import Dataset

MetricBuilder = Callable[["MetricContext"], pd.DataFrame]
_REGISTRY: dict[str, MetricBuilder] = {}
_ORDER: list[str] = []


def metric_table(name: str) -> Callable[[MetricBuilder], MetricBuilder]:
    """Register a builder under a table name detectors can ``requires``."""

    def wrap(fn: MetricBuilder) -> MetricBuilder:
        _REGISTRY[name] = fn
        if name not in _ORDER:
            _ORDER.append(name)
        return fn

    return wrap


def registered_tables() -> list[str]:
    return list(_ORDER)


@dataclass
class MetricContext:
    """Everything a metric or a detector needs, and the evidence they produce."""

    ds: Dataset
    spine: Spine
    cohorts: Cohorts
    settings: Settings
    as_of: date
    evidence: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    # ------------------------------------------------------------ accessors
    def table(self, name: str) -> pd.DataFrame:
        if name not in self.tables:
            raise KeyError(
                f"metric table {name!r} not built; available: {sorted(self.tables)}"
            )
        return self.tables[name]

    def row(self, name: str, customer_id: str) -> pd.Series | None:
        tbl = self.table(name)
        if customer_id not in tbl.index:
            return None
        return tbl.loc[customer_id]

    @property
    def customers(self) -> pd.DataFrame:
        return self.ds.customers.set_index(S.CUSTOMER_ID)

    @property
    def population(self) -> list[str]:
        """Customers with at least one visible sales line at ``as_of``."""
        return self.spine.customers

    # ------------------------------------------------------------- windows
    def window(self, months: int) -> tuple[date, date]:
        end = pd.Timestamp(self.as_of)
        return ((end - pd.DateOffset(months=months)).date(), end.date())

    def ev(self, customer_id: str, *slugs: str) -> list[str]:
        """Evidence ids already emitted for this customer under these slugs.

        Detectors cite evidence, they do not restate numbers, so this is how a
        detector reaches the metric layer's output. Results come back in the
        order the slugs were requested, because that order is what the brief
        reads out — the most pertinent claim has to come first.
        """
        buckets: dict[str, list[str]] = {slug: [] for slug in slugs}
        for e in self.evidence.for_customer(customer_id):
            tail = e.id[len(f"EV-{customer_id}-"):]
            slug = tail.rsplit("-", 1)[0]
            if slug in buckets:
                buckets[slug].append(e.id)
        return [eid for slug in slugs for eid in buckets[slug]]

    def ev_value(self, customer_id: str, slug: str):
        """The value of the most recent evidence under ``slug``, or None."""
        ids = self.ev(customer_id, slug)
        return self.evidence.get(ids[-1]).value if ids else None

    # -------------------------------------------------------------- evidence
    def emit(
        self,
        customer_id: str,
        slug: str,
        claim_fa: str,
        value,
        *,
        unit: str | None = None,
        kind: str = "metric",
        window: tuple[date, date] | None = None,
        source_rows: str = "",
        formula: str = "",
        assumption: bool = False,
        confidence: float = 1.0,
        **provenance,
    ) -> Evidence:
        prov = {"formula": formula, **provenance}
        locator = getattr(source_rows, "locator", None)
        if assumption:
            prov["assumption"] = True
            prov.setdefault(
                "caveat_fa", "این مقدار بر پایه فرض پیکربندی است، نه اندازه‌گیری."
            )
        return self.evidence.add(
            customer_id,
            slug,
            kind=kind,
            claim_fa=claim_fa,
            value=value,
            unit=unit,
            as_of=self.as_of,
            window=window,
            source_rows=source_rows,
            provenance=prov,
            confidence=confidence,
            locator=locator,
        )


# ------------------------------------------------------------------ helpers
class RowRef(str):
    """The display string, carrying the machine-resolvable locator with it.

    Subclassing ``str`` means every existing ``source_rows=rows_ref(...)`` call
    site keeps working unchanged and the rendered text is identical, while
    :meth:`MetricContext.emit` can lift ``.locator`` off it. The two can never
    drift because the string is *derived from* the locator, not written beside it.
    """

    locator: dict

    def __new__(cls, text: str, locator: dict):
        obj = super().__new__(cls, text)
        obj.locator = locator
        return obj


def rows_ref(sheet: str, ids: Iterable, limit: int = 4, *, key: str | None = None) -> RowRef:
    """A traceable row reference: ``فروش:SL-1,SL-2,SL-3 +48``.

    ``key`` names the column ``ids`` are values of. It is required in practice —
    the same sheet is referenced by row id in one place and by ``Customer_ID`` in
    another, and only the caller knows which — but defaults per sheet so the
    common case stays short.
    """
    ids = [str(i) for i in ids if pd.notna(i)]
    key = key or DEFAULT_KEY.get(sheet, S.CUSTOMER_ID)
    locator = {"kind": "ids", "sheet": sheet, "key": key, "values": ids}
    if not ids:
        return RowRef(f"{sheet}:—", locator)
    head = ",".join(ids[:limit])
    extra = f" +{len(ids) - limit}" if len(ids) > limit else ""
    return RowRef(f"{sheet}:{head}{extra}", locator)


def span_ref(
    sheet: str, customer_id: str, window: tuple[date, date], n_rows: int,
    *, date_column: str | None = None,
) -> RowRef:
    """Reference for an aggregate over a window rather than named rows.

    The locator stores the *slice* (customer + date range) instead of a
    materialised id list. It resolves to exactly the rows the number was computed
    from, without carrying hundreds of ids in every evidence record — 3,042 of
    the 7,851 evidence at the demo anchor are of this shape.
    """
    return RowRef(
        f"{sheet}:{customer_id}@{window[0].isoformat()}..{window[1].isoformat()}"
        f" ({n_rows} ردیف)",
        {
            "kind": "filter", "sheet": sheet,
            "filters": {S.CUSTOMER_ID: customer_id},
            "date_column": date_column or DEFAULT_DATE_COLUMN.get(sheet),
            "date_from": window[0].isoformat(),
            "date_to": window[1].isoformat(),
        },
    )


# Which column an id list refers to, per sheet, when the caller does not say.
DEFAULT_KEY = {
    S.S_SALES: S.SALES_LINE_ID,
    S.S_INVOICES: S.INVOICE_NO,
    S.S_COLLECTIONS: S.INVOICE_NO,
    S.S_COMPLAINTS: S.K_ID,
    S.S_COMPLAINT_LINK: S.K_ID,
    S.S_CRM: S.X_ID,
    S.S_DEV_REQUESTS: S.D_ID,
    S.S_OFFERS: S.O_ID,
    S.S_WALLET: S.CUSTOMER_ID,
    S.S_HEMBAFT_LOT: S.HEMBAFT_ID,
    S.S_COST_REAL: S.SALES_LINE_ID,
    S.S_LOT_QUALITY: S.SALES_LINE_ID,
}

DEFAULT_DATE_COLUMN = {
    S.S_SALES: S.F_DATE,
    S.S_INVOICES: S.I_DATE,
    S.S_OFFERS: S.O_DATE,
    S.S_CRM: S.X_EVENT_TIME,
    S.S_COMPLAINTS: S.K_CREATED_AT,
    S.S_DEV_REQUESTS: S.D_CREATED_AT,
}


def days_since(as_of, series: pd.Series) -> pd.Series:
    """``as_of − series`` in whole days, safe on an all-empty column.

    An empty source sheet produces a float64 column of NaN, and subtracting a
    Timestamp from that raises. Every "days since X" metric goes through here so
    an absent sheet degrades to NaN instead of crashing the run.
    """
    stamps = pd.to_datetime(series, errors="coerce")
    return (pd.Timestamp(as_of) - stamps).dt.days


def pct(x: float | None, digits: int = 1) -> str:
    """Percent, ASCII digits, no separator — the validator compares literally."""
    if x is None or pd.isna(x):
        return "-"
    return f"{x * 100:.{digits}f}"


def num(x: float | None, digits: int = 1) -> str:
    if x is None or pd.isna(x):
        return "-"
    x = float(x)
    return str(int(x)) if x.is_integer() and abs(x) < 1e15 else f"{x:.{digits}f}"


def money(x: float | None, settings: Settings) -> str:
    """Money in the one scale used throughout (PLAN §5.4: never mix scales)."""
    if x is None or pd.isna(x):
        return "-"
    return f"{x / settings.currency_scale:.1f}{settings.currency_label}"


# Dependency order, not registration order: economics consumes payment, quality
# and engagement to build risk-adjusted margin, and wallet's headroom fallback
# consumes economics.
BUILD_ORDER = [
    "cadence", "payment", "quality", "engagement", "mix", "economics", "wallet",
    "rfm", "open_loops",
]


def build_metrics(ctx: MetricContext, only: list[str] | None = None) -> MetricContext:
    """Run the metric builders in dependency order."""
    from . import (  # noqa: F401  — imported for side-effect registration
        cadence, economics, engagement, mix, open_loops, payment, quality, rfm, wallet,
    )

    missing = set(_REGISTRY) - set(BUILD_ORDER)
    if missing:
        raise RuntimeError(f"metric tables not placed in BUILD_ORDER: {sorted(missing)}")
    for name in BUILD_ORDER:
        if only and name not in only:
            continue
        ctx.tables[name] = _REGISTRY[name](ctx)
    return ctx


def make_context(
    ds: Dataset, as_of: date | None = None, settings: Settings | None = None
) -> MetricContext:
    from ..core.cohort import build_cohorts
    from ..core.spine import build_spine

    st = settings or ds.settings
    as_of = as_of or st.as_of
    spine = build_spine(ds, as_of=as_of, settings=st)
    cohorts = build_cohorts(spine, ds.customers)
    return MetricContext(
        ds=ds, spine=spine, cohorts=cohorts, settings=st, as_of=as_of
    )
