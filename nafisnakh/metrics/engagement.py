"""CRM interactions, offers and R&D development requests.

Two cautions from PLAN travel with this module:

* ``آفرها`` has **no association with anything** (§1.2): discount, reason, type
  and validity are all independent of the outcome. That is the absence of a
  generator link, not a commercial finding, so offer *counts* and *timing* are
  used as engagement evidence while offer *effectiveness* is never claimed.
* ``Offer_Type = مدت‌دار`` is a financing concession, not a price cut (§5.3);
  its discount percentage is not comparable with a ``قیمتی`` offer, so the two
  are counted separately and never averaged together.

``Summary_Text`` is templated (``فوریت``/``کد پیگیری`` slots), so it is parsed
with a regex rather than embedded (§5.4).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..core.spine import visible
from ..io import schema as S
from .base import MetricContext, days_since, metric_table, num, pct, rows_ref

_URGENCY_RE = re.compile(r"فوریت[:\s]*([^\|،؛\n]+)")
_TRACKING_RE = re.compile(r"کد پیگیری[:\s]*([A-Za-z0-9\-]+)")


def parse_summary_slots(text: str) -> dict[str, str | None]:
    """Extract the template slots instead of embedding the template (§5.4)."""
    if not isinstance(text, str):
        return {"urgency": None, "tracking": None}
    return {
        "urgency": (m.group(1).strip() if (m := _URGENCY_RE.search(text)) else None),
        "tracking": (m.group(1).strip() if (m := _TRACKING_RE.search(text)) else None),
    }


@metric_table("engagement")
def build(ctx: MetricContext) -> pd.DataFrame:
    st = ctx.settings
    as_of = pd.Timestamp(ctx.as_of)
    index = pd.Index(sorted(set(ctx.spine.customers) | set(ctx.ds.customers[S.CUSTOMER_ID])),
                     name=S.CUSTOMER_ID)
    df = pd.DataFrame(index=index)

    # ---- CRM (rule #5: latest visible version per interaction)
    crm = visible(ctx.ds.crm_latest, ctx.as_of)
    crm = crm.loc[pd.to_datetime(crm[S.X_EVENT_TIME], errors="coerce") <= as_of]
    g = crm.groupby(S.CUSTOMER_ID)
    df["crm_interactions"] = g[S.X_ID].nunique().reindex(index).fillna(0.0)
    df["crm_last_at"] = g[S.X_EVENT_TIME].max().reindex(index)
    df["days_since_crm"] = days_since(as_of, df["crm_last_at"])
    for label, itype in [
        ("crm_price_talks", "قیمت و تخفیف"),
        ("crm_quality_talks", "کیفیت محصول"),
        ("crm_collection_talks", "وصول مطالبات"),
        ("crm_plan_talks", "برنامه خرید"),
    ]:
        df[label] = (
            crm.loc[crm[S.X_TYPE] == itype].groupby(S.CUSTOMER_ID)[S.X_ID]
            .nunique().reindex(index).fillna(0.0)
        )

    # ---- offers: counts and timing only, never effectiveness (§1.2)
    off = visible(ctx.ds.offers, ctx.as_of)
    off = off.loc[pd.to_datetime(off[S.O_DATE], errors="coerce") <= as_of]
    og = off.groupby(S.CUSTOMER_ID)
    df["offers_total"] = og[S.O_ID].count().reindex(index).fillna(0.0)
    df["offers_won"] = (
        off.loc[off[S.O_RESULT] == S.O_RESULT_WON].groupby(S.CUSTOMER_ID)[S.O_ID]
        .count().reindex(index).fillna(0.0)
    )
    price_offers = off.loc[off[S.O_TYPE] != S.O_TYPE_FINANCING]
    df["offers_price_type"] = (
        price_offers.groupby(S.CUSTOMER_ID)[S.O_ID].count().reindex(index).fillna(0.0)
    )
    df["offers_financing_type"] = (
        off.loc[off[S.O_TYPE] == S.O_TYPE_FINANCING].groupby(S.CUSTOMER_ID)[S.O_ID]
        .count().reindex(index).fillna(0.0)
    )
    # discount is only averaged inside the price-cut family, never across types
    df["discount_pct_mean_price_type"] = (
        price_offers.groupby(S.CUSTOMER_ID)[S.O_DISCOUNT_PCT].mean().reindex(index)
    )
    df["discount_given_total"] = (
        price_offers.assign(
            _gap=lambda d: (
                pd.to_numeric(d[S.O_BASE_PRICE], errors="coerce")
                - pd.to_numeric(d[S.O_OFFERED_PRICE], errors="coerce")
            )
        ).groupby(S.CUSTOMER_ID)["_gap"].sum().reindex(index).fillna(0.0)
    )

    # ---- development requests: open, decided, stalled
    dev = visible(ctx.ds.dev_requests, ctx.as_of)
    dev = dev.loc[pd.to_datetime(dev[S.D_CREATED_AT], errors="coerce") <= as_of].copy()
    dev["_decision"] = pd.to_datetime(dev[S.D_DECISION_AT], errors="coerce")
    dev["_open"] = dev["_decision"].isna() | (dev["_decision"] > as_of)
    dev["_age_days"] = np.where(
        dev["_open"], (as_of - pd.to_datetime(dev[S.D_CREATED_AT])).dt.days,
        (dev["_decision"] - pd.to_datetime(dev[S.D_CREATED_AT])).dt.days,
    )
    dg = dev.groupby(S.CUSTOMER_ID)
    df["dev_requests_total"] = dg[S.D_ID].count().reindex(index).fillna(0.0)
    df["dev_requests_open"] = dg["_open"].sum().reindex(index).fillna(0.0)
    df["dev_request_oldest_open_days"] = (
        dev.loc[dev["_open"]].groupby(S.CUSTOMER_ID)["_age_days"].max().reindex(index)
    )
    df["dev_requests_approved"] = (
        dev.loc[dev[S.D_STATUS] == S.D_STATUS_APPROVED].groupby(S.CUSTOMER_ID)[S.D_ID]
        .count().reindex(index).fillna(0.0)
    )

    # ---- market signals (concurrent descriptor only, never a leading indicator)
    mkt = visible(ctx.ds.market, ctx.as_of)
    df["market_demand_down"] = (
        mkt.loc[mkt[S.M_DEMAND_CHANGE] == "کاهش"].groupby(S.CUSTOMER_ID)[S.M_WEEK_ID]
        .count().reindex(index).fillna(0.0)
    )

    window = ctx.window(st.long_window_months)
    dev_open_ids = dev.loc[dev["_open"]].groupby(S.CUSTOMER_ID)[S.D_ID].apply(list)
    crm_ids = g[S.X_ID].apply(list)

    for cid, r in df.iterrows():
        if r.crm_interactions > 0:
            ctx.emit(
                cid, "crm",
                f"{num(r.crm_interactions)} تعامل CRM ثبت شده و آخرین تماس "
                f"{num(r.days_since_crm)} روز پیش بوده است.",
                float(r.crm_interactions), unit="مورد", kind="event",
                window=window, source_rows=rows_ref(S.S_CRM, crm_ids.get(cid, [])[-4:]),
                formula="count(latest Record_Version per Interaction_ID) [rule #5]",
            )
        if r.dev_requests_open > 0 and pd.notna(r.dev_request_oldest_open_days):
            ctx.emit(
                cid, "devreq",
                f"{num(r.dev_requests_open)} درخواست توسعه باز دارد و قدیمی‌ترین آن "
                f"{num(r.dev_request_oldest_open_days)} روز بدون تصمیم مانده است.",
                float(r.dev_request_oldest_open_days), unit="روز", kind="event",
                window=window,
                source_rows=rows_ref(S.S_DEV_REQUESTS, dev_open_ids.get(cid, [])),
                formula="as_of − Created_At where Decision_At is null",
            )
        if r.offers_total > 0:
            ctx.emit(
                cid, "offers",
                f"{num(r.offers_total)} پیشنهاد قیمتی/مدت‌دار برای این مشتری ثبت شده است "
                f"({num(r.offers_price_type)} قیمتی و {num(r.offers_financing_type)} مدت‌دار).",
                float(r.offers_total), unit="مورد", kind="event",
                window=window, source_rows=rows_ref(S.S_OFFERS, [cid], key=S.CUSTOMER_ID),
                formula="count(آفرها)",
                caveat=("مدت‌دار is a financing concession, not a price cut; the two "
                        "discount scales are not comparable (§5.3). Offer effectiveness "
                        "is NOT claimed — the sheet has no association with outcome (§1.2)."),
            )
    return df
