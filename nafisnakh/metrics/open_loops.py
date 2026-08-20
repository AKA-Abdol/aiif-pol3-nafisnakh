"""Open loops — promises the company made and has not closed (PLAN §2).

Every other metric table describes what the *customer* did. This one describes
what **we** did and then stopped doing: a sample we approved and never priced, a
rejection we never told them about, a next action we wrote down and never took,
an offer left hanging months past its own validity. These are the items a sales
manager can act on today without needing anything new from the customer, which
is why they belong in the meeting agenda ahead of most of the risk detectors.

Two rules from PLAN govern every line below.

**State, never outcome.** ``Status`` and ``Decision_At`` on ``درخواست_توسعه``
are coherent — a decision date is present for exactly the three decided statuses
and absent for ``درحال بررسی``. ``Outcome_Text`` is *not*: measured on the full
sheet it is independent of ``Status`` (χ², p≈0.94), and a request marked
``فنی رد`` carries the text "sample ready for customer testing" 55 times. So the
loops are built on status and dates, and the outcome prose is never read.

**Rule #4, applied to knowability, not to the calendar.** An offer's ``Result``
is knowable only from ``Decision_Available_At``. At the demo anchor 403 visible
offers have no knowable decision, and 46 of them already carry a ``Result`` in
the raw sheet — a result the sales manager could not have seen that day. Those
46 are correctly treated here as still open. An offer whose decision is not yet
knowable and whose validity expired long ago is an abandoned offer regardless of
what the sheet eventually says.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.spine import visible
from ..io import schema as S
from .base import MetricContext, days_since, metric_table, num, rows_ref

# What, if anything, in the rest of the workbook would prove a promised next
# action was actually carried out. Where the value is empty there is no trace
# anywhere in the data, so the claim is "no record of follow-through" — never
# "it did not happen". The distinction is carried into the evidence text.
NEXT_ACTION_TRACE = {
    "جلسه قیمت": ("offer",),        # a price meeting that led anywhere leaves an offer
    "ارسال نمونه": ("dev", "offer"),  # a sample leaves a development request or an offer
    "پیگیری تلفنی": (),
    "بازدید فنی": (),
}
NO_ACTION = "بدون اقدام"


@metric_table("open_loops")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    as_of = pd.Timestamp(ctx.as_of)
    index = pd.Index(sorted(set(ctx.spine.customers)), name=S.CUSTOMER_ID)
    df = pd.DataFrame(index=index)

    dev = visible(ctx.ds.dev_requests, ctx.as_of)
    dev = dev.loc[pd.to_datetime(dev[S.D_CREATED_AT], errors="coerce") <= as_of].copy()
    dev["_decided_at"] = pd.to_datetime(dev[S.D_DECISION_AT], errors="coerce")
    decided = dev.loc[dev["_decided_at"].notna() & (dev["_decided_at"] <= as_of)]

    off = visible(ctx.ds.offers, ctx.as_of)
    off = off.loc[pd.to_datetime(off[S.O_DATE], errors="coerce") <= as_of].copy()
    off["_offered_at"] = pd.to_datetime(off[S.O_DATE], errors="coerce")

    crm = visible(ctx.ds.crm_latest, ctx.as_of)
    crm = crm.loc[pd.to_datetime(crm[S.X_EVENT_TIME], errors="coerce") <= as_of].copy()
    crm["_at"] = pd.to_datetime(crm[S.X_EVENT_TIME], errors="coerce")

    last_offer = off.groupby(S.CUSTOMER_ID)["_offered_at"].max()
    last_crm = crm.groupby(S.CUSTOMER_ID)["_at"].max()
    last_dev = dev.groupby(S.CUSTOMER_ID)[S.D_CREATED_AT].max()

    # ---- loop 1: sample approved, never turned into an offer ---------------
    # `نمونه تأیید` means R&D said yes and the ball came back to sales. If no
    # offer has gone out since that decision, the approval is sitting unused.
    stalled_appr = _nothing_since(
        decided.loc[decided[S.D_STATUS] == S.D_STATUS_APPROVED],
        last_offer, as_of, st.open_loop_grace_days,
    )

    # ---- loop 2: technically rejected, never communicated ------------------
    # `فنی رد` is the answer the customer is waiting for. If there has been no
    # CRM contact of any kind since the decision, nobody has told them.
    unspoken = _nothing_since(
        decided.loc[decided[S.D_STATUS] == S.D_STATUS_REJECTED],
        last_crm, as_of, st.open_loop_grace_days,
    )

    for prefix, frame in (("dev_approved_open", stalled_appr),
                          ("dev_rejected_unspoken", unspoken)):
        g = frame.groupby(S.CUSTOMER_ID) if len(frame) else None
        df[prefix] = (g[S.D_ID].count().reindex(index).fillna(0.0) if g is not None
                      else 0.0)
        df[f"{prefix}_days"] = (g["_age"].max().reindex(index) if g is not None
                                else np.nan)
        df[f"{prefix}_ids"] = _lists(frame, S.D_ID, index)
        df[f"{prefix}_products"] = _lists(frame, S.PRODUCT_ID, index, unique=True)

    # ---- loop 3: a next action written down and left ------------------------
    # Only the *latest* interaction counts: an older promise superseded by a
    # later conversation is not an open loop, it is history.
    last_row = crm.sort_values("_at").groupby(S.CUSTOMER_ID).tail(1).set_index(S.CUSTOMER_ID)
    df["next_action_type"] = last_row[S.X_NEXT_ACTION].reindex(index)
    df["next_action_at"] = last_row["_at"].reindex(index)
    df["next_action_id"] = last_row[S.X_ID].reindex(index)
    df["next_action_age_days"] = days_since(as_of, df["next_action_at"])

    traced = []
    for cid in index:
        action = df.at[cid, "next_action_type"]
        stamp = df.at[cid, "next_action_at"]
        if not isinstance(action, str) or action == NO_ACTION or pd.isna(stamp):
            traced.append(False)
            continue
        traces = NEXT_ACTION_TRACE.get(action, ())
        done = False
        if "offer" in traces:
            done |= bool(pd.notna(last_offer.get(cid, pd.NaT))
                         and last_offer.get(cid) > stamp)
        if "dev" in traces:
            done |= bool(pd.notna(last_dev.get(cid, pd.NaT))
                         and pd.Timestamp(last_dev.get(cid)) > stamp)
        traced.append(done)
    df["next_action_followed_through"] = traced
    df["next_action_open"] = (
        df["next_action_type"].notna()
        & (df["next_action_type"] != NO_ACTION)
        & ~df["next_action_followed_through"]
    )
    # whether the absence of follow-through is *provable* or merely unrecorded
    df["next_action_trace_exists"] = [
        bool(NEXT_ACTION_TRACE.get(a, ())) if isinstance(a, str) else False
        for a in df["next_action_type"]
    ]

    # ---- loop 4: offers abandoned past their own validity -------------------
    decision_known = pd.to_datetime(off[S.O_DECISION_AVAILABLE_AT], errors="coerce")
    open_offers = off.loc[decision_known.isna() | (decision_known > as_of)].copy()
    open_offers["_age"] = (as_of - open_offers["_offered_at"]).dt.days
    open_offers["_validity"] = pd.to_numeric(
        open_offers[S.O_VALIDITY_DAYS], errors="coerce"
    )
    abandoned = open_offers.loc[open_offers["_age"] > open_offers["_validity"]]
    ag = abandoned.groupby(S.CUSTOMER_ID) if len(abandoned) else None
    df["offers_abandoned"] = (ag[S.O_ID].count().reindex(index).fillna(0.0)
                              if ag is not None else 0.0)
    df["offers_abandoned_days"] = (ag["_age"].max().reindex(index)
                                   if ag is not None else np.nan)
    df["offers_abandoned_ids"] = _lists(abandoned, S.O_ID, index)
    df["offers_abandoned_families"] = _lists(abandoned, S.O_FAMILY, index, unique=True)

    df["open_loop_count"] = (
        df["dev_approved_open"].fillna(0)
        + df["dev_rejected_unspoken"].fillna(0)
        + df["next_action_open"].astype(int)
        + df["offers_abandoned"].fillna(0)
    )

    window = ctx.window(st.long_window_months)
    for cid, r in df.iterrows():
        if r.dev_approved_open > 0:
            ctx.emit(
                cid, "loop-sample",
                f"{num(r.dev_approved_open)} درخواست توسعه با وضعیت «نمونه تأیید» دارد که "
                f"از زمان تصمیم، هیچ آفری برای این مشتری ثبت نشده است — قدیمی‌ترین "
                f"{num(r.dev_approved_open_days)} روز.",
                float(r.dev_approved_open), unit="مورد", kind="event", window=window,
                source_rows=rows_ref(S.S_DEV_REQUESTS, r.dev_approved_open_ids),
                formula=("count(Status = نمونه تأیید, Decision_At ≤ as_of) where "
                         "max(Offer_Date) ≤ Decision_At"),
                products=list(r.dev_approved_open_products),
                caveat=("Status و Decision_At مبنا هستند؛ Outcome_Text در این شیت با "
                        "Status هم‌بسته نیست و خوانده نمی‌شود."),
            )
        if r.dev_rejected_unspoken > 0:
            ctx.emit(
                cid, "loop-rejection",
                f"{num(r.dev_rejected_unspoken)} درخواست توسعه «فنی رد» شده و از تاریخ "
                f"تصمیم هیچ تعامل CRM با این مشتری ثبت نشده است — قدیمی‌ترین "
                f"{num(r.dev_rejected_unspoken_days)} روز.",
                float(r.dev_rejected_unspoken), unit="مورد", kind="event", window=window,
                source_rows=rows_ref(S.S_DEV_REQUESTS, r.dev_rejected_unspoken_ids),
                formula=("count(Status = فنی رد, Decision_At ≤ as_of) where "
                         "max(Event_Time) ≤ Decision_At [rule #5 latest version]"),
            )
        if r.next_action_open and pd.notna(r.next_action_age_days):
            proof = ("هیچ ردی از انجام آن در داده‌ها نیست"
                     if r.next_action_trace_exists
                     else "این نوع اقدام در داده‌ها رد قابل بررسی ندارد")
            ctx.emit(
                cid, "loop-nextaction",
                f"آخرین تعامل CRM اقدام بعدی «{r.next_action_type}» را ثبت کرده و "
                f"{num(r.next_action_age_days)} روز از آن گذشته است — {proof}.",
                float(r.next_action_age_days), unit="روز", kind="event", window=window,
                source_rows=rows_ref(S.S_CRM, [r.next_action_id]),
                formula="as_of − Event_Time of the latest interaction with Next_Action ≠ بدون اقدام",
                next_action=r.next_action_type,
                falsifiable=bool(r.next_action_trace_exists),
            )
        if r.offers_abandoned > 0:
            ctx.emit(
                cid, "loop-offer",
                f"{num(r.offers_abandoned)} آفر بدون پاسخ مانده که مهلت اعتبار خودش را "
                f"رد کرده است — قدیمی‌ترین {num(r.offers_abandoned_days)} روز.",
                float(r.offers_abandoned), unit="مورد", kind="event", window=window,
                source_rows=rows_ref(S.S_OFFERS, r.offers_abandoned_ids),
                formula=("count(offers with Decision_Available_At > as_of or null, "
                         "age > Validity_Days) [rule #4]"),
                families=list(r.offers_abandoned_families),
            )
    return df


def _nothing_since(
    requests: pd.DataFrame, last_contact: pd.Series, as_of: pd.Timestamp, grace: int
) -> pd.DataFrame:
    """Decided requests where nothing has happened since the decision.

    ``last_contact`` is the customer's most recent event of whatever kind closes
    this loop — an offer for an approved sample, any CRM interaction for a
    rejection. A customer absent from it has never had one at all, which counts
    as "nothing since".
    """
    if not len(requests):
        return requests.assign(_age=pd.Series(dtype=float))
    out = requests.copy()
    out["_age"] = (as_of - out["_decided_at"]).dt.days
    latest = out[S.CUSTOMER_ID].map(last_contact)
    return out.loc[(out["_age"] >= grace) & (latest.isna() | (latest <= out["_decided_at"]))]


def _lists(frame: pd.DataFrame, column: str, index: pd.Index, *, unique: bool = False):
    """Per-customer list column, empty list where the customer has no rows.

    Detectors cite row ids, so the ids have to survive the groupby rather than
    being recomputed later from a different filter — that is how a citation and
    the number it supports drift apart.
    """
    if not len(frame) or column not in frame.columns:
        return pd.Series([[] for _ in index], index=index)
    agg = frame.groupby(S.CUSTOMER_ID)[column].apply(
        lambda s: sorted(set(s.dropna())) if unique else list(s.dropna())
    )
    return agg.reindex(index).apply(lambda v: v if isinstance(v, list) else [])
