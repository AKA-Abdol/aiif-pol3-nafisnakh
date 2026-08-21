"""The seven agents and the conditions that wake them (PLAN §3.10).

Each trigger is **pure Python over metric tables and signals** — no model decides
whether an agent runs. That is what keeps the cost of a meeting predictable and
the routing auditable: `nafisnakh meeting` prints, for every agent, either the
sentence that woke it or the sentence that says why it stayed asleep.

The division of labour is by *question*, not by data source, and the questions
deliberately overlap in their inputs. The complaints sheet feeds both `risk` and
`relationship`, because "what threatens this account" and "what tone do we walk
in with" are different questions with different answers, and one analyst covering
both would collapse them. Each agent carries a ``forbidden_fa`` line naming the
claim it must not make — which is where the dataset's own limits are enforced at
the prompt, not just in review.
"""

from __future__ import annotations

import pandas as pd

from ..metrics.base import MetricContext
from .base import AgentSpec, Trigger, register

OPEN_LOOP_DETECTORS = {
    "dev_sample_ready_no_offer", "dev_rejected_uncommunicated",
    "crm_promise_outstanding", "offer_negotiation_stalled", "dev_request_stalled",
}
PRICE_DETECTORS = {
    "price_erosion", "margin_below_peer_cohort", "discount_without_return",
    "negative_risk_adj_margin", "mix_downgrade",
}
PAYMENT_DETECTORS = {
    "dso_slippage", "bounced_cheque", "credit_exposure", "late_interest_drag",
}


def _fired(signals, names) -> list:
    return [s for s in signals if s.detector in names]


def _row(ctx: MetricContext, table: str, cid: str):
    t = ctx.tables.get(table)
    if t is None or cid not in t.index:
        return None
    return t.loc[cid]


def _n(row, key, default=0.0) -> float:
    if row is None or key not in row:
        return default
    v = row[key]
    return default if pd.isna(v) else float(v)


# --------------------------------------------------------------------- agents
def _open_loops_trigger(ctx, cid, signals):
    loops = _row(ctx, "open_loops", cid)
    count = _n(loops, "open_loop_count")
    hits = _fired(signals, OPEN_LOOP_DETECTORS)
    if not count and not hits:
        return None
    kinds = [
        label for label, open_ in (
            ("نمونه تأییدشده بدون آفر", _n(loops, "dev_approved_open") > 0),
            ("رد فنی اعلام‌نشده", _n(loops, "dev_rejected_unspoken") > 0),
            ("اقدام بعدی معلق", bool(loops is not None and loops.get("next_action_open"))),
            ("آفر رهاشده", _n(loops, "offers_abandoned") > 0),
        ) if open_
    ]
    return Trigger(
        reason_fa=("حلقه‌های باز از سمت ما: " + "، ".join(kinds)) if kinds
        else "آشکارسازهای حلقه باز روی این مشتری فعال شده‌اند.",
        weight=1.3, detail={"kinds": kinds, "count": count},
    )


register(AgentSpec(
    name="open_loops",
    question_fa="چه چیزی از سمت ما نیمه‌کاره مانده و پیش از هر پیشنهاد تازه باید بسته شود؟",
    role_fa=("تو مسئول پیگیری تعهدات انجام‌نشده نفیس نخ هستی — نمونه تأییدشده‌ای که "
             "قیمت نگرفته، پاسخ ردی که به مشتری نرسیده، قولی که در CRM ثبت شده و "
             "انجام نشده، آفری که بی‌پاسخ مانده."),
    tools=("get_dev_requests", "get_crm_promises", "get_offer_history"),
    trigger=_open_loops_trigger,
    forbidden_fa=("هرگز نگو مشتری بی‌تفاوت یا بی‌پاسخ بوده مگر شاهدی همین را بگوید؛ "
                  "این حوزه دربارهٔ کار ماست، نه رفتار مشتری."),
))


def _risk_trigger(ctx, cid, signals):
    hits = [s for s in signals if s.category == "risk"]
    qual = _row(ctx, "quality", cid)
    escapes = _n(qual, "lab_escape_lines") + _n(qual, "hembaft_at_risk_lines")
    if not hits and not escapes:
        return None
    top = max(hits, key=lambda s: s.severity, default=None)
    return Trigger(
        reason_fa=(f"{len(hits)} سیگنال ریسک فعال است"
                   + (f"؛ شدیدترین: {top.headline_fa}" if top else "")
                   + ("؛ و لات‌های در معرض خطر ثبت شده است." if escapes else ".")),
        weight=1.4 if escapes else 1.2,
        detail={"n_risk_signals": len(hits), "exposed_lines": escapes},
    )


register(AgentSpec(
    name="risk",
    question_fa="چه چیزی همین حالا این رابطه یا این محموله را تهدید می‌کند؟",
    role_fa=("تو مسئول تشخیص خطرهای فعال روی این پرونده‌ای: شکایت باز، پروندهٔ "
             "بررسی‌نشده، لات مشکوکی که ارسال شده و هنوز شکایتی رویش نیست."),
    tools=("get_complaints", "get_lab_band_position", "get_crm_promises"),
    trigger=_risk_trigger,
    forbidden_fa=("شکایتی را با اعداد آزمون آزمایشگاهی توضیح نده؛ در این دفتر بین "
                  "مقادیر آزمون و بروز شکایت رابطه‌ای اندازه‌گیری نشده است."),
))


def _opportunity_trigger(ctx, cid, signals):
    """Don't re-test what a calibrated detector already tests.

    Raw ``headroom_value`` is a peer-capacity estimate, positive for nearly the
    whole book — triggering on it wakes everyone. ``wallet_headroom`` is the
    *calibrated* version of that same question (profitable **and** under a third
    of peer purchase level) and fires on 38%. So the trigger is the opportunity
    signals themselves, plus one state no detector covers: an approved sample
    that has never been priced, which is growth already paid for.
    """
    hits = [s for s in signals if s.category == "opportunity"]
    loops = _row(ctx, "open_loops", cid)
    unsold_sample = _n(loops, "dev_approved_open") > 0
    if not hits and not unsold_sample:
        return None
    return Trigger(
        reason_fa=(f"{len(hits)} سیگنال فرصت فعال است." if hits
                   else "نمونه‌ای تأیید شده و هرگز قیمت نگرفته — رشدی که هزینه‌اش "
                        "قبلاً پرداخت شده است."),
        weight=1.0,
        detail={"n_opportunity_signals": len(hits), "unsold_sample": unsold_sample},
    )


register(AgentSpec(
    name="opportunity",
    question_fa="کجای این حساب جای رشد دارد و چه چیزی را باید پیشنهاد داد؟",
    role_fa=("تو مسئول یافتن فرصت رشد روی این حساب هستی: فاصله تا همتایان، خانواده "
             "کالایی که نمی‌خرد، نمونه‌ای که تأیید شده و هنوز به فروش نرسیده."),
    tools=("get_peer_comparison", "get_offer_history", "get_dev_requests"),
    trigger=_opportunity_trigger,
    forbidden_fa=("ادعا نکن تخفیف یا نوع آفر باعث پذیرش یا رد شده؛ در این دفتر شیت "
                  "آفرها هیچ ارتباطی با نتیجه ندارد."),
))


def _financial_trigger(ctx, cid, signals):
    from ..aggregate.aggregator import credit_state

    pay = _row(ctx, "payment", cid)
    state = credit_state(ctx, cid)
    hits = _fired(signals, PAYMENT_DETECTORS)
    # Every customer has a payment row, so "has payment data" wakes everyone and
    # decides nothing. The financial analyst is woken when there is something to
    # settle: the credit line is not simply open, a payment detector fired, the
    # line is already heavily occupied, or slow payment is eating the margin.
    heavy = _n(pay, "exposure_ratio") >= ctx.settings.credit_exposure_ratio / 2
    bleeding = _n(pay, "net_finance_effect") < 0
    if state == "open" and not hits and not heavy and not bleeding:
        return None
    blocking = state == "exhausted"
    reason = {
        "exhausted": "سقف اعتبار این مشتری پر شده است — هر پیشنهاد افزایش حجم مشروط است.",
        "open": "وضعیت اعتباری باز است؛ بررسی مالی برای تأیید شرایط.",
        "unknown": "سقف اعتبار این مشتری قابل ارزیابی نیست.",
    }[state]
    if hits:
        reason += f" {len(hits)} سیگنال مالی فعال است."
    elif bleeding:
        reason += " اثر خالص مالی این حساب منفی است."
    elif heavy:
        reason += " بخش قابل‌توجهی از سقف اعتبار اشغال شده است."
    return Trigger(reason_fa=reason, weight=1.5 if blocking else 1.1,
                   blocking=blocking,
                   detail={"credit_state": state, "heavy": heavy, "bleeding": bleeding})


register(AgentSpec(
    name="financial",
    question_fa="از نظر مالی اصلاً می‌شود جلو رفت، و با چه شرطی؟",
    role_fa=("تو مسئول تعیین تکلیف مالی این پرونده‌ای: مانده باز، اشغال سقف اعتبار، "
             "سرعت وصول و چک برگشتی."),
    tools=("get_payment_state",),
    trigger=_financial_trigger,
    forbidden_fa=("سقف اعتبار و مانده را از هم کم نکن؛ این دو در این دفتر دو مقیاس "
                  "متفاوت دارند و فقط نسبت اشغال معنا دارد."),
))


def _relationship_trigger(ctx, cid, signals):
    """Tone is a decision only where there is tension.

    "Has ever had a CRM call" is true of 96% of the book and settles nothing. The
    tone of the next conversation is genuinely in question when a complaint is
    open, when one was **rejected** — we told them they were wrong, the highest
    tension a file can carry — when an investigation is still running, or when the
    resolution history has already produced a stance.
    """
    from ..aggregate.aggregator import investigation_state

    qual = _row(ctx, "quality", cid)
    open_ = _n(qual, "complaints_open")
    rejected = _n(qual, "complaints_rejected")
    recurrences = _n(qual, "complaint_recurrences")
    info = investigation_state(ctx, cid)
    stance = info.get("stance", "neutral")
    pending = bool(info.get("pending"))
    if not (open_ or rejected or recurrences or pending or stance != "neutral"):
        return None
    parts = []
    if rejected:
        parts.append("شکایتی از این مشتری رد شده است")
    if open_:
        parts.append("پروندهٔ شکایت باز دارد")
    if recurrences:
        parts.append("شکایت تکراری ثبت شده است")
    if pending:
        parts.append("بررسی هنوز تمام نشده است")
    if stance != "neutral":
        parts.append(f"موضع پیشنهادی از سابقهٔ بررسی‌ها: {stance}")
    return Trigger(
        reason_fa="لحن ورود تعیین تکلیف می‌خواهد — " + "، ".join(parts) + ".",
        weight=1.2 if (rejected or pending) else 1.1,
        detail={"open": open_, "rejected": rejected, "pending": pending,
                "stance": stance},
    )


register(AgentSpec(
    name="relationship",
    question_fa="با چه لحنی باید وارد این گفتگو شد، و اول چه چیزی را باید گفت؟",
    role_fa=("تو مسئول تعیین لحن و ترتیب گفتگو با این مشتری هستی: کجا باید عذرخواهی "
             "کرد، کجا نباید، و کدام موضوع باید اول مطرح شود."),
    tools=("get_complaints", "get_crm_promises"),
    trigger=_relationship_trigger,
    forbidden_fa=("اگر نتیجه بررسی شکایتی هنوز قابل‌دانستن نیست، دربارهٔ مقصر بودن یا "
                  "نبودن اظهار نظر نکن."),
))


def _pricing_trigger(ctx, cid, signals):
    hits = _fired(signals, PRICE_DETECTORS)
    loops = _row(ctx, "open_loops", cid)
    # Having ever been sent an offer is not a pricing question. There is one when
    # a price or margin detector fired, or when an offer is sitting unanswered —
    # because the next thing we do about that offer is a pricing decision.
    abandoned = _n(loops, "offers_abandoned")
    if not hits and abandoned <= 0:
        return None
    return Trigger(
        reason_fa=(f"{len(hits)} سیگنال قیمت و حاشیه سود فعال است."
                   if hits else "آفر بی‌پاسخ و گذشته از مهلت دارد؛ ادامهٔ آن یک "
                                "تصمیم قیمتی است."),
        weight=1.2 if hits else 0.9,
        detail={"n_price_signals": len(hits), "abandoned_offers": abandoned},
    )


register(AgentSpec(
    name="pricing",
    question_fa="قیمت این مشتری کجای دفتر ایستاده و پیشنهاد بعدی با چه منطقی بسته شود؟",
    role_fa=("تو مسئول جایگاه قیمتی این حساب هستی: قیمت تورم‌زدوده در برابر همتایان، "
             "حاشیه سود ریسک‌تعدیل‌شده، و سابقهٔ آفرهایی که داده‌ایم."),
    tools=("get_peer_comparison", "get_offer_history", "get_market_context"),
    trigger=_pricing_trigger,
    forbidden_fa=("قیمت مطلق را مقایسه نکن؛ در این دفتر تقریباً همه قیمت‌ها صعودی‌اند "
                  "و آن تورم است، نه سیگنال. گزارش بازار هم دربارهٔ خانواده کالاست، "
                  "نه دربارهٔ این مشتری."),
))


def _supply_trigger(ctx, cid, signals):
    eng = _row(ctx, "engagement", cid)
    loops = _row(ctx, "open_loops", cid)
    total = _n(eng, "dev_requests_total")
    if total <= 0:
        return None
    return Trigger(
        reason_fa=(f"این مشتری درخواست توسعه ثبت کرده است"
                   + ("؛ از جمله موردی که تأیید شده و هنوز آفری نگرفته."
                      if _n(loops, "dev_approved_open") > 0 else ".")),
        weight=1.0, detail={"dev_requests": total},
    )


register(AgentSpec(
    name="supply_feasibility",
    question_fa="آنچه این مشتری خواسته اصلاً شدنی است، و اگر هست قدم فنی بعدی چیست؟",
    role_fa=("تو مسئول امکان‌سنجی فنی خواسته‌های این مشتری هستی: وضعیت درخواست‌های "
             "توسعه و آنچه آزمون‌های لات دربارهٔ آنچه واقعاً تولید کرده‌ایم می‌گویند."),
    tools=("get_dev_requests", "get_lab_band_position"),
    trigger=_supply_trigger,
    forbidden_fa=("متن نتیجه (Outcome_Text) درخواست توسعه را مبنا نگیر؛ در این شیت با "
                  "وضعیت هم‌بسته نیست. فقط وضعیت و تاریخ تصمیم معتبرند."),
))
