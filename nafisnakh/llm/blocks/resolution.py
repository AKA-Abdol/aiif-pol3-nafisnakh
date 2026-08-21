"""What the investigation found — extracted from ``Resolution_Text`` (PLAN §2).

``Complaint_Text`` says what the customer claimed. ``Resolution_Text`` says what
we found, whose fault it was, what we did about it, and whether it is finished.
Nothing read either of the last two until now, and they change what the sales
manager should say in the next meeting more than the complaint itself does:

* the customer complained and **the claim did not hold** — do not open with an
  apology, and note that the investigation cost us a visit and a lab test;
* the fault **was ours** — go in acknowledging it, and name the corrective action;
* the file is **still waiting on a sample or a test** — chase it to closure
  *before* the meeting, not after.

**Whole-book by construction** (PLAN §2 standing instruction). The two universes
write this column differently, so the block is a hybrid rather than being scoped
to one of them:

* Universe A is **templated** — 161 distinct strings over 334 rows, built from a
  fixed set of sentence frames. A template match is a string equality test, not a
  guess, so parsing it deterministically is both cheaper and *more* reliable than
  asking a model. Same reasoning as the 45→10 title map in :mod:`..taxonomy`.
* Universe B is **real Persian prose**, 40/40 unique, and only a model can read it.

So: templates first, model for everything they cannot classify. Every row records
which path produced it in ``extraction_source``, and that tag travels into the
evidence confidence exactly as the complaint block's does.

**As-of gating.** A resolution is knowable only from ``Resolution_Available_At``
on — integration rule #4. Reading it earlier would let the queue explain a
complaint using an answer that had not been written yet.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ...config import Settings, get_settings
from ...io import schema as S
from ...metrics.base import rows_ref
from ...io.normalize import normalize_fa, normalize_fa_keep_punct
from ..client import LLMClient, LLMResult, LLMUnavailable, get_client

log = logging.getLogger(__name__)

FaultVerdict = Literal["نفیس‌نخ", "مشتری", "حمل‌ونقل", "مشترک", "نامشخص"]
InvestigationState = Literal["بسته", "منتظر نمونه یا آزمون", "بدون نتیجه"]
RemedyType = Literal[
    "اصلاح فرآیند تولید", "اصلاح انبار و چیدمان", "جایگزینی کالا",
    "ابلاغ و آموزش", "بدون اقدام", "نامشخص",
]
EscalationBody = Literal[
    "کمیته S&OP", "جلسه خدمات مشتری", "بازدید میدانی", "مکاتبه رسمی", "هیچ"
]


class ResolutionExtraction(BaseModel):
    """What one investigation concluded."""

    fault_verdict: FaultVerdict = Field(
        description="پس از بررسی، قصور متوجه چه کسی شناخته شد"
    )
    investigation_state: InvestigationState = Field(
        description="آیا پرونده بسته شده، منتظر نمونه یا آزمون است، یا بدون نتیجه مانده"
    )
    initial_claim_overturned: bool = Field(
        description="آیا بررسی، مکانیزم یا ادعای اولیه شکایت را رد یا تصحیح کرد"
    )
    corrected_mechanism_fa: str | None = Field(
        default=None, description="اگر ادعای اولیه تصحیح شد، عیب واقعی چه بود"
    )
    remedy_type: RemedyType = Field(description="چه اقدامی انجام شد")
    systemic_fix: bool = Field(
        description="آیا اقدام یک تغییر فرآیندی پایدار بود، نه رفع موردی"
    )
    resolution_confirmed: bool = Field(
        description="آیا متن صراحتاً می‌گوید مشکل رفع شد"
    )
    compensation_given: bool = Field(
        description="آیا کالا یا جبران مادی به مشتری داده شد"
    )
    escalation_body_fa: EscalationBody = Field(
        description="موضوع به کدام مرجع ارجاع شد"
    )
    summary_fa: str = Field(description="خلاصه یک‌جمله‌ای نتیجه بررسی")


SYSTEM_PROMPT = """تو تحلیلگر واحد کیفیت شرکت نفیس نخ (تولیدکننده نخ POY) هستی.

متن «نتیجه بررسی و رسیدگی» یک شکایت به تو داده می‌شود. وظیفه‌ات استخراج ساختاریافته
از **همان متن** است.

قواعد سختگیرانه:
- فقط از متن رسیدگی استخراج کن. اگر چیزی در متن نیامده، «نامشخص» یا false بگذار.
- حدس نزن و از دانش عمومی خودت پر نکن.
- `fault_verdict` را از نتیجه بررسی بگیر، نه از ادعای مشتری.
- اگر متن می‌گوید ادعای مشتری تأیید نشد یا موضوع منتفی است، قصور متوجه ما نیست.
"""

USER_TEMPLATE = """عنوان شکایت: {title}
متن شکایت: {text}
وضعیت ثبت‌شده: {status}

متن رسیدگی:
\"\"\"{resolution}\"\"\"
"""


# --------------------------------------------------------------- template path
# The Universe-A sentence frames. These are matched, not inferred: the generator
# writes a fixed string, so a hit is an identification rather than a guess.
#
# ⚠️ Every pattern is compiled through :func:`normalize_fa`, the same function the
# text goes through. Writing one in raw orthography silently never matches —
# `normalize_fa` folds hamza (تأیید → تایید), strips ZWNJ and drops punctuation,
# so `مغایرتی که ادعای مشتری را تأیید کند` matched 0 of 62 rows it was written
# for. Normalising both sides with one function makes that class of bug
# impossible to reintroduce.


def _rx(*phrases: str) -> re.Pattern:
    """Alternation over phrases, normalised exactly like the text they match."""
    parts = [normalize_fa(p) for p in phrases]
    parts = [re.escape(p) for p in parts if p]
    if not parts:
        raise ValueError("no usable phrases")
    return re.compile("|".join(parts))


def _rx_gap(left: str, right: str, gap: int = 120) -> re.Pattern:
    """``left`` … ``right`` within ``gap`` characters, both normalised."""
    return re.compile(
        f"{re.escape(normalize_fa(left))}.{{0,{gap}}}?{re.escape(normalize_fa(right))}"
    )


_NOT_SUBSTANTIATED = _rx(
    "مغایرتی که ادعای مشتری را تأیید کند مشاهده نشد",
    "فاقد قصور",
    "منتفی",
)
_AWAITING = _rx(
    "مقرر گردید دوک نمونه",
    "تا زمان دریافت نمونه",
    "نیازمند بررسی تکمیلی",
    "آزمون تکمیلی",
)
_ROOT_CAUSE_ACTION = re.compile(
    "|".join([
        _rx_gap("مشخص گردید", "مقرر شد").pattern,
        _rx("اعلام و مقرر شد").pattern,
    ])
)
_REPLACEMENT = _rx("جایگزین", "ارسال گردید", "تعویض دوک", "مرجوع")
_INFORMED_ONLY = _rx("نمونه و سوابق تولید بررسی و نتیجه به مشتری اعلام شد")
_COMMITTEE = _rx("کمیته")
_SERVICE_MEETING = _rx("جلسه خدمات مشتری")
_SITE_VISIT = _rx("بازدید")
_LETTER = _rx("اتوماسیون", "نامه", "مکاتبه")
_WAREHOUSE = _rx("انبار", "چیدمان", "پالت")
_TRANSPORT = _rx("حمل", "جابه جایی", "باربری")


def _escalation(text: str) -> EscalationBody:
    if _COMMITTEE.search(text):
        return "کمیته S&OP"
    if _SERVICE_MEETING.search(text):
        return "جلسه خدمات مشتری"
    if _SITE_VISIT.search(text):
        return "بازدید میدانی"
    if _LETTER.search(text):
        return "مکاتبه رسمی"
    return "هیچ"


def template_extraction(resolution: str | None) -> ResolutionExtraction | None:
    """Parse a templated resolution, or return ``None`` to escalate to the model.

    Returning ``None`` is the important half: the templates cover Universe A's
    generator, and anything else — all of Universe B, plus the Universe-A rows
    that fall outside the frames — must not be forced into a template's reading.
    """
    raw = (resolution or "").strip()
    if not raw:
        return None
    norm = normalize_fa(raw)
    escalation = _escalation(norm)

    if _NOT_SUBSTANTIATED.search(norm):
        return ResolutionExtraction(
            fault_verdict="مشتری" if _TRANSPORT.search(norm) is None else "حمل‌ونقل",
            investigation_state="بسته",
            initial_claim_overturned=True,
            corrected_mechanism_fa=None,
            remedy_type="بدون اقدام",
            systemic_fix=False,
            resolution_confirmed=True,
            compensation_given=bool(_REPLACEMENT.search(norm)),
            escalation_body_fa=escalation,
            summary_fa="بررسی انجام شد و ادعای مشتری تأیید نشد.",
        )

    if _AWAITING.search(norm):
        return ResolutionExtraction(
            fault_verdict="نامشخص",
            investigation_state="منتظر نمونه یا آزمون",
            initial_claim_overturned=False,
            corrected_mechanism_fa=None,
            remedy_type="نامشخص",
            systemic_fix=False,
            resolution_confirmed=False,
            compensation_given=False,
            escalation_body_fa=escalation,
            summary_fa="پرونده باز است و منتظر نمونه یا آزمون تکمیلی مانده.",
        )

    if _ROOT_CAUSE_ACTION.search(norm):
        remedy: RemedyType = (
            "اصلاح انبار و چیدمان" if _WAREHOUSE.search(norm)
            else "جایگزینی کالا" if _REPLACEMENT.search(norm)
            else "اصلاح فرآیند تولید"
        )
        return ResolutionExtraction(
            fault_verdict="نفیس‌نخ",
            investigation_state="بسته",
            initial_claim_overturned=False,
            corrected_mechanism_fa=None,
            remedy_type=remedy,
            systemic_fix=True,
            resolution_confirmed=True,
            compensation_given=bool(_REPLACEMENT.search(norm)),
            escalation_body_fa=escalation,
            summary_fa="ریشه عیب شناسایی و اقدام اصلاحی تعیین شد.",
        )

    if _INFORMED_ONLY.search(norm):
        return ResolutionExtraction(
            fault_verdict="نامشخص",
            investigation_state="بسته",
            initial_claim_overturned=False,
            corrected_mechanism_fa=None,
            remedy_type="بدون اقدام",
            systemic_fix=False,
            resolution_confirmed=False,
            compensation_given=False,
            escalation_body_fa=escalation,
            summary_fa="نتیجه بررسی به مشتری اعلام شد بدون اقدام اصلاحی ثبت‌شده.",
        )

    return None


_UNKNOWN = ResolutionExtraction(
    fault_verdict="نامشخص", investigation_state="بدون نتیجه",
    initial_claim_overturned=False, corrected_mechanism_fa=None,
    remedy_type="نامشخص", systemic_fix=False, resolution_confirmed=False,
    compensation_given=False, escalation_body_fa="هیچ",
    summary_fa="متن رسیدگی قابل تفسیر نبود.",
)


def extract_one(
    client: LLMClient, title: str | None, text: str | None,
    resolution: str | None, status: str | None, *, allow_rules: bool,
) -> LLMResult:
    """Template first, model second — see the module docstring on why.

    ``source="template"`` is deliberately distinct from the complaint block's
    ``"rules"``. A rules pass there is a keyword *heuristic*; a template hit here
    is a match against the exact string the generator wrote, so it earns a higher
    confidence and says so under its own name.
    """
    templated = template_extraction(resolution)
    if templated is not None:
        return LLMResult(templated, "template", "template", "")

    user = USER_TEMPLATE.format(
        title=title or "—", text=normalize_fa_keep_punct(str(text or ""))[:600],
        status=status or "—",
        resolution=normalize_fa_keep_punct(str(resolution or "")),
    )
    fallback = (lambda: _UNKNOWN) if allow_rules else None
    return client.structured(SYSTEM_PROMPT, user, ResolutionExtraction, fallback=fallback)


EXTRACTION_COLUMNS = [
    "complaint_id", "fault_verdict", "investigation_state",
    "initial_claim_overturned", "corrected_mechanism_fa", "remedy_type",
    "systemic_fix", "resolution_confirmed", "compensation_given",
    "escalation_body_fa", "summary_fa", "extraction_source",
]

CONFIDENCE_BY_SOURCE = {
    "live": 1.0, "cached": 1.0,
    # a fixed-string match, not a heuristic — but still our reading of a
    # template rather than a human's, so not a flat 1.0
    "template": 0.85,
    "rules": 0.4,
}


def extract_resolutions(
    complaints: pd.DataFrame,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    allow_rules: bool = True,
) -> pd.DataFrame:
    """Run the block over an **already as-of-gated** complaint frame.

    The caller does the gating because the correct gate here is
    ``Resolution_Available_At``, not the complaint's own ``Available_At``.
    """
    st = settings or get_settings()
    client = client or get_client(st)

    rows = []
    for r in complaints.itertuples():
        resolution = getattr(r, "Resolution_Text", None)
        if not str(resolution or "").strip():
            continue
        try:
            result = extract_one(
                client,
                getattr(r, "Complaint_Title", None),
                getattr(r, "Complaint_Text", None),
                resolution,
                getattr(r, "Complaint_Status", None),
                allow_rules=allow_rules,
            )
        except LLMUnavailable:
            log.warning("no LLM and rules disabled — skipping %s", r.Complaint_ID)
            continue
        e = result.value
        rows.append({
            S.CUSTOMER_ID: r.Customer_ID,
            "complaint_id": r.Complaint_ID,
            "extraction_source": result.source,
            **e.model_dump(),
        })

    if not rows:
        return pd.DataFrame(columns=[S.CUSTOMER_ID] + EXTRACTION_COLUMNS).set_index(
            S.CUSTOMER_ID
        )
    return pd.DataFrame(rows).set_index(S.CUSTOMER_ID)


def knowable_resolutions(ctx) -> pd.DataFrame:
    """Complaints whose **resolution** is readable at ``as_of`` (rule #4).

    Gated on ``Resolution_Available_At``, not on the complaint's ``Available_At``:
    the complaint is knowable when it is filed, the answer only when it is
    published. At the demo anchor the two differ by one day for every row, but a
    feature that reads the wrong stamp is wrong at every other anchor too.
    """
    from ...core.spine import visible

    comp = visible(ctx.ds.complaints, ctx.as_of)
    as_of = pd.Timestamp(ctx.as_of)
    comp = comp.loc[
        pd.to_datetime(comp[S.K_CREATED_AT], errors="coerce") <= as_of
    ]
    stamp = pd.to_datetime(comp[S.K_RESOLUTION_AVAILABLE_AT], errors="coerce")
    return comp.loc[stamp.notna() & (stamp <= as_of)]


# --------------------------------------------------- the per-customer rollup
RELATIONSHIP_STANCE_FA = {
    "apologise": (
        "در آخرین بررسی‌ها قصور متوجه نفیس نخ شناخته شده است؛ گفتگو را با پذیرش "
        "موضوع و اعلام اقدام اصلاحی شروع کن، نه با دفاع."
    ),
    "unsubstantiated": (
        "شکایت‌های اخیر این مشتری بررسی شد و قصور متوجه نفیس نخ نبود؛ عذرخواهی لازم "
        "نیست و هزینه بررسی‌های بی‌مورد یک اهرم در مذاکره است."
    ),
    "mixed": (
        "سابقه شکایات این مشتری هر دو حالت را دارد؛ پیش از موضع‌گیری، پرونده‌ها را "
        "تک‌به‌تک مرور کن."
    ),
    "neutral": "بررسی شکایتی که موضع خاصی ایجاد کند در سابقه نیست.",
}


def customer_state(ctx, customer_id: str) -> dict:
    """The one-customer view the aggregator and the detectors read.

    Kept here rather than folded into the ``quality`` metric table because the
    metric layer is built *before* this block runs — the same reason detector #16
    reads ``llm_complaints`` from ``ctx.tables`` directly.
    """
    empty = {
        "fault_ours": 0, "fault_not_ours": 0, "pending": 0,
        "oldest_pending_days": None, "pending_ids": [], "stance": "neutral",
        "pending_evidence_ids": [],
    }
    table = ctx.tables.get("llm_resolutions")
    if table is None or not len(table) or customer_id not in table.index:
        return empty
    rows = table.loc[[customer_id]]

    ours = int((rows["fault_verdict"] == "نفیس‌نخ").sum())
    not_ours = int(rows["fault_verdict"].isin(("مشتری", "حمل‌ونقل")).sum())
    pending_rows = rows.loc[rows["investigation_state"] == "منتظر نمونه یا آزمون"]
    pending_ids = sorted(pending_rows["complaint_id"])

    oldest = None
    if pending_ids:
        comp = knowable_resolutions(ctx)
        mine = comp.loc[comp[S.K_ID].isin(pending_ids)]
        if len(mine):
            age = (
                pd.Timestamp(ctx.as_of)
                - pd.to_datetime(mine[S.K_CREATED_AT], errors="coerce")
            ).dt.days
            oldest = int(age.max()) if pd.notna(age.max()) else None

    if ours and not_ours:
        stance = "mixed"
    elif ours:
        stance = "apologise"
    elif not_ours:
        stance = "unsubstantiated"
    else:
        stance = "neutral"

    return {
        "fault_ours": ours, "fault_not_ours": not_ours,
        "pending": len(pending_ids), "oldest_pending_days": oldest,
        "pending_ids": pending_ids, "stance": stance,
        "pending_evidence_ids": ctx.ev(customer_id, "resolution-pending"),
    }


def attach_to_context(ctx, *, allow_rules: bool = True) -> "object":
    """Register the ``llm_resolutions`` table and emit its evidence."""
    comp = knowable_resolutions(ctx)
    table = extract_resolutions(comp, settings=ctx.settings, allow_rules=allow_rules)
    ctx.tables["llm_resolutions"] = table
    if not len(table):
        return ctx

    # age per complaint, so the pending evidence can state a number the action
    # text is then allowed to quote (the validator checks exactly this)
    ages = {}
    if len(comp):
        age_days = (
            pd.Timestamp(ctx.as_of)
            - pd.to_datetime(comp[S.K_CREATED_AT], errors="coerce")
        ).dt.days
        ages = dict(zip(comp[S.K_ID], age_days))

    window = (ctx.as_of, ctx.as_of)
    for cid, r in table.iterrows():
        conf = CONFIDENCE_BY_SOURCE.get(r.extraction_source, 0.4)
        if r.fault_verdict == "نفیس‌نخ":
            ctx.emit(
                cid, "resolution-fault",
                f"در بررسی شکایت {r.complaint_id} قصور متوجه نفیس نخ شناخته شد "
                f"({r.summary_fa})",
                r.fault_verdict, unit=None, kind="text", window=window,
                source_rows=rows_ref(S.S_COMPLAINTS, [r.complaint_id]),
                formula=f"resolution extraction ({r.extraction_source})",
                confidence=conf, extraction_source=r.extraction_source,
                remedy=r.remedy_type, systemic=bool(r.systemic_fix),
            )
        elif r.fault_verdict in ("مشتری", "حمل‌ونقل"):
            ctx.emit(
                cid, "resolution-unsubstantiated",
                f"شکایت {r.complaint_id} بررسی شد و قصور متوجه نفیس نخ نبود "
                f"({r.summary_fa})",
                r.fault_verdict, unit=None, kind="text", window=window,
                source_rows=rows_ref(S.S_COMPLAINTS, [r.complaint_id]),
                formula=f"resolution extraction ({r.extraction_source})",
                confidence=conf, extraction_source=r.extraction_source,
            )
        if r.investigation_state == "منتظر نمونه یا آزمون":
            age = ages.get(r.complaint_id)
            age_fa = f" و {int(age)} روز از ثبت آن گذشته است" if pd.notna(age) else ""
            ctx.emit(
                cid, "resolution-pending",
                f"پروندهٔ شکایت {r.complaint_id} هنوز بسته نشده، منتظر نمونه یا "
                f"آزمون تکمیلی است{age_fa}.",
                int(age) if pd.notna(age) else 0, unit="روز", kind="text", window=window,
                source_rows=rows_ref(S.S_COMPLAINTS, [r.complaint_id]),
                formula=f"resolution extraction ({r.extraction_source})",
                confidence=conf, extraction_source=r.extraction_source,
            )
    return ctx
