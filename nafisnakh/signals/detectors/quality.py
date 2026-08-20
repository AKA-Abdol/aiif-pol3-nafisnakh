"""Quality and relationship detectors #15–#20 (PLAN §3.4).

Two of these are the system's strongest arguments:

* **#16 ``churn_threat_language``** — the highest-severity signal in the whole
  design, and it exists only because an LLM reads the complaint body. Nothing in
  the structured columns carries "درصورت تکرار قطع همکاری میکند".
* **#18 ``hembaft_blast_radius``** — preemptive. When one customer complains
  about a همبافت, every other customer shipped from that same همبافت is holding
  a complaint that has not been filed yet. Nobody asked for this detector; it is
  specific to this industry's lot structure (integration rule #7).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...metrics.base import MetricContext, money, num, pct
from ..base import BaseDetector, Signal, annual_revenue, register, scale


@register
class ComplaintRecurrence(BaseDetector):
    """#15 — the same failure happening again to the same customer.

    The deterministic floor matches on the normalised title; the LLM block
    upgrades this to the physical **mechanism**, which is what actually recurs
    (the 45 titles are near-synonyms).
    """

    name = "complaint_recurrence"
    category = "risk"
    requires = ["quality", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        q = ctx.table("quality")
        return q.index[q["complaints_total"] > 0].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        q = self.frame(ctx)
        hits = q.loc[q["complaint_recurrences"] > 0]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.complaint_recurrences, 1, 5, floor=45.0),
                headline_fa=(
                    f"{num(r.complaint_recurrences)} شکایت تکراری با همان عنوان در بازه "
                    f"{ctx.settings.complaint_recurrence_days} روزه — مشکل حل نشده است."
                ),
                evidence_ids=ctx.ev(cid, "complaint-repeat", "complaints"),
                value_at_stake=annual_revenue(ctx, cid) * 0.3,
                recurrences=float(r.complaint_recurrences),
            ))
        return out


@register
class ChurnThreatLanguage(BaseDetector):
    """#16 — an explicit threat to end the relationship, read out of the
    complaint prose by the LLM block.

    This detector consumes ``llm_complaints``: it does not parse text itself.
    When the LLM block has not run (no API key — Q14), it returns nothing rather
    than guessing, so the queue never silently loses its most important signal
    to a fallback heuristic.
    """

    name = "churn_threat_language"
    category = "risk"
    requires = ["quality", "economics"]
    rare_by_design = True

    def eligible(self, ctx: MetricContext) -> pd.Index:
        q = ctx.table("quality")
        return q.index[q["complaints_total"] > 0]

    def detect(self, ctx: MetricContext) -> list[Signal]:
        extractions = ctx.tables.get("llm_complaints")
        if extractions is None or extractions.empty:
            return []
        hits = extractions.loc[extractions["churn_threat"].fillna(False)]
        out = []
        for cid, group in hits.groupby(level=0):
            quotes = [q for q in group["churn_threat_quote_fa"].tolist() if q]
            repeat = bool(group["repeat_claim"].any())
            # A body the generator copied across several customers is one text,
            # not several customers threatening to leave (PLAN §5.4).
            shared = int(group.get("body_duplicate_customers", pd.Series([1])).max() or 1)
            severity = 95.0 if repeat else 80.0
            if shared > 1:
                severity *= 0.5
            head = "مشتری صراحتاً به قطع همکاری اشاره کرده است"
            if quotes:
                head += f": «{quotes[0]}»"
            if repeat:
                head += " — و اعلام کرده مشکل تکراری است."
            if shared > 1:
                head += (
                    f" ⚠️ عین همین متن برای {shared} مشتری ثبت شده — پیش از اقدام،"
                    " اصالت متن بررسی شود."
                )
            out.append(self.signal(
                ctx, cid,
                severity=severity,
                headline_fa=head,
                evidence_ids=ctx.ev(cid, "llm-churn", "complaints", "llm-mechanism"),
                value_at_stake=annual_revenue(ctx, cid),
                suggested_bucket="protect",
                repeat_claim=repeat,
                quotes=quotes,
                body_duplicate_customers=shared,
            ))
        return out


@register
class UnresolvedAging(BaseDetector):
    """#17 — a complaint open longer than the book's median time to resolve."""

    name = "unresolved_aging"
    category = "risk"
    requires = ["quality", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        q = ctx.table("quality")
        return q.index[q["complaints_open"] > 0].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        q = self.frame(ctx)
        ages = q.loc[q["complaints_open"] > 0, "oldest_open_age_days"].dropna()
        if ages.empty:
            return []
        threshold = float(st.unresolved_aging_days)
        if len(ages) >= st.min_percentile_observations:
            threshold = max(threshold, float(ages.quantile(st.aging_percentile / 100.0)))
        hits = q.loc[q["oldest_open_age_days"] > threshold]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.oldest_open_age_days, threshold, threshold * 3),
                headline_fa=(
                    f"شکایت باز {num(r.oldest_open_age_days)} روزه — کهنه‌تر از "
                    f"{num(threshold, 0)} روز، یعنی صدک "
                    f"{num(st.aging_percentile, 0)} شکایت‌های باز دفتر."
                ),
                evidence_ids=ctx.ev(cid, "complaint-age", "complaints"),
                value_at_stake=annual_revenue(ctx, cid) * 0.15,
                age_days=float(r.oldest_open_age_days), threshold_days=threshold,
            ))
        return out


@register
class HembaftBlastRadius(BaseDetector):
    """#18 — preemptive: complaints in flight, before they are filed.

    Traversal is complaint → ``Hembaft_ID`` → ``همبافت_لات`` → ``Lot_ID`` →
    ``فروش``, per integration rule #7. Grouping on ``Lot_ID`` instead would be
    wrong and would find nothing.
    """

    name = "hembaft_blast_radius"
    category = "risk"
    requires = ["quality", "economics"]
    rare_by_design = True

    def detect(self, ctx: MetricContext) -> list[Signal]:
        q = self.frame(ctx)
        hits = q.loc[q["hembaft_at_risk_lines"] > 0]
        out = []
        for cid, r in hits.iterrows():
            ids = r.hembaft_at_risk_ids if isinstance(r.hembaft_at_risk_ids, list) else []
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.hembaft_at_risk_qty, 500, 40_000, floor=50.0),
                headline_fa=(
                    f"این مشتری {num(r.hembaft_at_risk_qty)} کیلوگرم از همبافت‌هایی "
                    f"دریافت کرده که مشتری دیگری روی همان‌ها شکایت ثبت کرده است "
                    f"({len(ids)} همبافت) — تماس پیشدستانه پیش از ثبت شکایت."
                ),
                evidence_ids=ctx.ev(cid, "hembaft-risk"),
                value_at_stake=float(r.hembaft_at_risk_value or 0.0),
                suggested_bucket="protect",
                hembaft_ids=ids,
                preemptive=True,
            ))
        return out


@register
class ReturnRateSpike(BaseDetector):
    """#19 — returned weight against shipped weight, above the book's p90."""

    name = "return_rate_spike"
    category = "risk"
    requires = ["quality", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        q = ctx.table("quality")
        return q.index[q["return_rate"].fillna(0) > 0].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        q = self.frame(ctx)
        rates = q["return_rate"].replace(0, np.nan).dropna()
        if rates.empty:
            return []
        threshold = (
            float(rates.quantile(st.return_rate_percentile / 100.0))
            if len(rates) >= st.min_percentile_observations
            else float(st.return_rate_floor)
        )
        hits = q.loc[q["return_rate"] > threshold]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.return_rate, threshold, threshold * 4),
                headline_fa=(
                    f"نرخ برگشتی {pct(r.return_rate, 2)} درصد است — بالاتر از صدک "
                    f"{num(st.return_rate_percentile, 0)} دفتر "
                    f"({pct(threshold, 2)} درصد)."
                ),
                evidence_ids=ctx.ev(cid, "returns", "complaints"),
                value_at_stake=float(r.returns_value or 0.0),
                rate=float(r.return_rate),
            ))
        return out


@register
class DevRequestStalled(BaseDetector):
    """#20 — relationship debt. An R&D request left open past the point where a
    decision would normally have been made is a promise quietly not kept."""

    name = "dev_request_stalled"
    category = "risk"
    requires = ["engagement", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        eng = ctx.table("engagement")
        return eng.index[eng["dev_requests_open"] > 0].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        eng = self.frame(ctx)
        ages = eng.loc[eng["dev_requests_open"] > 0, "dev_request_oldest_open_days"].dropna()
        if ages.empty:
            return []
        threshold = float(st.dev_request_stall_days)
        if len(ages) >= st.min_percentile_observations:
            threshold = max(threshold, float(ages.quantile(st.aging_percentile / 100.0)))
        hits = eng.loc[eng["dev_request_oldest_open_days"] > threshold]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(r.dev_request_oldest_open_days, threshold, threshold * 3),
                headline_fa=(
                    f"{num(r.dev_requests_open)} درخواست توسعه باز، قدیمی‌ترین "
                    f"{num(r.dev_request_oldest_open_days)} روز بدون تصمیم "
                    f"(میانه تصمیم‌گیری در دفتر ۵۹ روز)."
                ),
                evidence_ids=ctx.ev(cid, "devreq", "crm"),
                value_at_stake=annual_revenue(ctx, cid) * 0.1,
                age_days=float(r.dev_request_oldest_open_days),
            ))
        return out
