"""The feedback loop: what the sales manager did with the queue (PLAN §4, Phase 2).

A queue nobody grades is a queue that never gets better. This module records the
one thing the system cannot compute — whether an action was worth the sales
manager's time — and feeds it back into the ranking.

The mechanism is deliberately modest, because the honest sample size is small:

* Feedback is appended to a JSONL file. Append-only, so a mistaken entry is
  visible in history rather than silently overwritten.
* Per detector we track **acted vs dismissed**. That ratio is the closest thing
  to precision that exists here: the detector said "this is worth an hour" and a
  human said yes or no.
* The ratio becomes a **ranking weight**, not a threshold change. Weights shift
  the order of the queue; they never silence a detector. A detector that stops
  firing can never earn its way back, and one bad month should not delete a
  signal that matters twice a year.
* Weights are **shrunk toward 1.0 by the sample size** (a Bayesian-flavoured
  smoothing with a configurable prior). Three dismissals is an opinion, not
  evidence; thirty is evidence. Below `feedback_min_events` a detector keeps a
  weight of exactly 1.0.

Nothing here retrains a model. It reorders a list, and it shows its arithmetic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

from .config import Settings, get_settings

log = logging.getLogger(__name__)

Decision = Literal["done", "dismissed", "snoozed", "wrong"]

# `snoozed` is neither a yes nor a no and is excluded from the ratio; `wrong`
# is a stronger no than `dismissed` — the manager is saying the fact itself was
# not true, which is a data problem, not a prioritisation one.
POSITIVE = {"done"}
NEGATIVE = {"dismissed", "wrong"}


@dataclass(frozen=True)
class FeedbackEvent:
    customer_id: str
    decision: Decision
    detectors: list[str]
    as_of: str
    recorded_at: str
    rank: int | None = None
    bucket: str | None = None
    reason_fa: str | None = None
    actor: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class FeedbackStore:
    """Append-only JSONL store of manager decisions."""

    def __init__(self, path: Path | None = None, settings: Settings | None = None):
        st = settings or get_settings()
        self.path = Path(path) if path else Path(st.out_dir) / "feedback.jsonl"
        self.settings = st

    # ------------------------------------------------------------- writing
    def record(
        self,
        customer_id: str,
        decision: Decision,
        detectors: Iterable[str],
        *,
        as_of: date | str | None = None,
        rank: int | None = None,
        bucket: str | None = None,
        reason_fa: str | None = None,
        actor: str | None = None,
    ) -> FeedbackEvent:
        if decision not in {"done", "dismissed", "snoozed", "wrong"}:
            raise ValueError(f"unknown decision {decision!r}")
        as_of = as_of or self.settings.as_of
        event = FeedbackEvent(
            customer_id=customer_id,
            decision=decision,
            detectors=sorted(set(detectors)),
            as_of=as_of.isoformat() if isinstance(as_of, date) else str(as_of),
            recorded_at=datetime.now().isoformat(timespec="seconds"),
            rank=rank,
            bucket=bucket,
            reason_fa=reason_fa,
            actor=actor,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def record_for_action(self, action, decision: Decision, **kwargs) -> FeedbackEvent:
        """Record a decision straight off an :class:`Action`."""
        return self.record(
            action.customer_id, decision, action.signals,
            rank=action.rank, bucket=action.bucket, **kwargs
        )

    # ------------------------------------------------------------- reading
    def events(self) -> list[FeedbackEvent]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(FeedbackEvent(**json.loads(line)))
            except (json.JSONDecodeError, TypeError) as exc:
                log.warning("skipping malformed feedback line: %s", exc)
        return out

    def frame(self) -> pd.DataFrame:
        events = self.events()
        if not events:
            return pd.DataFrame(
                columns=["customer_id", "decision", "detectors", "as_of",
                         "recorded_at", "rank", "bucket", "reason_fa", "actor"]
            )
        return pd.DataFrame([e.to_dict() for e in events])


# --------------------------------------------------------------- aggregation
def detector_stats(store: FeedbackStore) -> pd.DataFrame:
    """Acted / dismissed counts and the smoothed weight, per detector.

    A single action carries several detectors, so one decision credits or debits
    all of them. That is the honest attribution available without asking the
    manager which signal convinced them — and asking is a Phase 3 question.
    """
    st = store.settings
    rows: dict[str, dict[str, int]] = {}
    for event in store.events():
        if event.decision not in POSITIVE | NEGATIVE:
            continue
        for detector in event.detectors:
            bucket = rows.setdefault(detector, {"acted": 0, "dismissed": 0, "wrong": 0})
            if event.decision in POSITIVE:
                bucket["acted"] += 1
            else:
                bucket["dismissed"] += 1
                if event.decision == "wrong":
                    bucket["wrong"] += 1

    if not rows:
        return pd.DataFrame(
            columns=["detector", "acted", "dismissed", "wrong", "n", "act_rate",
                     "weight", "enough_evidence"]
        )

    prior = st.feedback_prior_strength
    out = []
    for detector, counts in sorted(rows.items()):
        n = counts["acted"] + counts["dismissed"]
        act_rate = counts["acted"] / n if n else 0.0
        # shrink toward the neutral 0.5 by the prior, then map to a weight
        # around 1.0 bounded by feedback_weight_range
        smoothed = (counts["acted"] + prior * 0.5) / (n + prior)
        span = st.feedback_weight_range
        weight = 1.0 + (smoothed - 0.5) * 2.0 * span
        enough = n >= st.feedback_min_events
        out.append({
            "detector": detector,
            "acted": counts["acted"],
            "dismissed": counts["dismissed"],
            "wrong": counts["wrong"],
            "n": n,
            "act_rate": round(act_rate, 3),
            "weight": round(weight if enough else 1.0, 3),
            "enough_evidence": enough,
        })
    return pd.DataFrame(out).sort_values("weight", ascending=False)


def detector_weights(
    store: FeedbackStore | None = None, settings: Settings | None = None
) -> dict[str, float]:
    """The ranking weights, ready to hand to :func:`priority_score`.

    Detectors with too little feedback are simply absent, which the scorer reads
    as 1.0 — no feedback means no opinion, not a penalty.
    """
    st = settings or get_settings()
    store = store or FeedbackStore(settings=st)
    stats = detector_stats(store)
    if stats.empty:
        return {}
    return {
        r.detector: float(r.weight)
        for r in stats.itertuples()
        if r.enough_evidence
    }


def recalibration_report(store: FeedbackStore) -> str:
    """A short, honest read of what the feedback so far does and does not say."""
    stats = detector_stats(store)
    st = store.settings
    if stats.empty:
        return (
            "هنوز هیچ بازخوردی ثبت نشده است.\n"
            "با `nafisnakh feedback --customer <id> --decision done|dismissed` ثبت کنید."
        )
    usable = stats.loc[stats["enough_evidence"]]
    lines = [
        "بازخورد مدیر فروش — اثر روی رتبه‌بندی",
        "=" * 58,
        f"مجموع رویدادها: {int(stats['n'].sum())}",
        f"آشکارسازهای با بازخورد کافی (≥{st.feedback_min_events}): "
        f"{len(usable)} از {len(stats)}",
        "",
        stats.to_string(index=False),
        "",
    ]
    if usable.empty:
        lines.append(
            "هیچ آشکارسازی هنوز بازخورد کافی ندارد؛ همه وزن‌ها ۱.۰ می‌مانند. "
            "این درست است — چند رد کردن یک نظر است، نه شواهد."
        )
    else:
        best = usable.iloc[0]
        worst = usable.iloc[-1]
        lines += [
            f"بیشترین اثر مثبت: {best.detector} (وزن {best.weight})",
            f"کمترین اثر: {worst.detector} (وزن {worst.weight})",
            "وزن‌ها فقط ترتیب صف را جابه‌جا می‌کنند و هیچ آشکارسازی را خاموش نمی‌کنند.",
        ]
    return "\n".join(lines)
