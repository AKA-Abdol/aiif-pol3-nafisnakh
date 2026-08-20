"""Signal contract, detector protocol and registry (PLAN §3.3).

A detector is a pure function of the metric layer. It never reads a dataframe
from the dataset directly, never formats a number into prose, and never invents
a fact: it reads metric tables, decides whether something is true, and returns a
:class:`Signal` that **cites evidence ids**. That indirection is what makes the
final "evidence-backed" claim enforceable rather than decorative.

Severity is a 0–100 scale that each detector normalises itself, so a cadence
breach at 3× and a margin 40 points below cohort are comparable when the queue
is ranked. ``value_at_stake`` is money, and it is what turns "worrying" into
"worth the sales manager's next hour".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from ..metrics.base import MetricContext

Category = Literal["risk", "opportunity", "efficiency"]
Direction = Literal["deteriorating", "improving", "static"]
Bucket = Literal["grow", "protect", "fix", "reduce"]


@dataclass(frozen=True)
class Signal:
    id: str
    customer_id: str
    detector: str
    category: Category
    severity: float
    direction: Direction
    headline_fa: str
    evidence_ids: list[str]
    first_detected_at: date
    value_at_stake: float
    suggested_bucket: Bucket | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["first_detected_at"] = self.first_detected_at.isoformat()
        return d


@runtime_checkable
class Detector(Protocol):
    name: str
    category: Category
    requires: list[str]

    def detect(self, ctx: MetricContext) -> list[Signal]: ...


_REGISTRY: dict[str, "BaseDetector"] = {}


def register(cls):
    """Class decorator — instantiate once and add to the registry."""
    inst = cls()
    if inst.name in _REGISTRY:
        raise ValueError(f"duplicate detector name {inst.name!r}")
    _REGISTRY[inst.name] = inst
    return cls


def all_detectors() -> list["BaseDetector"]:
    from . import detectors  # noqa: F401 — import for side-effect registration

    return list(_REGISTRY.values())


def get_detector(name: str) -> "BaseDetector":
    from . import detectors  # noqa: F401

    return _REGISTRY[name]


# --------------------------------------------------------------------- helpers
def scale(value: float, lo: float, hi: float, floor: float = 10.0) -> float:
    """Map a magnitude onto 0–100 severity, linearly between ``lo`` and ``hi``.

    ``floor`` keeps a just-triggered signal from scoring zero — it fired, so it
    is worth at least something.
    """
    if value is None or pd.isna(value):
        return floor
    if hi == lo:
        return floor
    t = (float(value) - lo) / (hi - lo)
    return float(np.clip(floor + t * (100.0 - floor), floor, 100.0))


class BaseDetector:
    """Shared plumbing: name, category, required tables, and safe row access."""

    name: str = ""
    category: Category = "risk"
    requires: list[str] = []
    # Detectors that are rare by design are exempt from the "must fire on ≥2%
    # of the book" calibration guard (PLAN §4, Phase 1b).
    rare_by_design: bool = False

    def detect(self, ctx: MetricContext) -> list[Signal]:  # pragma: no cover
        raise NotImplementedError

    # ---------------------------------------------------------------- utils
    def signal(
        self,
        ctx: MetricContext,
        customer_id: str,
        *,
        severity: float,
        headline_fa: str,
        evidence_ids: list[str],
        value_at_stake: float,
        direction: Direction = "deteriorating",
        suggested_bucket: Bucket | None = None,
        **detail,
    ) -> Signal:
        return Signal(
            id=f"SIG-{customer_id}-{self.name}",
            customer_id=customer_id,
            detector=self.name,
            category=self.category,
            severity=round(float(severity), 1),
            direction=direction,
            headline_fa=headline_fa,
            evidence_ids=evidence_ids,
            first_detected_at=ctx.as_of,
            value_at_stake=float(value_at_stake or 0.0),
            suggested_bucket=suggested_bucket,
            detail=detail,
        )

    def frame(self, ctx: MetricContext) -> pd.DataFrame:
        """The required tables joined on Customer_ID, restricted to the book.

        Column collisions are suffixed with the *table name*, never with a
        positional counter, so a detector's column references stay stable when
        another table gains a column.
        """
        out = ctx.table(self.requires[0])
        for name in self.requires[1:]:
            out = out.join(ctx.table(name), how="left", rsuffix=f"__{name}")
        return out.loc[out.index.isin(ctx.population)]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        """The customers this detector could *possibly* fire on.

        Calibration divides by this, not by the whole book: a returns detector
        cannot fire on a customer with no returns, and judging it against the
        full population would call a correct detector "too narrow".
        """
        return pd.Index(ctx.population)


def annual_revenue(ctx: MetricContext, customer_id: str) -> float:
    """Revenue over the trailing 12 months — the denominator for money at stake."""
    econ = ctx.table("economics")
    if customer_id not in econ.index:
        return 0.0
    row = econ.loc[customer_id]
    monthly = (row.get("revenue_recent", 0.0) or 0.0) / ctx.settings.recent_window_months
    if monthly <= 0:
        monthly = (row.get("revenue_total", 0.0) or 0.0) / 12.0
    return float(max(monthly, 0.0) * 12.0)


def annual_margin(ctx: MetricContext, customer_id: str) -> float:
    econ = ctx.table("economics")
    if customer_id not in econ.index:
        return 0.0
    row = econ.loc[customer_id]
    rate = row.get("risk_adj_margin_rate")
    if rate is None or pd.isna(rate):
        rate = row.get("margin_rate", 0.0) or 0.0
    return float(annual_revenue(ctx, customer_id) * float(rate))
