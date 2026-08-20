"""The final step: signals + evidence → a ranked, cited action queue (PLAN §3.7).

Division of labour, and it is the whole design:

* **Python ranks.** `severity × log1p(value_at_stake) × bucket_weight` is computed
  in :mod:`nafisnakh.signals.engine`. The order must be reproducible and
  auditable — the sales manager can ask "why is this above that?" and get
  arithmetic, not a model's mood.
* **The LLM writes.** Title, rationale and recommended step, in Persian, for a
  sales manager. It is handed *evidence claims and ids only* — never a dataframe,
  never a raw number.
* **The validator refuses.** Anything that cites an id that does not exist,
  belongs to another customer, or contains a number absent from its evidence is
  retried once and then dropped.

Offline (no key — Q14) the same structure runs with a deterministic Persian
composer instead of the model. Its output is tagged ``source="rules"`` and is
subject to the identical validation, so the enforcement path is exercised on
every run rather than only when a key happens to be present.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..core.evidence import EvidenceRegistry
from ..llm.client import LLMClient, LLMUnavailable, get_client
from ..metrics.base import MetricContext
from ..signals.base import Signal
from ..signals.engine import SignalRun, priority_score
from ..llm.blocks.resolution import RELATIONSHIP_STANCE_FA
from .quadrant import BUCKET_LABEL_FA, BUCKET_MEANING_FA, QuadrantResult
from .validate import ValidationResult, validate_action

log = logging.getLogger(__name__)

Priority = Literal["فوری", "بالا", "متوسط", "پایین"]

# Short Persian action titles per detector. The offline composer builds titles
# from this map rather than slicing a signal headline: headlines carry numbers,
# and a truncated headline both reads badly and can strand a number away from
# the evidence that supports it.
TITLE_BY_DETECTOR = {
    "cadence_breach": "سکوت خرید خارج از ریتم همیشگی مشتری",
    "volume_decline": "افت حجم خرید نسبت به روند خود مشتری",
    "volume_surge": "رشد حجم خرید — بررسی ظرفیت و اعتبار",
    "first_order_no_repeat": "خرید اول بدون تکرار — شکست در جذب",
    "mix_downgrade": "حرکت سبد خرید به سمت خانواده کالای ارزان‌تر",
    "sku_narrowing": "کاهش تنوع کد کالای خریداری‌شده",
    "price_erosion": "افت موقعیت قیمتی نسبت به بازار",
    "negative_risk_adj_margin": "حاشیه سود ریسک‌تعدیل‌شده منفی — بازنگری قرارداد",
    "margin_below_peer_cohort": "حاشیه سود پایین‌تر از همتایان هم‌بخش",
    "discount_without_return": "تخفیف داده‌شده بدون تغییر در حجم خرید",
    "dso_slippage": "کند شدن وصول نسبت به رفتار قبلی مشتری",
    "bounced_cheque": "چک برگشتی — بررسی فوری اعتبار",
    "credit_exposure": "اشغال بالای سقف اعتبار",
    "late_interest_drag": "اثر خالص مالی منفی روی حاشیه سود",
    "complaint_recurrence": "تکرار شکایت با همان مکانیزم",
    "churn_threat_language": "تهدید صریح به قطع همکاری در متن شکایت",
    "unresolved_aging": "شکایت باز و کهنه بدون رسیدگی",
    "hembaft_blast_radius": "تماس پیشدستانه — همبافت مشکوک نزد این مشتری",
    "return_rate_spike": "نرخ برگشتی بالاتر از دفتر",
    "dev_request_stalled": "درخواست توسعه معطل‌مانده",
    "wallet_headroom": "ظرفیت رشد استفاده‌نشده",
    "cross_sell_peer_gap": "فرصت فروش متقابل بر پایه همتایان",
}

OWNER_BY_DETECTOR = {
    "complaint_recurrence": "کارشناس فنی",
    "churn_threat_language": "مدیر فروش",
    "unresolved_aging": "کنترل کیفیت",
    "hembaft_blast_radius": "کارشناس فنی",
    "return_rate_spike": "کنترل کیفیت",
    "dev_request_stalled": "تحقیق‌وتوسعه",
    "bounced_cheque": "واحد مالی",
    "credit_exposure": "واحد مالی",
    "dso_slippage": "واحد مالی",
    "late_interest_drag": "واحد مالی",
}
DEFAULT_OWNER = "مدیر فروش"


@dataclass(frozen=True)
class Action:
    customer_id: str
    rank: int
    priority: Priority
    bucket: str
    title_fa: str
    rationale_fa: str
    recommended_step_fa: str
    owner: str
    evidence_ids: list[str]
    signals: list[str]
    value_at_stake: float
    source: str = "rules"
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionDraft(BaseModel):
    """What the LLM returns. Note what is *not* here: rank, priority, bucket and
    value_at_stake are all computed in Python and never asked for."""

    title_fa: str = Field(description="عنوان کوتاه اقدام، حداکثر ۱۲ کلمه")
    rationale_fa: str = Field(
        description="دلیل، با ارجاع درون‌متنی به شناسه‌های شاهد مثل [EV-...]"
    )
    recommended_step_fa: str = Field(description="یک قدم مشخص و قابل انجام")
    owner: str = Field(description="مسئول پیشنهادی")
    evidence_ids: list[str] = Field(description="فقط شناسه‌هایی که واقعاً استفاده کردی")


SYSTEM_PROMPT = """تو دستیار مدیر فروش شرکت نفیس نخ (تولیدکننده نخ POY) هستی.

برای یک مشتری، فهرستی از سیگنال‌ها و شواهد به تو داده می‌شود. وظیفه‌ات نوشتن یک اقدام
پیشنهادی کوتاه و عملی است.

قواعد سختگیرانه:
- **هیچ عددی ننویس که در متن شواهد داده‌شده نیامده باشد.** اگر عددی لازم داری، از همان
  عبارتی استفاده کن که در شاهد آمده و شناسه‌اش را ذکر کن.
- به هر ادعا، شناسه شاهد مربوطه را به شکل [EV-...] بچسبان.
- فقط از شناسه‌هایی استفاده کن که در همین ورودی آمده‌اند.
- قدم پیشنهادی باید مشخص باشد (تماس، بازدید، بازنگری قرارداد، اقدام فنی)، نه توصیه کلی.
- **قید اعتباری را رعایت کن:** اگر سقف اعتبار مشتری پر شده باشد، پیشنهاد افزایش حجم
  بدون تعیین تکلیف سقف اعتبار بی‌فایده است؛ در آن حالت قدم اول باید بازنگری سقف باشد.
- لحن: حرفه‌ای، کوتاه، بدون تعارف.
"""

USER_TEMPLATE = """مشتری: {customer_id}
دسته‌بندی: {bucket_label} — {bucket_meaning}
دلیل دسته‌بندی: {bucket_reason}
وضعیت اعتباری: {credit_note}
سابقه رسیدگی به شکایات: {stance_note}
پرونده باز: {investigation_note}

سیگنال‌های فعال‌شده (به ترتیب اهمیت):
{signal_block}

شواهد در دسترس (فقط از همین‌ها استفاده کن):
{evidence_block}
"""


# ---------------------------------------------------------------- credit gate
# A growth recommendation is only actionable if the customer is financially
# *permitted* to buy more. Selling volume into a maxed-out credit limit produces
# an order the finance department blocks, so credit room decides the shape of the
# step, not the priority: ranking stays pure arithmetic over signals.
#
# Credit_Limit is NOT used as a capacity anchor for headroom — against lifetime
# revenue it is spearman +0.900 / pearson −0.031, i.e. a monotone re-encoding of
# what the customer already buys, which adds nothing to an estimate built from
# the same quantity (PLAN §5.4). What it does carry is the *residual*: how much
# more they are allowed to buy.
CREDIT_NOTE_FA = {
    "open": "فضای اعتباری باقی مانده است؛ پیشنهاد افزایش حجم قابل اجراست.",
    "exhausted": (
        "سقف اعتبار عملاً پر شده است؛ هر پیشنهاد رشد باید مشروط به بازنگری سقف "
        "اعتبار باشد، وگرنه سفارش در واحد مالی متوقف می‌شود."
    ),
    "unknown": "دادهٔ سقف اعتبار برای این مشتری قابل اتکا نیست؛ روی آن حساب نکن.",
}

# Steps that replace the bucket default when credit is the binding constraint.
CREDIT_BLOCKED_STEP_FA = {
    "grow": (
        "پیش از هر پیشنهاد حجم، افزایش سقف اعتبار با واحد مالی تعیین تکلیف شود؛ "
        "سفارش جدید تا آن زمان ثبت نشود."
    ),
    "protect": (
        "پیش از تمدید سفارش‌های جاری، وضعیت سقف اعتبار با واحد مالی تعیین تکلیف شود."
    ),
}


# ------------------------------------------------- the open-investigation gate
# Same shape as the credit gate, and for the same reason: a step the customer
# cannot act on is not a step. Meeting a customer while their own complaint file
# sits waiting on a sample we never chased wastes the meeting and damages the
# relationship — the file has to be closed first, then the meeting happens.
INVESTIGATION_NOTE_FA = {
    "pending": (
        "پروندهٔ شکایت این مشتری هنوز باز است و منتظر نمونه یا آزمون تکمیلی مانده؛ "
        "هر جلسه یا پیشنهادی باید *بعد از* تعیین تکلیف آن پرونده انجام شود."
    ),
    "clear": "پروندهٔ شکایت بازی که مانع گفتگو باشد وجود ندارد.",
}

INVESTIGATION_BLOCKED_STEP_FA = (
    "ابتدا پروندهٔ شکایت {ids} که {days} روز منتظر نمونه یا آزمون تکمیلی مانده با "
    "کنترل کیفیت تعیین تکلیف شود؛ جلسه یا پیشنهاد بعدی پس از بستن آن پرونده."
)


def investigation_state(ctx: MetricContext, customer_id: str) -> dict:
    """``pending``/``clear`` plus the ids and age driving it."""
    from ..llm.blocks.resolution import customer_state

    info = customer_state(ctx, customer_id)
    info["state"] = "pending" if info["pending"] else "clear"
    return info


def credit_state(ctx: MetricContext, customer_id: str) -> str:
    """``open`` · ``exhausted`` · ``unknown`` — see :data:`CREDIT_NOTE_FA`."""
    try:
        row = ctx.row("payment", customer_id)
    except KeyError:
        return "unknown"
    if row is None or "credit_room_state" not in row:
        return "unknown"
    state = row["credit_room_state"]
    return state if state in CREDIT_NOTE_FA else "unknown"


def _priority(score: float, thresholds: tuple[float, float, float]) -> Priority:
    hi, mid, lo = thresholds
    if score >= hi:
        return "فوری"
    if score >= mid:
        return "بالا"
    if score >= lo:
        return "متوسط"
    return "پایین"


def _owner_for(signals: list[Signal]) -> str:
    for s in signals:
        if s.detector in OWNER_BY_DETECTOR:
            return OWNER_BY_DETECTOR[s.detector]
    return DEFAULT_OWNER


def _evidence_block(registry: EvidenceRegistry, evidence_ids: list[str]) -> str:
    lines = []
    for ev in registry.many(evidence_ids):
        suffix = ""
        if ev.confidence < 1.0:
            suffix = f"  (اطمینان {ev.confidence:.1f}"
            if ev.provenance.get("assumption"):
                suffix += "، مبتنی بر فرض"
            suffix += ")"
        lines.append(f"[{ev.id}] {ev.claim_fa}{suffix}")
    return "\n".join(lines)


def _signal_block(signals: list[Signal]) -> str:
    return "\n".join(
        f"- {s.detector} (شدت {s.severity:.0f}): {s.headline_fa}" for s in signals
    )


def compose_offline(
    customer_id: str, signals: list[Signal], registry: EvidenceRegistry,
    bucket: str, bucket_reason: str, credit: str = "unknown",
    investigation: dict | None = None,
) -> ActionDraft:
    """Deterministic Persian composer used when no model is available.

    It states the top signals and cites their evidence verbatim — no numbers of
    its own, which is exactly what the validator will check.
    """
    top = signals[0]
    # Every evidence id belonging to the signals we actually reference is
    # declared — not a truncated prefix. Truncating strands the numbers used in
    # the title away from the evidence that supports them, which the validator
    # correctly rejects.
    seen, ordered = set(), []
    for s in signals[:3]:
        for e in s.evidence_ids:
            if e not in seen:
                seen.add(e)
                ordered.append(e)

    claims = [f"{ev.claim_fa} [{ev.id}]" for ev in registry.many(ordered[:4])]
    step = {
        "grow": "تماس فروش برای پیشنهاد افزایش حجم روی خانواده‌های کالای پیشنهادی.",
        "protect": "تماس نگهداشت و بررسی وضعیت سفارش‌های جاری با مشتری.",
        "fix": "بازنگری شرایط قرارداد (قیمت، شرایط پرداخت) با حضور مدیر فروش.",
        "reduce": "توقف پیشنهادهای ویژه؛ ادامه همکاری فقط با شرایط استاندارد.",
    }[bucket]
    owner = _owner_for(signals)
    # fix/reduce are unaffected: neither asks the customer to buy more, so credit
    # room is not the lever there.
    if credit == "exhausted" and bucket in CREDIT_BLOCKED_STEP_FA:
        step = CREDIT_BLOCKED_STEP_FA[bucket]
        owner = "واحد مالی و مدیر فروش"
    # An open investigation outranks the credit gate: credit decides whether the
    # customer *may* buy more, the open file decides whether the conversation can
    # usefully happen at all.
    if investigation and investigation.get("state") == "pending":
        step = INVESTIGATION_BLOCKED_STEP_FA.format(
            ids="، ".join(investigation["pending_ids"][:3]),
            days=investigation.get("oldest_pending_days") or 0,
        )
        owner = "کنترل کیفیت و مدیر فروش"
        # the day count in that sentence comes from the pending evidence, so the
        # evidence has to be declared or the validator will (correctly) drop it
        for eid in investigation.get("pending_evidence_ids", []):
            if eid not in seen:
                seen.add(eid)
                ordered.append(eid)

    title = TITLE_BY_DETECTOR.get(top.detector, top.detector)
    return ActionDraft(
        title_fa=f"{BUCKET_LABEL_FA[bucket]} — {title}",
        rationale_fa=" ".join(claims) if claims else top.headline_fa,
        recommended_step_fa=step,
        owner=owner,
        evidence_ids=ordered,
    )


@dataclass
class ActionQueue:
    actions: list[Action]
    as_of: date
    dropped: list[dict[str, Any]] = field(default_factory=list)
    quadrant_counts: dict[str, int] = field(default_factory=dict)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([a.to_dict() for a in self.actions])

    def dump_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps({
            "as_of": self.as_of.isoformat(),
            "quadrant_counts": self.quadrant_counts,
            "n_actions": len(self.actions),
            "n_dropped": len(self.dropped),
            "dropped": self.dropped,
            "actions": [a.to_dict() for a in self.actions],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def to_brief_fa(self, settings: Settings, top_n: int | None = None) -> str:
        """A readable Persian brief for the sales manager."""
        top_n = top_n or settings.top_n_actions
        out = [
            "صف اقدام — نفیس نخ",
            f"تاریخ مبنا: {self.as_of.isoformat()}",
            "=" * 66,
            "دسته‌بندی مشتریان: "
            + " · ".join(
                f"{BUCKET_LABEL_FA.get(k, k)} {v}" for k, v in sorted(self.quadrant_counts.items())
            ),
            f"اقدام‌های پیشنهادی: {len(self.actions)}"
            + (f" (رد شده در اعتبارسنجی: {len(self.dropped)})" if self.dropped else ""),
            "",
        ]
        for a in self.actions[:top_n]:
            out += [
                f"{a.rank}. [{a.priority}] {a.customer_id} — {BUCKET_LABEL_FA.get(a.bucket, a.bucket)}",
                f"   {a.title_fa}",
                f"   چرا: {a.rationale_fa}",
                f"   قدم بعدی: {a.recommended_step_fa}   (مسئول: {a.owner})",
                f"   سیگنال‌ها: {', '.join(a.signals)}",
                "",
            ]
        return "\n".join(out)


def build_actions(
    ctx: MetricContext,
    run: SignalRun,
    quadrants: QuadrantResult,
    *,
    client: LLMClient | None = None,
    top_n: int | None = None,
    allow_offline: bool = True,
    weights: dict[str, float] | None = None,
) -> ActionQueue:
    st = ctx.settings
    client = client or get_client(st)
    # the weights the run was ranked with, unless the caller overrides them
    weights = weights if weights is not None else run.weights
    by_customer = run.by_customer()

    # rank customers by their best signal's priority score — Python, not the LLM
    ranked = sorted(
        by_customer.items(),
        key=lambda kv: max(priority_score(s, st, weights) for s in kv[1]),
        reverse=True,
    )
    # Priority bands are computed over the WHOLE book, before truncation.
    # Deriving them from the top-N would relabel the same customer "پایین" just
    # because the caller asked for five rows instead of fifty.
    all_scores = [max(priority_score(s, st, weights) for s in sigs) for _, sigs in ranked]
    series = pd.Series(all_scores) if all_scores else pd.Series([0.0])
    thresholds = (
        float(series.quantile(0.90)),
        float(series.quantile(0.60)),
        float(series.quantile(0.30)),
    )

    limit = top_n if top_n is not None else st.top_n_actions
    ranked = ranked[:limit] if limit else ranked

    actions: list[Action] = []
    dropped: list[dict[str, Any]] = []

    for rank, (cid, signals) in enumerate(ranked, start=1):
        signals = sorted(signals, key=lambda s: priority_score(s, st, weights), reverse=True)
        bucket = quadrants.bucket_of(cid) or "protect"
        bucket_reason = (
            quadrants.table.loc[cid, "bucket_reason_fa"]
            if cid in quadrants.table.index else ""
        )
        available_ids = [e.id for e in ctx.evidence.for_customer(cid)]
        credit = credit_state(ctx, cid)
        investigation = investigation_state(ctx, cid)
        user = USER_TEMPLATE.format(
            customer_id=cid,
            bucket_label=BUCKET_LABEL_FA[bucket],
            bucket_meaning=BUCKET_MEANING_FA[bucket],
            bucket_reason=bucket_reason,
            credit_note=CREDIT_NOTE_FA[credit],
            investigation_note=INVESTIGATION_NOTE_FA[investigation["state"]],
            stance_note=RELATIONSHIP_STANCE_FA[investigation["stance"]],
            signal_block=_signal_block(signals),
            evidence_block=_evidence_block(ctx.evidence, available_ids),
        )
        fallback = (
            (lambda: compose_offline(cid, signals, ctx.evidence, bucket,
                                     bucket_reason, credit, investigation))
            if allow_offline else None
        )

        draft, source, result = None, "rules", None
        for attempt in range(2):
            try:
                llm_result = client.structured(
                    SYSTEM_PROMPT,
                    user if attempt == 0 else f"{user}\n\n{result.complaint_fa()}",
                    ActionDraft, fallback=fallback,
                )
            except LLMUnavailable:
                dropped.append({"customer_id": cid, "reason": "no_llm_and_no_fallback"})
                draft = None
                break
            draft, source = llm_result.value, llm_result.source
            candidate = _to_action(cid, rank, draft, bucket, signals, thresholds, st,
                                   source, weights, credit, investigation)
            result = validate_action(candidate, ctx.evidence)
            if result.ok:
                actions.append(candidate)
                break
            log.warning(
                "action for %s failed validation (attempt %d): %s",
                cid, attempt + 1, [i.code for i in result.issues],
            )
            if attempt == 1 or source == "rules":
                # a rules draft is deterministic — retrying it changes nothing
                dropped.append({
                    "customer_id": cid,
                    "reason": "validation_failed",
                    "issues": [{"code": i.code, "detail": i.detail} for i in result.issues],
                })
                draft = None
                break

    for i, a in enumerate(actions, start=1):
        object.__setattr__(a, "rank", i)

    return ActionQueue(
        actions=actions, as_of=ctx.as_of, dropped=dropped,
        quadrant_counts=quadrants.counts(),
    )


def _to_action(
    cid: str, rank: int, draft: ActionDraft, bucket: str, signals: list[Signal],
    thresholds, settings: Settings, source: str,
    weights: dict[str, float] | None = None, credit: str = "unknown",
    investigation: dict | None = None,
) -> Action:
    score = max(priority_score(s, settings, weights) for s in signals)
    return Action(
        customer_id=cid,
        rank=rank,
        priority=_priority(score, thresholds),
        bucket=bucket,
        title_fa=draft.title_fa,
        rationale_fa=draft.rationale_fa,
        recommended_step_fa=draft.recommended_step_fa,
        owner=draft.owner or _owner_for(signals),
        evidence_ids=list(draft.evidence_ids),
        signals=[s.detector for s in signals],
        value_at_stake=float(max(s.value_at_stake for s in signals)),
        source=source,
        detail={
            "priority_score": round(score, 2),
            "credit_room": credit,
            "open_investigation": (investigation or {}).get("state", "clear"),
            "relationship_stance": (investigation or {}).get("stance", "neutral"),
        },
    )
