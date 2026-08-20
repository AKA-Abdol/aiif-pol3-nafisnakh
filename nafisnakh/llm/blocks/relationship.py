"""Per-customer relationship synthesis (PLAN §3.2, Phase 2).

The complaint block reads one document. This block reads the *relationship*: the
signals that fired, the evidence behind them, what the CRM log says the customer
keeps calling about, which mechanisms keep failing on their material, and what
we promised and did not deliver.

What it adds that the metric layer cannot: the metric layer knows an R&D request
has been open 250 days and that the customer calls about quality more than about
price. It does not know that those two facts together mean *we owe this customer
something and they are being patient about it* — which changes how the sales
manager should open the call.

Same discipline as everywhere else in this package:

* the model is handed **evidence claims and ids only**, never a dataframe;
* it is asked for judgement and tone, never for a number;
* offline it falls back to a deterministic composer tagged ``source="rules"``,
  and the tag travels into the evidence confidence;
* it runs **only for customers that already triggered a signal**, so the cost is
  bounded by the queue, not by the size of the book.
"""

from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ...config import Settings, get_settings
from ...io import schema as S
from ..client import LLMClient, LLMUnavailable, get_client
from ..taxonomy import mechanism_label

log = logging.getLogger(__name__)

Health = Literal["سالم", "شکننده", "در معرض خطر", "بحرانی"]

# What the CRM interaction mix says the relationship is mostly about. These are
# the seven `Interaction_Type` values, condensed into the four things a sales
# manager can actually act on.
THEME_BY_INTERACTION = {
    "قیمت و تخفیف": "گفت‌وگوی قیمتی",
    "کیفیت محصول": "کیفیت",
    "خدمات فنی": "کیفیت",
    "نمونه محصول": "توسعه محصول",
    "وصول مطالبات": "مالی",
    "پیگیری سفارش": "تحویل",
    "برنامه خرید": "برنامه‌ریزی خرید",
}


class RelationshipSynthesis(BaseModel):
    """What the model must return for one customer."""

    health: Health = Field(description="وضعیت کلی رابطه")
    health_confidence: float = Field(ge=0.0, le=1.0)
    dominant_theme_fa: str = Field(
        description="این رابطه بیشتر حول چه موضوعی می‌چرخد — کیفیت، قیمت، مالی، تحویل"
    )
    unmet_promises_fa: list[str] = Field(
        default_factory=list,
        description="چیزهایی که به این مشتری قول داده‌ایم و انجام نشده",
    )
    customer_priorities_fa: list[str] = Field(
        default_factory=list, description="آنچه برای این مشتری اهمیت دارد"
    )
    recommended_tone_fa: str = Field(
        description="مدیر فروش با چه لحنی وارد گفت‌وگو شود"
    )
    watch_items_fa: list[str] = Field(
        default_factory=list, description="چیزهایی که باید زیر نظر بمانند"
    )
    summary_fa: str = Field(description="دو جمله برای مدیر فروش")


SYSTEM_PROMPT = """تو دستیار مدیر فروش شرکت نفیس نخ هستی.

برای یک مشتری، سیگنال‌های فعال‌شده، شواهد، و خلاصه تعامل‌ها به تو داده می‌شود.
وظیفه‌ات جمع‌بندی *کیفیت رابطه* است، نه تکرار اعداد.

قواعد سختگیرانه:
- **هیچ عددی ننویس.** اعداد در شواهد هستند و جای دیگری استفاده می‌شوند؛ تو فقط قضاوت
  کیفی می‌نویسی.
- unmet_promises_fa فقط چیزهایی است که از سمت ما معطل مانده (درخواست توسعه بی‌پاسخ،
  شکایت باز، نمونه ارسال‌نشده) — نه گلایه عمومی.
- health را با احتیاط انتخاب کن: «بحرانی» فقط وقتی که رابطه واقعاً در آستانه قطع است.
- لحن پیشنهادی باید عملی باشد (مثلاً «عذرخواهی بابت تأخیر فنی، بعد گفت‌وگوی حجم»).
"""

USER_TEMPLATE = """مشتری: {customer_id}
دسته‌بندی: {bucket}

سیگنال‌های فعال‌شده:
{signal_block}

شواهد (فقط برای درک وضعیت — عدد از اینها در خروجی تو نمی‌آید):
{evidence_block}

الگوی تعامل‌های CRM: {interaction_mix}
مکانیزم‌های شکایت تکرارشونده: {mechanisms}
درخواست‌های توسعه باز: {open_requests}
"""


# ----------------------------------------------------------------- rule path
def rule_synthesis(
    *,
    signals: list,
    themes: dict[str, int],
    mechanisms: list[str],
    open_requests: int,
    oldest_request_days: float | None,
    open_complaints: int,
    bucket: str,
) -> RelationshipSynthesis:
    """Deterministic fallback. Judgement by rule, and labelled as such."""
    detectors = {s.detector for s in signals}
    severity = max((s.severity for s in signals), default=0.0)

    if "churn_threat_language" in detectors:
        health: Health = "بحرانی"
    elif severity >= 80 or "complaint_recurrence" in detectors:
        health = "در معرض خطر"
    elif severity >= 50 or open_complaints:
        health = "شکننده"
    else:
        health = "سالم"

    dominant = max(themes, key=themes.get) if themes else "نامشخص"

    promises = []
    if open_requests:
        promises.append(
            "درخواست توسعه باز بدون تصمیم"
            + (" و بسیار قدیمی" if (oldest_request_days or 0) > 180 else "")
        )
    if open_complaints:
        promises.append("شکایت باز بدون جمع‌بندی")
    if "hembaft_blast_radius" in detectors:
        promises.append("اطلاع‌رسانی پیشدستانه درباره همبافت مشکوک انجام نشده")

    priorities = []
    if mechanisms:
        priorities.append("کیفیت — " + "، ".join(mechanism_label(m) for m in mechanisms[:3]))
    if "قیمت و تخفیف" in themes:
        priorities.append("قیمت و شرایط پرداخت")
    if "پیگیری سفارش" in themes:
        priorities.append("زمان‌بندی تحویل")

    tone = {
        "بحرانی": "ابتدا عذرخواهی و تعهد زمان‌دار فنی، بعد هر گفت‌وگوی تجاری.",
        "در معرض خطر": "شروع با رسیدگی به مشکل باز، سپس بررسی برنامه خرید.",
        "شکننده": "گفت‌وگوی نگهداشت؛ پیش از پیشنهاد جدید، وضعیت موارد باز روشن شود.",
        "سالم": "گفت‌وگوی عادی فروش؛ فضا برای پیشنهاد وجود دارد.",
    }[health]

    watch = sorted(detectors)[:4]
    return RelationshipSynthesis(
        health=health,
        health_confidence=0.5,
        dominant_theme_fa=dominant,
        unmet_promises_fa=promises,
        customer_priorities_fa=priorities,
        recommended_tone_fa=tone,
        watch_items_fa=watch,
        summary_fa=(
            f"رابطه در وضعیت «{health}» است و بیشتر حول «{dominant}» می‌چرخد. "
            + (f"{len(promises)} مورد از سمت ما معطل مانده است." if promises
               else "موردی از سمت ما معطل نمانده است.")
        ),
    )


# ------------------------------------------------------------------- the block
def _customer_context(ctx, customer_id: str) -> dict:
    """Everything the block needs about one customer, from the metric layer."""
    from ...core.spine import visible

    crm = visible(ctx.ds.crm_latest, ctx.as_of)
    crm = crm.loc[crm[S.CUSTOMER_ID] == customer_id]
    themes: dict[str, int] = {}
    for itype, count in crm[S.X_TYPE].value_counts().items():
        theme = THEME_BY_INTERACTION.get(itype, itype)
        themes[theme] = themes.get(theme, 0) + int(count)

    mechanisms: list[str] = []
    llm_table = ctx.tables.get("llm_complaints")
    if llm_table is not None and len(llm_table) and customer_id in llm_table.index:
        rows = llm_table.loc[[customer_id]]
        counts = rows["mechanism"].value_counts()
        mechanisms = [m for m, n in counts.items() if n >= 2] or list(counts.index[:2])

    eng = ctx.tables.get("engagement")
    qual = ctx.tables.get("quality")
    open_requests = int(eng.loc[customer_id, "dev_requests_open"]) if (
        eng is not None and customer_id in eng.index) else 0
    oldest = (
        eng.loc[customer_id, "dev_request_oldest_open_days"]
        if eng is not None and customer_id in eng.index else None
    )
    open_complaints = int(qual.loc[customer_id, "complaints_open"]) if (
        qual is not None and customer_id in qual.index) else 0

    return {
        "themes": themes,
        "mechanisms": mechanisms,
        "open_requests": open_requests,
        "oldest_request_days": None if oldest is None or pd.isna(oldest) else float(oldest),
        "open_complaints": open_complaints,
    }


def synthesise_one(
    ctx, customer_id: str, signals: list, bucket: str,
    *, client: LLMClient, allow_rules: bool = True,
):
    info = _customer_context(ctx, customer_id)
    evidence = ctx.evidence.for_customer(customer_id)
    user = USER_TEMPLATE.format(
        customer_id=customer_id,
        bucket=bucket,
        signal_block="\n".join(
            f"- {s.detector}: {s.headline_fa}" for s in signals
        ) or "—",
        evidence_block="\n".join(f"[{e.id}] {e.claim_fa}" for e in evidence[:14]) or "—",
        interaction_mix=", ".join(f"{k}×{v}" for k, v in info["themes"].items()) or "—",
        mechanisms=", ".join(mechanism_label(m) for m in info["mechanisms"]) or "—",
        open_requests=info["open_requests"],
    )
    fallback = (
        (lambda: rule_synthesis(signals=signals, bucket=bucket, **info))
        if allow_rules else None
    )
    return client.structured(SYSTEM_PROMPT, user, RelationshipSynthesis, fallback=fallback)


def attach_to_context(
    ctx,
    run,
    quadrants=None,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    allow_rules: bool = True,
    top_n: int | None = None,
):
    """Run the block for triggered customers and register ``relationship``.

    ``top_n`` bounds the cost the same way the aggregator does: the synthesis is
    only useful for the accounts that are actually going to be worked.
    """
    st = settings or ctx.settings
    client = client or get_client(st)
    from ...signals.engine import priority_score

    by_customer = run.by_customer()
    ranked = sorted(
        by_customer.items(),
        key=lambda kv: max(priority_score(s, st) for s in kv[1]),
        reverse=True,
    )
    if top_n:
        ranked = ranked[:top_n]

    rows = []
    for cid, signals in ranked:
        bucket = quadrants.bucket_of(cid) if quadrants else "protect"
        try:
            result = synthesise_one(
                ctx, cid, signals, bucket or "protect",
                client=client, allow_rules=allow_rules,
            )
        except LLMUnavailable:
            log.warning("no LLM and rules disabled — skipping relationship for %s", cid)
            continue
        r = result.value
        rows.append({
            S.CUSTOMER_ID: cid,
            "health": r.health,
            "health_confidence": r.health_confidence,
            "dominant_theme_fa": r.dominant_theme_fa,
            "unmet_promises_fa": r.unmet_promises_fa,
            "customer_priorities_fa": r.customer_priorities_fa,
            "recommended_tone_fa": r.recommended_tone_fa,
            "watch_items_fa": r.watch_items_fa,
            "summary_fa": r.summary_fa,
            "synthesis_source": result.source,
        })
        conf = 1.0 if result.source in {"live", "cached"} else 0.5
        ctx.emit(
            cid, "relationship",
            f"جمع‌بندی رابطه: وضعیت «{r.health}»، محور اصلی «{r.dominant_theme_fa}». "
            f"{r.summary_fa}",
            r.health, unit=None, kind="text",
            window=(ctx.as_of, ctx.as_of),
            source_rows=f"{S.S_CRM}:{cid}",
            formula=f"relationship synthesis ({result.source})",
            confidence=min(conf, float(r.health_confidence or conf)),
            synthesis_source=result.source,
            recommended_tone_fa=r.recommended_tone_fa,
            unmet_promises_fa=r.unmet_promises_fa,
        )

    table = (
        pd.DataFrame(rows).set_index(S.CUSTOMER_ID)
        if rows else pd.DataFrame(columns=["health"]).rename_axis(S.CUSTOMER_ID)
    )
    ctx.tables["relationship"] = table
    return ctx
