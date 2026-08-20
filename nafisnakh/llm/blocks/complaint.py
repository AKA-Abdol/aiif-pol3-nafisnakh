"""Structured extraction from complaint text (PLAN §3.6).

The category is the least valuable thing here. A 45→10 lookup already gives the
mechanism for any complaint that carries one of the curated titles. What no
column in the dataset holds — and what changes what the sales manager does
tomorrow — is everything else in :class:`ComplaintExtraction`:

    «... **اين مشکل تکراري ميباشد** و قبلا هم وجود داشته و مشتري اعلام نموده که
    **درصورت تکرار قطع همکاري ميکند**. مشتري عکس ارسال نموده است»

An explicit churn threat, a repeat claim, and photographic evidence supplied —
three facts, in one sentence, none of them in any structured field.
``churn_threat`` alone drives detector #16, the highest-severity signal in the
system.

**Offline behaviour.** Without an API key (Q14) the block runs a deliberately
narrow rule extractor and tags every row ``extraction_source="rules"``. That tag
travels into the evidence confidence and into the eval report, so a rules run is
never mistaken for a model run. The rules exist to keep the pipeline testable
end-to-end, not to substitute for the model.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ...config import Settings, get_settings
from ...io import schema as S
from ...io.normalize import normalize_fa, normalize_fa_keep_punct
from ..client import LLMClient, LLMUnavailable, get_client
from ..taxonomy import (
    MECHANISM_IDS,
    UNKNOWN,
    mechanism_for_title,
    mechanism_label,
    taxonomy_prompt_block,
)

log = logging.getLogger(__name__)

EscalationLevel = Literal["عادی", "پیگیری", "تشدید", "بحرانی"]
AttributedFault = Literal["تولید", "بسته‌بندی", "حمل", "مشتری", "نامشخص"]


class ComplaintExtraction(BaseModel):
    """What the LLM must return for one complaint."""

    mechanism: str = Field(
        description="یکی از شناسه‌های مکانیزم، یا UNKNOWN اگر هیچ‌کدام مناسب نبود"
    )
    mechanism_confidence: float = Field(ge=0.0, le=1.0)
    proposed_new_category_fa: str | None = Field(
        default=None, description="فقط وقتی mechanism برابر UNKNOWN است"
    )
    churn_threat: bool = Field(
        description="آیا مشتری صراحتاً به قطع همکاری یا توقف خرید اشاره کرده است؟"
    )
    churn_threat_quote_fa: str | None = None
    repeat_claim: bool = Field(
        description="آیا مشتری گفته این مشکل تکراری است یا قبلاً هم رخ داده؟"
    )
    financial_demand: bool = Field(
        description="آیا درخواست مالی صریح (مرجوعی، اعتبار، خسارت) مطرح شده؟"
    )
    escalation_level: EscalationLevel
    attributed_fault: AttributedFault
    evidence_supplied: bool = Field(
        description="آیا مشتری عکس، نمونه یا گزارش آزمایشگاه ارسال کرده است؟"
    )
    hembaft_mentioned: list[str] = Field(
        default_factory=list, description="شماره‌های همبافت که در خودِ متن آمده‌اند"
    )
    affected_quantity_kg: float | None = None
    summary_fa: str = Field(description="یک جمله برای مدیر فروش")


SYSTEM_PROMPT = f"""تو دستیار تحلیل شکایات کیفی یک تولیدکننده نخ POY (نفیس نخ) هستی.
متن شکایت را می‌خوانی و فقط چیزهایی را استخراج می‌کنی که **در خود متن آمده‌اند**.
هیچ چیزی را حدس نزن و هیچ عددی را که در متن نیست ننویس.

مکانیزم‌های فیزیکی مجاز:
{taxonomy_prompt_block()}

قواعد:
- اگر متن با هیچ‌کدام از این ده مکانیزم نمی‌خواند، mechanism را UNKNOWN بگذار و در
  proposed_new_category_fa یک عنوان کوتاه فارسی برای دسته پیشنهادی بنویس.
- churn_threat فقط وقتی true است که مشتری صراحتاً به قطع همکاری، توقف خرید یا
  تغییر تأمین‌کننده اشاره کرده باشد. نارضایتی شدید به‌تنهایی کافی نیست.
- اگر churn_threat true است، عین عبارت را در churn_threat_quote_fa بیاور.
- hembaft_mentioned فقط شماره‌هایی است که در متن شکایت آمده‌اند، نه از ستون‌های دیگر.
- summary_fa یک جمله کوتاه و عملیاتی برای مدیر فروش باشد.
"""

USER_TEMPLATE = """عنوان شکایت: {title}
شدت ثبت‌شده: {severity}
متن شکایت:
\"\"\"{text}\"\"\"
"""

# ----------------------------------------------------------------- rule path
_CHURN_PATTERNS = [
    r"قطع همکاری", r"قطع همکاري", r"عدم همکاری", r"دیگر خرید نمی",
    r"دیگر خريد نمي", r"خرید نخواهیم", r"تأمین کننده دیگر", r"تامین کننده دیگر",
    r"لغو قرارداد", r"فسخ قرارداد",
]
_REPEAT_PATTERNS = [
    r"تکراری", r"تکراري", r"قبلا هم", r"قبلاً هم", r"مجدد", r"مشکل قبلی",
    r"مشکل قبلي", r"باز هم", r"مکرر",
]
_FINANCIAL_PATTERNS = [
    r"مرجوع", r"خسارت", r"غرامت", r"کسر هزینه", r"کسر هزينه", r"تخفیف",
    r"اعتبار", r"جبران",
]
_EVIDENCE_PATTERNS = [r"عکس", r"تصویر", r"تصاویر", r"نمونه ارسال", r"گزارش آزمایشگاه"]
_IMPACT_PATTERNS = [r"راندمان", r"توقف", r"افت شدید", r"پارگی شدید", r"به شدت"]
_HEMBAFT_RE = re.compile(r"\b\d{6,12}\b")

_FAULT_HINTS: list[tuple[str, AttributedFault]] = [
    (r"حمل|باربری|پالت|جابه ?جایی|بارگیری", "حمل"),
    (r"بسته ?بندی|شیرینگ|دوک|لیبل|پالت", "بسته‌بندی"),
    (r"تولید|وایندر|ستینگ|خط ۲|خط 2|پیچش|فیلامنت|دنیر|شید", "تولید"),
]


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def rule_extraction(title: str | None, text: str | None, severity: str | None) -> ComplaintExtraction:
    """A narrow, auditable fallback. Not a model — a keyword pass, and labelled
    as such wherever its output travels."""
    raw = text or ""
    norm = normalize_fa(raw)
    mech = mechanism_for_title(title)

    churn = _any(_CHURN_PATTERNS, norm)
    quote = None
    if churn:
        for sentence in re.split(r"[.؟!\n]", normalize_fa_keep_punct(raw)):
            if _any(_CHURN_PATTERNS, normalize_fa(sentence)):
                quote = sentence.strip()
                break

    repeat = _any(_REPEAT_PATTERNS, norm)
    impact = _any(_IMPACT_PATTERNS, norm)
    if churn:
        escalation: EscalationLevel = "تشدید"
    elif impact or repeat:
        escalation = "پیگیری"
    else:
        escalation = "عادی"

    fault: AttributedFault = "نامشخص"
    for pattern, label in _FAULT_HINTS:
        if re.search(pattern, norm):
            fault = label
            break

    return ComplaintExtraction(
        mechanism=mech,
        mechanism_confidence=0.9 if mech != UNKNOWN else 0.2,
        proposed_new_category_fa=None,
        churn_threat=churn,
        churn_threat_quote_fa=quote,
        repeat_claim=repeat,
        financial_demand=_any(_FINANCIAL_PATTERNS, norm),
        escalation_level=escalation,
        attributed_fault=fault,
        evidence_supplied=_any(_EVIDENCE_PATTERNS, norm),
        hembaft_mentioned=sorted(set(_HEMBAFT_RE.findall(normalize_fa(raw)))),
        affected_quantity_kg=None,
        summary_fa=(norm[:120] or "بدون متن"),
    )


# ------------------------------------------------------------------- the block
EXTRACTION_COLUMNS = [
    "complaint_id", "mechanism", "mechanism_confidence", "proposed_new_category_fa",
    "churn_threat", "churn_threat_quote_fa", "repeat_claim", "financial_demand",
    "escalation_level", "attributed_fault", "evidence_supplied", "hembaft_mentioned",
    "affected_quantity_kg", "summary_fa", "extraction_source", "title_mechanism",
]


def extract_one(
    client: LLMClient, title: str | None, text: str | None, severity: str | None,
    *, allow_rules: bool,
):
    user = USER_TEMPLATE.format(
        title=title or "—", severity=severity or "—",
        text=normalize_fa_keep_punct(text or ""),
    )
    fallback = (lambda: rule_extraction(title, text, severity)) if allow_rules else None
    return client.structured(SYSTEM_PROMPT, user, ComplaintExtraction, fallback=fallback)


def extract_complaints(
    complaints: pd.DataFrame,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    allow_rules: bool = True,
) -> pd.DataFrame:
    """Run the block over a complaint frame. Index is ``Customer_ID``.

    The result is the ``llm_complaints`` metric table that detector #16 reads.
    """
    st = settings or get_settings()
    client = client or get_client(st)

    rows = []
    for r in complaints.itertuples():
        title = getattr(r, S.K_TITLE.replace(" ", "_"), None) or getattr(r, "Complaint_Title", None)
        text = getattr(r, "Complaint_Text", None)
        severity = getattr(r, "Severity", None)
        try:
            result = extract_one(client, title, text, severity, allow_rules=allow_rules)
        except LLMUnavailable:
            log.warning("no LLM and rules disabled — skipping %s", r.Complaint_ID)
            continue
        e = result.value
        rows.append({
            S.CUSTOMER_ID: r.Customer_ID,
            "complaint_id": r.Complaint_ID,
            "mechanism": e.mechanism,
            "mechanism_confidence": e.mechanism_confidence,
            "proposed_new_category_fa": e.proposed_new_category_fa,
            "churn_threat": e.churn_threat,
            "churn_threat_quote_fa": e.churn_threat_quote_fa,
            "repeat_claim": e.repeat_claim,
            "financial_demand": e.financial_demand,
            "escalation_level": e.escalation_level,
            "attributed_fault": e.attributed_fault,
            "evidence_supplied": e.evidence_supplied,
            "hembaft_mentioned": e.hembaft_mentioned,
            "affected_quantity_kg": e.affected_quantity_kg,
            "summary_fa": e.summary_fa,
            "extraction_source": result.source,
            "title_mechanism": mechanism_for_title(title),
        })
    if not rows:
        return pd.DataFrame(columns=[S.CUSTOMER_ID] + EXTRACTION_COLUMNS).set_index(
            S.CUSTOMER_ID
        )
    out = pd.DataFrame(rows)

    # PLAN §5.4: 67% of universe-A complaint bodies are verbatim duplicates, and
    # the generator seeded real universe-B prose into universe-A rows. A body
    # that appears under several customers is a generator artifact, not several
    # independent customers saying the same thing — flag it so nothing
    # downstream can present it as N separate findings.
    bodies = comp_body_key(complaints)
    out["body_key"] = out["complaint_id"].map(bodies)
    spread = (
        out.reset_index().groupby("body_key")[S.CUSTOMER_ID].nunique()
        if "body_key" in out else {}
    )
    out["body_duplicate_customers"] = out["body_key"].map(spread).fillna(1).astype(int)
    return out.set_index(S.CUSTOMER_ID)


def comp_body_key(complaints: pd.DataFrame) -> dict[str, str]:
    """Normalised complaint body per complaint id — the duplicate-detection key."""
    return {
        r.Complaint_ID: normalize_fa(getattr(r, "Complaint_Text", "") or "")
        for r in complaints.itertuples()
    }


def attach_to_context(ctx, *, allow_rules: bool = True, universe: str | None = None):
    """Run the block for **triggered customers only** and register the table.

    PLAN §3.8 is the cost control: the metric layer is free and runs for all 526
    customers; the LLM runs only where a signal already fired, which is 40–80
    accounts, not 2,750.
    """
    from ...core.spine import visible

    comp = visible(ctx.ds.complaints, ctx.as_of)
    comp = comp.loc[
        pd.to_datetime(comp[S.K_CREATED_AT], errors="coerce") <= pd.Timestamp(ctx.as_of)
    ]
    if universe:
        comp = comp.loc[comp["_universe"] == universe]
    table = extract_complaints(comp, settings=ctx.settings, allow_rules=allow_rules)
    ctx.tables["llm_complaints"] = table

    window = (ctx.as_of, ctx.as_of)
    for cid, r in table.iterrows():
        conf = 1.0 if r.extraction_source in {"live", "cached"} else 0.6
        ctx.emit(
            cid, "llm-mechanism",
            f"شکایت {r.complaint_id} به مکانیزم «{mechanism_label(r.mechanism)}» "
            f"نسبت داده شد ({r.mechanism}).",
            r.mechanism, unit=None, kind="text", window=window,
            source_rows=f"{S.S_COMPLAINTS}:{r.complaint_id}",
            formula=f"LLM structured extraction ({r.extraction_source})",
            confidence=min(conf, float(r.mechanism_confidence or conf)),
            extraction_source=r.extraction_source,
        )
        if r.churn_threat:
            quote = r.churn_threat_quote_fa or ""
            shared = int(r.get("body_duplicate_customers", 1) or 1)
            claim = (
                f"در متن شکایت {r.complaint_id} تهدید صریح به قطع همکاری آمده است"
                + (f": «{quote}»" if quote else ".")
            )
            if shared > 1:
                claim += (
                    " ⚠️ عین همین متن برای چند مشتری دیگر هم ثبت شده است؛"
                    " احتمال تکرار مصنوعی داده وجود دارد."
                )
            ctx.emit(
                cid, "llm-churn", claim,
                True, unit=None, kind="text", window=window,
                source_rows=f"{S.S_COMPLAINTS}:{r.complaint_id}",
                formula=f"LLM structured extraction ({r.extraction_source})",
                confidence=conf if shared == 1 else conf * 0.5,
                extraction_source=r.extraction_source,
                repeat_claim=bool(r.repeat_claim),
                body_duplicate_customers=shared,
            )
    return ctx
