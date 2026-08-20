"""Evidence-citation enforcement — the mechanism behind the guarantee (PLAN §3.1).

The user's stated goal:

> با evidence درست بتوانیم اشاره کنیم که این اکشنی که پیشنهاد شده صحیح است.

"Evidence-backed" is a claim until something refuses to ship an action that
isn't. That is this module. Three checks, all programmatic:

1. every cited ``evidence_id`` exists in the registry;
2. every cited id belongs to **that** customer;
3. **no numeral appears in the action text that is absent from the cited
   evidence** — the LLM writes reasoning, never numbers.

On failure the aggregator retries once with the validator's complaint appended
to the prompt, then drops the action and logs it. A dropped action is visible in
the run summary; it never silently becomes a plausible-sounding sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.evidence import EvidenceRegistry, extract_numerals

# Numerals that are structural rather than factual claims and are therefore
# exempt: a year, a percentage sign's own "100", an enumerated step number.
_EXEMPT = {"0", "1", "2", "3", "100"}
_YEAR_RE = re.compile(r"^(19|20|14)\d{2}$")

# Identifiers are citations, not numeric claims: `[EV-C_117580-cadence-001]` must
# not be read as the three numbers 117580, 001. They are stripped before any
# numeral extraction, and checked separately as citations.
_CITATION_RE = re.compile(r"EV-[A-Za-z0-9_\-]+")
_CUSTOMER_RE = re.compile(r"\b(?:C_\d+|CUST-\d+)\b", re.IGNORECASE)
_MECHANISM_RE = re.compile(r"\bM\d{2}_[a-z_]+\b")
# `CMP-0021` and the fixture's `CMPFIX-007` are both citations, not numeric
# claims. The narrower form missed the fixture prefix and read its suffix as the
# number 007.
_COMPLAINT_RE = re.compile(r"\bCMP[A-Z]*-\d+\b", re.IGNORECASE)


def strip_identifiers(text: str) -> str:
    """Remove evidence ids, customer ids, mechanism ids and complaint ids."""
    for pattern in (_CITATION_RE, _CUSTOMER_RE, _MECHANISM_RE, _COMPLAINT_RE):
        text = pattern.sub(" ", text or "")
    return text


def _consistent_rounding(numeral: str, allowed: set[str]) -> bool:
    """``11.3`` is consistent with an evidence value of ``11.34``.

    The metric layer emits some claims at two decimals and some signal headlines
    at one, so an exact string match would reject text that is in fact faithful
    to its evidence. A numeral is accepted when *some* allowed value rounds to it
    at the numeral's own precision — never the other way round, so a text may
    round a number but never invent precision it was not given.
    """
    try:
        value = float(numeral)
    except ValueError:
        return False
    digits = len(numeral.split(".")[1]) if "." in numeral else 0
    for a in allowed:
        try:
            if round(float(a), digits) == value:
                return True
        except ValueError:
            continue
    return False


@dataclass
class ValidationIssue:
    code: str
    detail: str


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def complaint_fa(self) -> str:
        """A message that can be appended to a retry prompt."""
        if self.ok:
            return ""
        lines = ["اقدام قبلی رد شد. دلایل:"]
        for i in self.issues:
            lines.append(f"- {i.detail}")
        lines.append(
            "فقط از شناسه‌های شواهد داده‌شده استفاده کن و هیچ عددی ننویس که در متن آن "
            "شواهد نیامده باشد."
        )
        return "\n".join(lines)


def allowed_numerals(registry: EvidenceRegistry, evidence_ids: list[str]) -> set[str]:
    allowed = set(_EXEMPT)
    for ev in registry.many(evidence_ids):
        allowed |= ev.numerals()
    return allowed


def validate_action(
    action, registry: EvidenceRegistry, *, texts: list[str] | None = None
) -> ValidationResult:
    """Run the three checks against one :class:`~nafisnakh.aggregate.aggregator.Action`."""
    issues: list[ValidationIssue] = []

    if not action.evidence_ids:
        issues.append(ValidationIssue("no_evidence", "هیچ شناهد شاهدی ذکر نشده است."))

    for eid in action.evidence_ids:
        ev = registry.get(eid)
        if ev is None:
            issues.append(
                ValidationIssue("unknown_evidence", f"شناسه شاهد {eid} وجود ندارد.")
            )
        elif ev.customer_id != action.customer_id:
            issues.append(ValidationIssue(
                "foreign_evidence",
                f"شناسه شاهد {eid} متعلق به مشتری دیگری است ({ev.customer_id}).",
            ))

    allowed = allowed_numerals(registry, action.evidence_ids)
    texts = texts if texts is not None else [
        action.title_fa, action.rationale_fa, action.recommended_step_fa
    ]
    for text in texts:
        for numeral in extract_numerals(strip_identifiers(text or "")):
            if numeral in allowed or _YEAR_RE.match(numeral):
                continue
            if _consistent_rounding(numeral, allowed):
                continue
            issues.append(ValidationIssue(
                "unsupported_number",
                f"عدد «{numeral}» در متن آمده اما در هیچ‌یک از شواهد ذکرشده نیست.",
            ))

    # every cited id must actually be referenced, or the citation is decoration
    cited_inline = set(re.findall(r"EV-[A-Za-z0-9_\-]+", " ".join(t or "" for t in texts)))
    unknown_inline = [c for c in cited_inline if c not in action.evidence_ids]
    for c in unknown_inline:
        issues.append(ValidationIssue(
            "inline_not_declared",
            f"شناسه {c} در متن آمده اما در فهرست evidence_ids نیست.",
        ))

    return ValidationResult(ok=not issues, issues=issues)
