"""The eight customer tools (PLAN §3.9, step 4).

Each answers one question a sales manager actually asks before a meeting, and
each answers it in **claims backed by locators**, never in loose numbers. Where
the metric layer has already emitted the fact, the tool reuses that evidence
rather than minting a second id for the same thing; where the fact is row-level
and nothing has emitted it — this particular development request, this
complaint, this offer — the tool mints it here, with the row ids that back it.

Two data realities are encoded rather than discovered again by whoever reads
this next:

* **``Outcome_Text`` on ``درخواست_توسعه`` is never read.** It is independent of
  ``Status`` (χ², p≈0.94); a request marked ``فنی رد`` carries "sample ready for
  customer testing" 55 times. :func:`get_dev_requests` reads status and dates.
* **``سیگنال_بازار`` is a family-level weekly report, not a customer signal.**
  130 rows across 7 families for 526 customers, and only 59 rows carry any
  ``Customer_ID`` at all. :func:`get_market_context` therefore reports the market
  for the family this customer buys, and says so in its own note, because an
  agent handed these rows without that caveat will read them as being about the
  customer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.spine import visible
from ..io import schema as S
from ..metrics.base import MetricContext, money, num, pct, rows_ref
from .base import ToolResult, tool


# --------------------------------------------------------------------- helpers
def _reuse(ctx: MetricContext, cid: str, *slugs: str) -> tuple[list[str], list[str]]:
    """Evidence the metric layer already emitted, as (ids, claims).

    Minting a second id for a fact that already has one is how a 360° page ends
    up listing the same claim twice with two different ids.
    """
    ids = ctx.ev(cid, *slugs)
    return ids, [ctx.evidence.get(i).claim_fa for i in ids]


def _result(tool_name, cid, ids, claims, payload, note="", empty="") -> ToolResult:
    return ToolResult(
        tool=tool_name, customer_id=cid, claims=claims, evidence_ids=ids,
        payload=payload, note_fa=note, empty_reason_fa=empty,
    )


def _asof(ctx: MetricContext) -> pd.Timestamp:
    return pd.Timestamp(ctx.as_of)


def _dominant_family(ctx: MetricContext, cid: str) -> str | None:
    """The family this customer mostly buys.

    ``mix.dominant_family`` is computed over the *recent* window and is therefore
    empty for anyone who has gone quiet — which is a large share of the accounts
    a meeting is being prepared for. Falling back to the whole visible history
    answers the question that was actually asked instead of refusing it.
    """
    mix = ctx.table("mix")
    if cid in mix.index and isinstance(mix.loc[cid, "dominant_family"], str):
        return mix.loc[cid, "dominant_family"]
    lines = ctx.spine.lines
    mine = lines.loc[lines[S.CUSTOMER_ID] == cid]
    if mine.empty:
        return None
    by_family = mine.groupby(S.P_FAMILY)[S.D_REVENUE].sum()
    return str(by_family.idxmax()) if len(by_family) else None


def _customer_rows(ctx: MetricContext, sheet: str, date_column: str, cid: str):
    """Visible rows of one sheet for one customer, dated at or before ``as_of``."""
    df = visible(ctx.ds.frames[sheet], ctx.as_of)
    df = df.loc[df[S.CUSTOMER_ID] == cid]
    stamps = pd.to_datetime(df[date_column], errors="coerce")
    return df.loc[stamps <= _asof(ctx)].assign(_at=stamps)


# ------------------------------------------------------------------- the tools
@tool(
    "get_dev_requests",
    "درخواست‌های توسعه این مشتری: نوع، وضعیت، تاریخ تصمیم و سن هر درخواست.",
    limit="حداکثر تعداد درخواست (پیش‌فرض ۸، جدیدترین اول)",
)
def get_dev_requests(ctx: MetricContext, customer_id: str, limit: int = 8) -> ToolResult:
    rows = _customer_rows(ctx, S.S_DEV_REQUESTS, S.D_CREATED_AT, customer_id)
    if rows.empty:
        return _result("get_dev_requests", customer_id, [], [], {},
                       empty=f"تا {ctx.as_of.isoformat()} هیچ درخواست توسعه‌ای از این "
                             "مشتری ثبت نشده است.")
    rows = rows.sort_values("_at", ascending=False).head(limit)
    ids, claims, items = [], [], []
    for _, r in rows.iterrows():
        decided = pd.to_datetime(r[S.D_DECISION_AT], errors="coerce")
        known = pd.notna(decided) and decided <= _asof(ctx)
        age = int((_asof(ctx) - (decided if known else r["_at"])).days)
        state = (f"در وضعیت «{r[S.D_STATUS]}» و {age} روز از تصمیم گذشته"
                 if known else f"هنوز تصمیمی نگرفته‌ایم و {age} روز از ثبت آن گذشته")
        ev = ctx.emit(
            customer_id, "devitem",
            f"درخواست توسعه {r[S.D_ID]} از نوع «{r[S.D_TYPE]}» {state} است.",
            str(r[S.D_STATUS]) if known else "بی‌تصمیم", unit=None, kind="event",
            window=(r["_at"].date(), ctx.as_of),
            source_rows=rows_ref(S.S_DEV_REQUESTS, [r[S.D_ID]]),
            formula="Status و Decision_At — Outcome_Text خوانده نمی‌شود (§3.4)",
            request_type=r[S.D_TYPE], owner_unit=r.get(S.D_OWNER_UNIT),
            decided=bool(known), age_days=age,
        )
        ids.append(ev.id)
        claims.append(ev.claim_fa)
        items.append({"request_id": r[S.D_ID], "status": r[S.D_STATUS],
                      "type": r[S.D_TYPE], "decided": bool(known), "age_days": age})
    extra_ids, extra_claims = _reuse(ctx, customer_id,
                                     "devreq", "loop-sample", "loop-rejection")
    return _result(
        "get_dev_requests", customer_id, ids + extra_ids, claims + extra_claims,
        {"requests": items, "total_visible": int(len(
            _customer_rows(ctx, S.S_DEV_REQUESTS, S.D_CREATED_AT, customer_id)))},
        note=("وضعیت و تاریخ تصمیم مبنا هستند؛ متن نتیجه (Outcome_Text) در این شیت "
              "با وضعیت هم‌بسته نیست و استناد به آن مجاز نیست."),
    )


@tool(
    "get_complaints",
    "شکایات این مشتری: سازوکار فنی، شدت، وضعیت پرونده و نتیجه بررسی.",
    limit="حداکثر تعداد شکایت (پیش‌فرض ۸، جدیدترین اول)",
)
def get_complaints(ctx: MetricContext, customer_id: str, limit: int = 8) -> ToolResult:
    rows = _customer_rows(ctx, S.S_COMPLAINTS, S.K_CREATED_AT, customer_id)
    if rows.empty:
        return _result("get_complaints", customer_id, [], [], {},
                       empty=f"تا {ctx.as_of.isoformat()} هیچ شکایتی از این مشتری ثبت "
                             "نشده است.")
    mech = _by_complaint(ctx, "llm_complaints")
    reso = _by_complaint(ctx, "llm_resolutions")
    rows = rows.sort_values("_at", ascending=False).head(limit)

    ids, claims, items = [], [], []
    for _, r in rows.iterrows():
        kid = r[S.K_ID]
        m, rs = mech.get(kid, {}), reso.get(kid, {})
        # Rule #4 twice over: the complaint is visible from Available_At, its
        # answer only from Resolution_Available_At. A resolved complaint whose
        # resolution is not yet knowable is still an open file to the reader.
        r_at = pd.to_datetime(r[S.K_RESOLUTION_AVAILABLE_AT], errors="coerce")
        answered = pd.notna(r_at) and r_at <= _asof(ctx)
        age = int((_asof(ctx) - r["_at"]).days)
        parts = [f"شکایت {kid} با شدت «{r[S.K_SEVERITY]}» در وضعیت «{r[S.K_STATUS]}»"]
        if m.get("mechanism"):
            parts.append(f"سازوکار {m['mechanism']}")
        if answered and rs.get("fault_verdict"):
            parts.append(f"نتیجه بررسی: قصور متوجه «{rs['fault_verdict']}»")
            if rs.get("investigation_state"):
                parts.append(f"پرونده {rs['investigation_state']}")
        elif not answered:
            parts.append("نتیجه بررسی در این تاریخ هنوز قابل‌دانستن نیست")
        parts.append(f"{age} روز از ثبت آن گذشته است")
        ev = ctx.emit(
            customer_id, "cmpitem", "، ".join(parts) + ".",
            str(r[S.K_STATUS]), unit=None, kind="event",
            window=(r["_at"].date(), ctx.as_of),
            source_rows=rows_ref(S.S_COMPLAINTS, [kid]),
            formula="شکایات + استخراج سازوکار و نتیجه بررسی [rule #4 روی هر دو مهر]",
            mechanism=m.get("mechanism"), severity=r[S.K_SEVERITY],
            resolution_known=bool(answered),
            fault_verdict=rs.get("fault_verdict") if answered else None,
        )
        ids.append(ev.id)
        claims.append(ev.claim_fa)
        items.append({"complaint_id": kid, "severity": r[S.K_SEVERITY],
                      "status": r[S.K_STATUS], "mechanism": m.get("mechanism"),
                      "resolution_known": bool(answered),
                      "fault_verdict": rs.get("fault_verdict") if answered else None,
                      "age_days": age})
    extra_ids, extra_claims = _reuse(ctx, customer_id,
                                     "complaints", "complaint-open", "recurrence")
    return _result(
        "get_complaints", customer_id, ids + extra_ids, claims + extra_claims,
        {"complaints": items},
        note=("نتیجه بررسی فقط از Resolution_Available_At قابل‌دانستن است؛ پرونده‌ای "
              "که پاسخش هنوز منتشر نشده، برای تصمیم امروز باز است."),
    )


def _by_complaint(ctx: MetricContext, table: str) -> dict[str, dict]:
    df = ctx.tables.get(table)
    if df is None or not len(df):
        return {}
    return {r["complaint_id"]: r.to_dict() for _, r in df.iterrows()}


@tool(
    "get_crm_promises",
    "تعاملات CRM این مشتری و اقدام بعدی‌ای که در هرکدام ثبت شده است.",
    limit="حداکثر تعداد تعامل (پیش‌فرض ۶، جدیدترین اول)",
)
def get_crm_promises(ctx: MetricContext, customer_id: str, limit: int = 6) -> ToolResult:
    # rule #5: the latest visible version of each interaction, never all versions
    crm = visible(ctx.ds.crm_latest, ctx.as_of)
    crm = crm.loc[crm[S.CUSTOMER_ID] == customer_id].assign(
        _at=pd.to_datetime(crm.loc[crm[S.CUSTOMER_ID] == customer_id, S.X_EVENT_TIME],
                           errors="coerce")
    )
    crm = crm.loc[crm["_at"] <= _asof(ctx)]
    if crm.empty:
        return _result("get_crm_promises", customer_id, [], [], {},
                       empty=f"تا {ctx.as_of.isoformat()} هیچ تعامل CRM با این مشتری "
                             "ثبت نشده است.")
    crm = crm.sort_values("_at", ascending=False).head(limit)
    ids, claims, items = [], [], []
    for _, r in crm.iterrows():
        age = int((_asof(ctx) - r["_at"]).days)
        action = r[S.X_NEXT_ACTION] if isinstance(r[S.X_NEXT_ACTION], str) else "—"
        tail = ("اقدام بعدی ثبت نشده" if action in ("—", "بدون اقدام")
                else f"اقدام بعدی «{action}»")
        ev = ctx.emit(
            customer_id, "crmitem",
            f"تعامل {r[S.X_ID]} از نوع «{r[S.X_TYPE]}» {age} روز پیش ثبت شده و {tail} است.",
            action, unit=None, kind="event",
            window=(r["_at"].date(), ctx.as_of),
            source_rows=rows_ref(S.S_CRM, [r[S.X_ID]]),
            formula="آخرین Record_Version هر Interaction_ID [rule #5]",
            interaction_type=r[S.X_TYPE], next_action=action, age_days=age,
            record_status=r.get(S.X_RECORD_STATUS),
        )
        ids.append(ev.id)
        claims.append(ev.claim_fa)
        items.append({"interaction_id": r[S.X_ID], "type": r[S.X_TYPE],
                      "next_action": action, "age_days": age})
    extra_ids, extra_claims = _reuse(ctx, customer_id, "crm", "loop-nextaction")
    return _result("get_crm_promises", customer_id, ids + extra_ids,
                   claims + extra_claims, {"interactions": items},
                   note="فقط آخرین نسخه هر تعامل خوانده شده است (قاعده ۵).")


@tool(
    "get_payment_state",
    "وضعیت مالی مشتری: مانده باز، اشغال سقف اعتبار، DSO، چک برگشتی و اثر خالص مالی.",
)
def get_payment_state(ctx: MetricContext, customer_id: str) -> ToolResult:
    ids, claims = _reuse(ctx, customer_id, "exposure", "credit-room", "dso",
                         "bounce", "finance-net")
    if not ids:
        return _result("get_payment_state", customer_id, [], [], {},
                       empty="هیچ فاکتور یا رویداد وصولی برای این مشتری دیده نمی‌شود.")
    pay = ctx.table("payment")
    row = pay.loc[customer_id] if customer_id in pay.index else None
    payload = {} if row is None else {
        k: (None if pd.isna(row[k]) else row[k])
        for k in ("open_exposure", "credit_limit", "exposure_ratio", "dso",
                  "dso_slippage", "bounces", "credit_room_state",
                  "net_finance_effect")
        if k in row
    }
    return _result("get_payment_state", customer_id, ids, claims, payload,
                   note=("سقف اعتبار در این دفتر دو مقیاسی است (§5.4)؛ نسبت اشغال "
                         "معنا دارد، تفریق ریالی آن با مانده لزوماً نه."))


@tool(
    "get_lab_band_position",
    "جایگاه آزمون‌های آزمایشگاهی لات‌های ارسالی به این مشتری نسبت به همان خانواده کالا.",
)
def get_lab_band_position(ctx: MetricContext, customer_id: str) -> ToolResult:
    """Where the lots we actually shipped this customer sit in the book's band.

    Descriptive only, and deliberately so. Measured across the whole sheet the
    four lab metrics carry **no** relation to whether a line drew a complaint
    (Cohen's d 0.03–0.07 on tensile, elongation and oil pickup), so this tool
    describes what was shipped and never explains a complaint by it.

    The one exception is ``Lab_Result = رد``, which is not a band position but a
    fact: all 12 such lines in the book were measured before the customer bought
    them, shipped anyway, and every one drew a complaint that was upheld. When a
    customer has one, it leads.
    """
    lines = ctx.spine.lines
    mine = lines.loc[lines[S.CUSTOMER_ID] == customer_id, [S.SALES_LINE_ID, S.P_FAMILY]]
    if mine.empty:
        return _result("get_lab_band_position", customer_id, [], [], {},
                       empty="ردیف فروش قابل‌مشاهده‌ای برای این مشتری نیست.")
    lab = visible(ctx.ds.frames[S.S_LOT_QUALITY], ctx.as_of)
    lab = lab.loc[pd.to_datetime(lab[S.Q_MEASURED_AT], errors="coerce") <= _asof(ctx)]
    fam = lines[[S.SALES_LINE_ID, S.P_FAMILY]].drop_duplicates(S.SALES_LINE_ID)
    lab = lab.merge(fam, on=S.SALES_LINE_ID, how="inner")
    ours = lab.loc[lab[S.SALES_LINE_ID].isin(set(mine[S.SALES_LINE_ID]))]
    if ours.empty:
        return _result("get_lab_band_position", customer_id, [], [], {},
                       empty="برای لات‌های این مشتری آزمون آزمایشگاهی قابل‌مشاهده‌ای "
                             "ثبت نشده است.")

    ids, claims = [], []
    rejects = ours.loc[ours[S.Q_RESULT] == "رد"]
    if len(rejects):
        ev = ctx.emit(
            customer_id, "labreject",
            f"{num(len(rejects))} لات ارسالی به این مشتری در آزمون آزمایشگاهی «رد» "
            f"شده بود و با وجود آن ارسال شده است.",
            float(len(rejects)), unit="لات", kind="event",
            window=(ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of),
            source_rows=rows_ref(S.S_LOT_QUALITY, list(rejects[S.Q_ID]),
                                 key=S.Q_ID),
            formula="Lab_Result = رد روی لات‌های فروخته‌شده به این مشتری",
            confidence=1.0,
            note=("در کل دفتر هر ۱۲ مورد از این نوع، پیش از خرید مشتری اندازه‌گیری "
                  "شده و همه به شکایت پذیرفته‌شده منجر شده‌اند."),
        )
        ids.append(ev.id)
        claims.append(ev.claim_fa)

    metrics = [(S.Q_TENSILE, "استحکام"), (S.Q_ELONGATION, "ازدیاد طول"),
               (S.Q_EVENNESS, "یکنواختی CV"), (S.Q_OIL, "روغن‌گیری")]
    bands = {}
    for family, block in ours.groupby(S.P_FAMILY):
        peers = lab.loc[lab[S.P_FAMILY] == family]
        if len(peers) < ctx.settings.min_percentile_observations:
            continue
        for col, label_fa in metrics:
            mean = float(block[col].mean())
            position = float((peers[col] < mean).mean() * 100.0)
            bands[f"{family}|{col}"] = {"mean": mean, "percentile": position,
                                        "n_lots": int(len(block))}
            ev = ctx.emit(
                customer_id, "labband",
                f"میانگین {label_fa} لات‌های ارسالی این مشتری در {family} در صدک "
                f"{num(position, 0)} همان خانواده قرار دارد ({num(len(block))} لات).",
                position, unit="صدک", kind="comparison",
                window=(ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of),
                source_rows=rows_ref(S.S_LOT_QUALITY, list(block[S.Q_ID]), key=S.Q_ID),
                formula=f"percentile of mean({col}) within {family} lab records",
                family=family, metric=col,
            )
            ids.append(ev.id)
            claims.append(ev.claim_fa)
    return _result(
        "get_lab_band_position", customer_id, ids, claims,
        {"n_lab_records": int(len(ours)), "rejects": int(len(rejects)),
         "bands": bands},
        note=("این اعداد توصیف‌اند، نه تبیین: در کل دفتر بین مقادیر آزمون و بروز "
              "شکایت رابطه‌ای دیده نمی‌شود، پس نباید شکایتی را با آنها توضیح داد."),
    )


@tool(
    "get_market_context",
    "گزارش بازار هفتگی برای خانواده کالایی که این مشتری می‌خرد.",
    weeks="چند هفته اخیر (پیش‌فرض ۱۲)",
)
def get_market_context(ctx: MetricContext, customer_id: str, weeks: int = 12) -> ToolResult:
    family = _dominant_family(ctx, customer_id)
    if family is None:
        return _result("get_market_context", customer_id, [], [], {},
                       empty="خانواده کالای غالب این مشتری مشخص نیست.")
    mkt = visible(ctx.ds.frames[S.S_MARKET], ctx.as_of)
    stamps = pd.to_datetime(mkt[S.M_REPORT_DATE], errors="coerce")
    window_start = _asof(ctx) - pd.Timedelta(weeks=weeks)
    rows = mkt.loc[(mkt[S.M_PRODUCT_MARKET] == family)
                   & (stamps <= _asof(ctx)) & (stamps > window_start)]
    if rows.empty:
        return _result(
            "get_market_context", customer_id, [], [], {"family": family},
            empty=f"در {weeks} هفته منتهی به {ctx.as_of.isoformat()} گزارش بازاری "
                  f"برای {family} ثبت نشده است.")
    trend = rows[S.M_MARKET_TREND].mode()
    demand = rows[S.M_DEMAND_CHANGE].value_counts()
    price = pd.to_numeric(rows[S.M_PRICE_INDEX], errors="coerce").mean()
    ev = ctx.emit(
        customer_id, "market",
        f"در {num(len(rows))} گزارش بازار {family} در {num(weeks)} هفته اخیر، وضعیت "
        f"غالب «{trend.iloc[0] if len(trend) else '—'}» و میانگین شاخص قیمت "
        f"{num(price)} بوده است.",
        float(price) if pd.notna(price) else 0.0, unit="شاخص", kind="comparison",
        window=(window_start.date(), ctx.as_of),
        source_rows=rows_ref(S.S_MARKET, list(rows[S.M_WEEK_ID]), key=S.M_WEEK_ID),
        formula=f"mode(Market_Trend) و mean(Price_Index) روی {family}",
        confidence=0.5, assumption=False,
        family=family, demand_mix=demand.to_dict(),
    )
    return _result(
        "get_market_context", customer_id, [ev.id], [ev.claim_fa],
        {"family": family, "n_reports": int(len(rows)),
         "trend": (trend.iloc[0] if len(trend) else None),
         "price_index_mean": None if pd.isna(price) else float(price),
         "demand": demand.to_dict()},
        note=("این شیت گزارش هفتگی خانواده کالاست، نه سیگنال این مشتری: در کل دفتر "
              "۱۳۰ ردیف برای ۷ خانواده وجود دارد و فقط ۵۹ ردیف اصلاً شناسه مشتری "
              "دارد. آن را به این مشتری نسبت نده."),
    )


@tool(
    "get_peer_comparison",
    "مقایسه این مشتری با همتایان هم‌بخش: صدک حاشیه سود، جایگاه قیمت و فاصله ظرفیت.",
)
def get_peer_comparison(ctx: MetricContext, customer_id: str) -> ToolResult:
    ids, claims = _reuse(ctx, customer_id, "margin-percentile", "price-position",
                         "headroom", "rfm", "crosssell")
    segment = ctx.cohorts.customer_segment.get(customer_id)
    family = _dominant_family(ctx, customer_id)
    peers = [
        c for c in ctx.population
        if c != customer_id and ctx.cohorts.customer_segment.get(c) == segment
        and (family is None or _dominant_family(ctx, c) == family)
    ]
    if peers:
        # The peer set is itself a claim: "compared with whom" is the first thing
        # a customer asks when shown a percentile. When the family is unknown the
        # comparison is segment-only, and it has to say that rather than print a
        # cohort description with a hole in it.
        basis = (f"با همان خانواده کالای غالب ({family})" if family
                 else "بدون تفکیک خانواده کالا")
        ev = ctx.emit(
            customer_id, "peerset",
            f"مقایسه در برابر {num(len(peers))} مشتری هم‌بخش (بخش {segment}) "
            f"{basis} انجام شده است.",
            float(len(peers)), unit="مشتری", kind="comparison",
            window=(ctx.spine.lines[S.F_DATE].min().date(), ctx.as_of),
            source_rows=rows_ref(S.S_SALES, peers, key=S.CUSTOMER_ID),
            formula=("same Customer_Segment"
                     + (" and same dominant family" if family else "")),
            segment=segment, family=family,
        )
        ids = [ev.id] + ids
        claims = [ev.claim_fa] + claims
    if not ids:
        return _result("get_peer_comparison", customer_id, [], [], {},
                       empty="کوهورت همتای قابل‌اتکایی برای این مشتری ساخته نشد.")
    return _result("get_peer_comparison", customer_id, ids, claims,
                   {"segment": segment, "family": family, "n_peers": len(peers)},
                   note=("همه مقایسه‌های قیمتی تورم‌زدوده‌اند؛ قیمت مطلق در این دفتر "
                         "معنا ندارد (§1.7)."))


@tool(
    "get_offer_history",
    "آفرهای این مشتری: تاریخ، نوع، تخفیف، مهلت اعتبار و نتیجه‌ای که در این تاریخ قابل‌دانستن است.",
    limit="حداکثر تعداد آفر (پیش‌فرض ۸، جدیدترین اول)",
)
def get_offer_history(ctx: MetricContext, customer_id: str, limit: int = 8) -> ToolResult:
    rows = _customer_rows(ctx, S.S_OFFERS, S.O_DATE, customer_id)
    if rows.empty:
        return _result("get_offer_history", customer_id, [], [], {},
                       empty=f"تا {ctx.as_of.isoformat()} هیچ آفری برای این مشتری ثبت "
                             "نشده است.")
    rows = rows.sort_values("_at", ascending=False).head(limit)
    ids, claims, items = [], [], []
    for _, r in rows.iterrows():
        known_at = pd.to_datetime(r[S.O_DECISION_AVAILABLE_AT], errors="coerce")
        known = pd.notna(known_at) and known_at <= _asof(ctx)
        age = int((_asof(ctx) - r["_at"]).days)
        validity = pd.to_numeric(r[S.O_VALIDITY_DAYS], errors="coerce")
        outcome = (f"نتیجه آن «{r[S.O_RESULT]}» است" if known
                   else "نتیجه آن در این تاریخ هنوز قابل‌دانستن نیست")
        overdue = (pd.notna(validity) and age > validity and not known)
        ev = ctx.emit(
            customer_id, "offeritem",
            f"آفر {r[S.O_ID]} از نوع «{r[S.O_TYPE]}» با تخفیف "
            f"{pct(pd.to_numeric(r[S.O_DISCOUNT_PCT], errors='coerce'))} درصد، "
            f"{age} روز پیش ثبت شده (مهلت {num(validity)} روز) و {outcome}"
            + ("؛ از مهلت خودش گذشته است." if overdue else "."),
            str(r[S.O_RESULT]) if known else "بی‌پاسخ", unit=None, kind="event",
            window=(r["_at"].date(), ctx.as_of),
            source_rows=rows_ref(S.S_OFFERS, [r[S.O_ID]]),
            formula="نتیجه فقط از Decision_Available_At قابل‌دانستن است [rule #4]",
            offer_type=r[S.O_TYPE], age_days=age, decision_known=bool(known),
            past_validity=bool(overdue),
        )
        ids.append(ev.id)
        claims.append(ev.claim_fa)
        items.append({"offer_id": r[S.O_ID], "type": r[S.O_TYPE], "age_days": age,
                      "decision_known": bool(known), "past_validity": bool(overdue),
                      "result": r[S.O_RESULT] if known else None})
    extra_ids, extra_claims = _reuse(ctx, customer_id, "offers", "loop-offer")
    return _result(
        "get_offer_history", customer_id, ids + extra_ids, claims + extra_claims,
        {"offers": items},
        note=("اثربخشی آفر ادعا نمی‌شود: در این شیت تخفیف، دلیل و نوع هیچ ارتباطی با "
              "نتیجه ندارند (§1.2). «مدت‌دار» امتیاز مالی است، نه کاهش قیمت، و "
              "درصد تخفیفش با «قیمتی» قابل مقایسه نیست (§5.3)."),
    )
