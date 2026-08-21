"""Run the detectors, dedupe, score, rank, and calibrate.

Ranking is **deterministic Python** (PLAN §3.7). The LLM writes the reasoning
and the recommended step; it never decides the order. Ordering has to be
reproducible and auditable — the sales manager must be able to ask "why is this
account above that one?" and get an arithmetic answer.

The calibration pass exists because thresholds in ``config.py`` are starting
defaults, not measurements. A detector that fires on 70% of the book is a
tautology; one that fires on 0.5% is decoration. Detectors marked
``rare_by_design`` (a bounced cheque, a churn threat, a blast radius) are
exempt from the lower bound — rarity is the point of those.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..metrics.base import MetricContext
from .base import BaseDetector, Signal, all_detectors

log = logging.getLogger(__name__)

# how much each suggested bucket is worth in the queue (PLAN §0 strategy:
# fewer customers, higher and steadier margin)
BUCKET_WEIGHT = {"protect": 1.25, "fix": 1.15, "grow": 1.0, "reduce": 0.55, None: 1.0}
CATEGORY_WEIGHT = {"risk": 1.0, "efficiency": 0.95, "opportunity": 0.85}


@dataclass
class SignalRun:
    signals: list[Signal]
    as_of: date
    fire_rates: dict[str, float]
    population: int
    eligible_counts: dict[str, int] = field(default_factory=dict)
    fired_counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)

    def to_frame(self) -> pd.DataFrame:
        if not self.signals:
            return pd.DataFrame(
                columns=["customer_id", "detector", "category", "severity",
                         "value_at_stake", "priority_score", "headline_fa"]
            )
        return pd.DataFrame([s.to_dict() for s in self.signals])

    def by_customer(self) -> dict[str, list[Signal]]:
        out: dict[str, list[Signal]] = {}
        for s in self.signals:
            out.setdefault(s.customer_id, []).append(s)
        return out

    def triggered_customers(self) -> list[str]:
        return sorted(self.by_customer())

    def dump_json(self, path: Path) -> None:
        payload = {
            "as_of": self.as_of.isoformat(),
            "population": self.population,
            "fire_rates": self.fire_rates,
            "feedback_weights": self.weights,
            "signals": [s.to_dict() for s in self.signals],
        }
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def priority_score(
    signal: Signal, settings, weights: Mapping[str, float] | None = None
) -> float:
    """``severity × log1p(value_at_stake) × bucket_weight × category_weight``,
    times the sales manager's own verdict on the detector.

    ``log1p`` keeps one enormous account from burying twenty real problems, and
    the money is scaled first so the log is taken on a human-sized number.

    ``weights`` comes from :mod:`nafisnakh.feedback`. A detector with too little
    feedback is absent from the mapping and scores 1.0 — silence is not a
    penalty, and no weight can drive a signal out of the queue entirely.
    """
    stake = max(float(signal.value_at_stake or 0.0), 0.0) / settings.currency_scale
    feedback = (weights or {}).get(signal.detector, 1.0)
    return float(
        signal.severity
        * np.log1p(stake)
        * BUCKET_WEIGHT.get(signal.suggested_bucket, 1.0)
        * CATEGORY_WEIGHT.get(signal.category, 1.0)
        * feedback
    )


def dedupe(signals: list[Signal]) -> list[Signal]:
    """One signal per (customer, detector) — keep the most severe.

    Detectors are written to emit at most one row per customer, but the rule is
    enforced here so a future detector cannot quietly flood the queue.
    """
    best: dict[tuple[str, str], Signal] = {}
    for s in signals:
        key = (s.customer_id, s.detector)
        if key not in best or s.severity > best[key].severity:
            best[key] = s
    return list(best.values())


def run_detectors(
    ctx: MetricContext,
    only: list[str] | None = None,
    strict: bool = False,
    weights: Mapping[str, float] | None = None,
) -> SignalRun:
    detectors: list[BaseDetector] = [
        d for d in all_detectors() if not only or d.name in only
    ]
    signals: list[Signal] = []
    errors: dict[str, str] = {}
    counts: Counter[str] = Counter()

    for det in detectors:
        missing = [t for t in det.requires if t not in ctx.tables]
        if missing:
            errors[det.name] = f"missing metric tables: {missing}"
            log.warning("detector %s skipped — %s", det.name, errors[det.name])
            continue
        try:
            found = det.detect(ctx)
        except Exception as exc:                       # one bad detector must not
            if strict:                                 # take down the whole run
                raise
            errors[det.name] = f"{type(exc).__name__}: {exc}"
            log.exception("detector %s failed", det.name)
            continue
        counts[det.name] = len(found)
        signals.extend(found)

    signals = dedupe(signals)
    signals.sort(key=lambda s: priority_score(s, ctx.settings, weights), reverse=True)

    population = max(len(ctx.population), 1)
    eligible_counts, fire_rates = {}, {}
    for d in detectors:
        try:
            n_eligible = max(len(d.eligible(ctx)), 0)
        except Exception:                              # a detector with no table
            n_eligible = population
        eligible_counts[d.name] = n_eligible
        fire_rates[d.name] = counts.get(d.name, 0) / n_eligible if n_eligible else 0.0
    return SignalRun(
        signals=signals, as_of=ctx.as_of, fire_rates=fire_rates,
        population=population, eligible_counts=eligible_counts,
        fired_counts=dict(counts), errors=errors,
        weights=dict(weights or {}),
    )


# ------------------------------------------------------------------ calibration
@dataclass
class CalibrationReport:
    rows: pd.DataFrame
    population: int
    as_of: date

    @property
    def failures(self) -> pd.DataFrame:
        """Verdicts that mean something went wrong.

        ``insufficient`` is deliberately not one of them: it says the population
        was too small to judge, which is a fact about the run, not about the
        detector.
        """
        return self.rows.loc[self.rows["status"].isin(
            ("too_broad", "too_narrow", "error")
        )]

    @property
    def insufficient(self) -> pd.DataFrame:
        return self.rows.loc[self.rows["status"] == "insufficient"]

    def __str__(self) -> str:
        return self.rows.to_string(index=False)


def calibrate(run: SignalRun, ctx: MetricContext) -> CalibrationReport:
    """Check every detector's fire rate against the §4 guard-rails.

    The rate is ``fired / eligible``, not ``fired / whole book``: a returns
    detector cannot fire on a customer with no returns, and dividing by the
    whole book would condemn a correctly-scoped detector as "too narrow".

    A detector whose eligible population is below ``calib_min_eligible`` is
    reported ``insufficient`` rather than judged. Without that, any subset run
    produces a wall of false alarms — "1 fired of 1 eligible = 100%, too_broad"
    — which trains the reader to ignore the table.
    """
    st = ctx.settings
    by_name = {d.name: d for d in all_detectors()}
    rows = []
    for name, rate in sorted(run.fire_rates.items(), key=lambda kv: -kv[1]):
        det = by_name[name]
        n_eligible = run.eligible_counts.get(name, run.population)
        if name in run.errors:
            status = "error"
        elif n_eligible < st.calib_min_eligible:
            status = "insufficient"
        elif rate > st.calib_max_fire_rate:
            status = "too_broad"
        elif rate < st.calib_min_fire_rate and not det.rare_by_design:
            status = "too_narrow"
        else:
            status = "ok"
        rows.append({
            "detector": name,
            "category": det.category,
            "fired": run.fired_counts.get(name, 0),
            "eligible": n_eligible,
            "fire_rate": round(rate, 4),
            "rare_by_design": det.rare_by_design,
            "status": status,
            "note": run.errors.get(name, ""),
        })
    return CalibrationReport(
        rows=pd.DataFrame(rows), population=run.population, as_of=run.as_of
    )
