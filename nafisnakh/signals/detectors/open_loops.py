"""Open-loop detectors #24–#27 — the things *we* left unfinished (PLAN §3.4).

Detectors #1–#23 look at the customer. These four look at us. The distinction
matters commercially: a customer who is buying less is a diagnosis that needs a
conversation, but an approved sample nobody priced is an action the sales
manager can take before lunch, with no new information required from anyone.

They share one design decision worth stating. **The absence being detected must
be checkable.** "No offer since the approval" is a fact about the offers sheet,
falsifiable by a single row. "The rep never phoned" is not — nothing in this
workbook records a phone call that produced nothing — so #26 says *no record of
follow-through* and carries ``falsifiable`` in its detail, which is a weaker and
honest claim rather than a strong and unsupportable one.

Money at stake follows the house convention (``annual_revenue × share``) only
where nothing better exists. Where the data can measure the amount — the family
this customer already buys, what same-segment peers spend on the family a stalled
sample belongs to — it is measured, and ``stake_basis`` says which was used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...io import schema as S
from ...metrics.base import MetricContext, money, num
from ..base import BaseDetector, Signal, annual_revenue, register, scale

# How much of a year's revenue a written-down-and-dropped next action puts at
# risk, by what was promised. A price meeting that never happened is a different
# order of neglect from an unmade follow-up call, and flattening them would rank
# 258 accounts by revenue alone.
NEXT_ACTION_STAKE_SHARE = {
    "جلسه قیمت": 0.20,
    "ارسال نمونه": 0.15,
    "بازدید فنی": 0.10,
    "پیگیری تلفنی": 0.05,
}


def _family_revenue(ctx: MetricContext) -> pd.DataFrame:
    """Customer × family revenue over the long window, annualised.

    Cached on the context so four detectors and, later, the 360° page do not
    each rebuild it.
    """
    key = "family_revenue_annualised"
    if key in ctx.cache:
        return ctx.cache[key]
    months = ctx.settings.long_window_months
    start = pd.Timestamp(ctx.window(months)[0])
    lines = ctx.spine.lines
    recent = lines.loc[lines[S.F_DATE] > start]
    out = (
        recent.groupby([S.CUSTOMER_ID, S.P_FAMILY])[S.D_REVENUE].sum()
        .unstack(fill_value=0.0)
        * (12.0 / months)
    )
    ctx.cache[key] = out
    return out


def _product_family(ctx: MetricContext) -> pd.Series:
    products = ctx.ds.frames[S.S_PRODUCTS]
    return products.drop_duplicates(S.PRODUCT_ID).set_index(S.PRODUCT_ID)[S.P_FAMILY]


@register
class DevSampleReadyNoOffer(BaseDetector):
    """#24 — R&D approved the sample and sales never priced it.

    The most literal open loop in the book: the company spent development effort,
    said yes, and then let the ball sit. At the demo anchor 21 customers are in
    this state with a median 176 days elapsed.
    """

    name = "dev_sample_ready_no_offer"
    category = "opportunity"
    requires = ["open_loops", "rfm", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        """Customers who have ever had a development request approved.

        Anyone else cannot possibly be in this state, and dividing by the whole
        book would call a correct detector "too narrow".
        """
        from ...core.spine import visible

        dev = visible(ctx.ds.dev_requests, ctx.as_of)
        dec = pd.to_datetime(dev[S.D_DECISION_AT], errors="coerce")
        appr = dev.loc[(dev[S.D_STATUS] == S.D_STATUS_APPROVED)
                       & dec.notna() & (dec <= pd.Timestamp(ctx.as_of))]
        return pd.Index(sorted(set(appr[S.CUSTOMER_ID]))).intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        hits = df.loc[df["dev_approved_open"] > 0]
        if hits.empty:
            return []
        fam_rev = _family_revenue(ctx)
        prod_fam = _product_family(ctx)
        segments = ctx.cohorts.customer_segment
        out = []
        for cid, r in hits.iterrows():
            families = sorted({
                f for f in (prod_fam.get(p) for p in r.dev_approved_open_products)
                if isinstance(f, str)
            })
            stake, basis = self._stake(ctx, cid, families, fam_rev, segments, r)
            out.append(self.signal(
                ctx, cid,
                severity=scale(float(r.dev_approved_open_days), 30, 365, floor=30.0),
                direction="static",
                headline_fa=(
                    f"نمونه تأییدشده بدون آفر مانده است: {num(r.dev_approved_open)} "
                    f"درخواست توسعه «نمونه تأیید» دارد و "
                    f"{num(r.dev_approved_open_days)} روز است هیچ آفری برای این مشتری "
                    f"ثبت نشده — ارزش تخمینی بازار این خانواده "
                    f"{money(stake, st)} ریال در سال."
                ),
                evidence_ids=ctx.ev(cid, "loop-sample", "devreq", "rfm", "revenue"),
                value_at_stake=stake,
                suggested_bucket="grow",
                request_ids=list(r.dev_approved_open_ids),
                families=families,
                stalled_days=float(r.dev_approved_open_days),
                stake_basis=basis,
            ))
        return out

    def _stake(self, ctx, cid, families, fam_rev, segments, row):
        """What the unpriced approval is worth, measured wherever possible."""
        if families:
            cols = [f for f in families if f in fam_rev.columns]
            if cols:
                seg = segments.get(cid)
                peers = [c for c in fam_rev.index if segments.get(c) == seg]
                block = fam_rev.loc[peers, cols] if peers else fam_rev[cols]
                buyers = block.loc[(block > 0).any(axis=1)]
                if len(buyers) >= ctx.settings.cross_sell_min_peers:
                    return float(buyers.sum(axis=1).mean()), "peer_family_spend"
        return float(row.get("median_order_value", 0.0) or 0.0), "own_typical_order"


@register
class DevRejectedUncommunicated(BaseDetector):
    """#25 — we said no and never told them.

    ``فنی رد`` is a decision the customer is entitled to hear. Nothing in the CRM
    since the decision date means, as far as the record goes, they are still
    waiting. This is a relationship risk rather than a lost sale, so it is scored
    as risk and its money at stake is a share of the account, not of a product.
    """

    name = "dev_rejected_uncommunicated"
    category = "risk"
    requires = ["open_loops", "engagement", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        from ...core.spine import visible

        dev = visible(ctx.ds.dev_requests, ctx.as_of)
        dec = pd.to_datetime(dev[S.D_DECISION_AT], errors="coerce")
        rej = dev.loc[(dev[S.D_STATUS] == S.D_STATUS_REJECTED)
                      & dec.notna() & (dec <= pd.Timestamp(ctx.as_of))]
        return pd.Index(sorted(set(rej[S.CUSTOMER_ID]))).intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        df = self.frame(ctx)
        hits = df.loc[df["dev_rejected_unspoken"] > 0]
        out = []
        for cid, r in hits.iterrows():
            out.append(self.signal(
                ctx, cid,
                severity=scale(float(r.dev_rejected_unspoken_days), 30, 365, floor=25.0),
                direction="deteriorating",
                headline_fa=(
                    f"پاسخ رد فنی به مشتری منتقل نشده است: "
                    f"{num(r.dev_rejected_unspoken)} درخواست «فنی رد» شده و "
                    f"{num(r.dev_rejected_unspoken_days)} روز است هیچ تعامل CRM با این "
                    f"مشتری ثبت نشده — مشتری هنوز منتظر جواب است."
                ),
                evidence_ids=ctx.ev(cid, "loop-rejection", "crm", "devreq"),
                value_at_stake=annual_revenue(ctx, cid) * 0.15,
                suggested_bucket="protect",
                request_ids=list(r.dev_rejected_unspoken_ids),
                silent_days=float(r.dev_rejected_unspoken_days),
                stake_basis="annual_revenue_share",
            ))
        return out


@register
class CrmPromiseOutstanding(BaseDetector):
    """#26 — a next action was written down and nothing followed.

    Fires only on the **latest** interaction: an old promise superseded by a
    later conversation is history, not an open loop.

    The claim is deliberately weak where the data is weak. For ``جلسه قیمت`` and
    ``ارسال نمونه`` a follow-through would leave a row (an offer, a development
    request) and its absence is provable; for ``پیگیری تلفنی`` and ``بازدید فنی``
    nothing in this workbook would record it either way, so the signal says *no
    record* and carries ``falsifiable: false``.
    """

    name = "crm_promise_outstanding"
    category = "efficiency"
    requires = ["open_loops", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        loops = ctx.table("open_loops")
        return loops.index[loops["next_action_type"].notna()].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        hits = df.loc[
            df["next_action_open"].fillna(False)
            & (df["next_action_age_days"] >= st.next_action_stale_days)
        ]
        out = []
        for cid, r in hits.iterrows():
            share = NEXT_ACTION_STAKE_SHARE.get(r.next_action_type, 0.05)
            proof = ("و هیچ ردی از انجام آن در آفرها یا درخواست‌های توسعه نیست"
                     if r.next_action_trace_exists
                     else "و این نوع اقدام در داده‌ها رد قابل بررسی ندارد")
            out.append(self.signal(
                ctx, cid,
                severity=scale(float(r.next_action_age_days),
                               st.next_action_stale_days, 400,
                               floor=20.0 if r.next_action_trace_exists else 15.0),
                direction="static",
                headline_fa=(
                    f"اقدام بعدی معلق: آخرین تعامل CRM «{r.next_action_type}» را ثبت "
                    f"کرده، {num(r.next_action_age_days)} روز گذشته {proof}."
                ),
                evidence_ids=ctx.ev(cid, "loop-nextaction", "crm"),
                value_at_stake=annual_revenue(ctx, cid) * share,
                suggested_bucket=None,
                next_action=r.next_action_type,
                age_days=float(r.next_action_age_days),
                interaction_id=r.next_action_id,
                falsifiable=bool(r.next_action_trace_exists),
                stake_basis="annual_revenue_share",
            ))
        return out


@register
class OfferNegotiationStalled(BaseDetector):
    """#27 — an offer left hanging long past the validity it set itself.

    Rule #4 decides what "hanging" means: the offer's outcome is knowable only
    from ``Decision_Available_At``. At the demo anchor 403 visible offers have no
    knowable decision and 353 of them are already past their own validity window
    — median validity is 18 days, median age 315.

    No claim is made about *why*. The offers sheet has no association between
    discount, reason or type and the eventual result (PLAN §1.2), so this
    detector reports an abandoned process, never a failed price.
    """

    name = "offer_negotiation_stalled"
    category = "opportunity"
    requires = ["open_loops", "engagement", "economics", "rfm"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        from ...core.spine import visible

        off = visible(ctx.ds.offers, ctx.as_of)
        off = off.loc[pd.to_datetime(off[S.O_DATE], errors="coerce")
                      <= pd.Timestamp(ctx.as_of)]
        return pd.Index(sorted(set(off[S.CUSTOMER_ID]))).intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        hits = df.loc[df["offers_abandoned"] > 0]
        if hits.empty:
            return []
        fam_rev = _family_revenue(ctx)
        out = []
        for cid, r in hits.iterrows():
            families = [f for f in r.offers_abandoned_families if f in fam_rev.columns]
            own = (float(fam_rev.loc[cid, families].sum())
                   if families and cid in fam_rev.index else 0.0)
            basis = "own_family_revenue"
            if own <= 0:
                own = float(r.get("median_order_value", 0.0) or 0.0)
                basis = "own_typical_order"
            out.append(self.signal(
                ctx, cid,
                severity=scale(float(r.offers_abandoned_days), 30, 365, floor=20.0),
                direction="static",
                headline_fa=(
                    f"{num(r.offers_abandoned)} آفر بی‌پاسخ و گذشته از مهلت اعتبار "
                    f"دارد؛ قدیمی‌ترین {num(r.offers_abandoned_days)} روز — در این "
                    f"خانواده کالا سالانه {money(own, st)} ریال از این مشتری فروش هست."
                ),
                evidence_ids=ctx.ev(cid, "loop-offer", "offers", "rfm"),
                value_at_stake=own,
                suggested_bucket="grow",
                offer_ids=list(r.offers_abandoned_ids),
                families=list(r.offers_abandoned_families),
                oldest_days=float(r.offers_abandoned_days),
                stake_basis=basis,
                caveat=("آفر رها شده گزارش می‌شود، نه شکست قیمت — شیت آفرها هیچ "
                        "ارتباطی با نتیجه ندارد (§1.2)."),
            ))
        return out
