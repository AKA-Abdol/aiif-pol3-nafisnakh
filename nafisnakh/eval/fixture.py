"""The golden-sample fixture (PLAN §6).

Per Q6: *«یک نمونه طلایی هم برای تست آماده کنی»*. A small, fixed, composed sample
that exercises **every block end-to-end** — loader → metrics → detectors →
complaint block → quadrant → aggregator → validator — and, per §6, fires **all
28 detectors at least once**, without depending on which universe a real
customer happens to fall in.

It is a **test fixture, not a claim about reality.** Every row carries
``is_fixture: true``, every customer id is prefixed ``FIX-``, and nothing here
is ever mixed into output presented as analysis of real customers.

Each customer exists to prove one thing; :data:`FIXTURE_CUSTOMERS` records what,
so a failing snapshot says which capability broke rather than only that a number
moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import Settings, get_settings
from ..io import schema as S
from ..io.loader import Dataset
from ..io.normalize import normalize_fa, parse_date_any

FIXTURE_AS_OF = date(2021, 6, 30)
FIXTURE_FLAG = "is_fixture"
FIXTURE_PREFIX = "FIX-"

# the real universe-B text (PLAN §1.3) — the demo centrepiece, verbatim
CHURN_TEXT = (
    "نخ در بعضي جاها سيمي ميباشد و همچنين پرز شديد نيز در بعضي بسته ها وجود دارد."
    "اين مشکل تکراري ميباشد و قبلا هم وجود داشته و مشتري اعلام نموده که درصورت "
    "تکرار قطع همکاري ميکند.مشتري عکس ارسال نموده است"
)

SHARED_HEMBAFT = "9900000001"
SHARED_LOT = "LOT-FIX-9001"
LAB_REJECTED_LOT = "LOT-FIX-9002"

F03 = "Product_Family_03"
F04 = "Product_Family_04"
F05 = "Product_Family_05"

# customer_id → (segment, credit_limit, payment_terms, what this row proves)
FIXTURE_CUSTOMERS: dict[str, tuple[str, int, int, str]] = {
    "FIX-001": ("B", 5_000_000, 30, "protect · churn threat in prose · complaint recurrence · unresolved aging"),
    "FIX-002": ("A", 4_000_000, 60, "fix · negative risk-adjusted margin at real volume"),
    "FIX-003": ("B", 800_000, 0, "reduce · margin below peer cohort · two unsubstantiated complaints (#23)"),
    "FIX-004": ("B", 3_000_000, 30, "grow · wallet headroom · cross-sell gap"),
    "FIX-005": ("B", 6_000_000, 90, "blast radius · the complainant on the shared همبافت · open investigation awaiting a sample"),
    "FIX-006": ("B", 2_000_000, 30, "blast radius · exposed, has not complained"),
    "FIX-007": ("B", 1_500_000, 0, "blast radius · exposed, has not complained"),
    "FIX-008": ("B", 2_500_000, 45, "same-day repeat buyer · median gap 0"),
    "FIX-009": ("C", 900_000, 0, "first order, never repeated"),
    "FIX-010": ("A", 300_000, 30, "bounced cheque · credit exposure · late-interest drag"),
    "FIX-011": ("A", 9_000_000, 30, "volume surge"),
    "FIX-012": ("B", 3_000_000, 30, "mix downgrade · SKU narrowing"),
    "FIX-013": ("A", 3_000_000, 30, "price erosion (deflated, not absolute)"),
    "FIX-014": ("A", 3_000_000, 30, "discount without return"),
    "FIX-015": ("B", 3_000_000, 30, "DSO slippage against own baseline"),
    "FIX-016": ("A", 3_000_000, 30, "return-rate spike · stalled development request"),
    # ---- open loops (#24–#27): things *we* left unfinished
    "FIX-017": ("B", 3_000_000, 30, "approved sample never turned into an offer (#24)"),
    "FIX-018": ("B", 3_000_000, 30, "technically rejected, never communicated (#25)"),
    "FIX-019": ("B", 3_000_000, 30, "a written next action left undone (#26)"),
    "FIX-020": ("B", 3_000_000, 30, "offers abandoned past their own validity (#27)"),
    # a lot the lab failed before the customer bought it, shipped anyway, no
    # complaint filed yet — the preemptive half of #28
    "FIX-021": ("B", 3_000_000, 30, "lab-rejected lot shipped, complaint not yet filed (#28)"),
}


@dataclass
class Fixture:
    dataset: Dataset
    customer_ids: list[str]
    as_of: date
    intents: dict[str, str]


# --------------------------------------------------------------------- helpers
def _d(offset_days: int) -> pd.Timestamp:
    """A date, expressed as days before ``as_of`` (positive = earlier)."""
    return pd.Timestamp(FIXTURE_AS_OF - timedelta(days=offset_days))


def _series(start_days_ago: int, n: int, step: int) -> list[pd.Timestamp]:
    return [_d(start_days_ago - i * step) for i in range(n)]


class SalesBuilder:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._n: dict[str, int] = {}

    def add(self, cid, dates, *, qty, price, cost, family=F03, product=None,
            lot=None, hembaft=None, return_qty=0.0):
        product = product or f"P-{family[-2:]}"
        for d in dates:
            i = self._n.get(cid, 0)
            self._n[cid] = i + 1
            line_id = f"SL-{cid}-{i:03d}"
            self.rows.append({
                S.F_LINE_NO: i + 1,
                S.F_DATE: d,
                S.F_PAY_TYPE: "short_term",
                S.CUSTOMER_ID: cid,
                S.PRODUCT_ID: product,
                S.P_QUALITY_CLASS: "Quality_Class_02",
                S.F_QTY: float(qty),
                S.F_UNIT_PRICE: float(price),
                S.F_AMOUNT: float(qty) * float(price),
                S.INVOICE_NO: f"INV-{cid}-{i:03d}",
                S.F_MONTH: d.month,
                S.F_YEAR: d.year,
                S.P_LUSTER: "Luster_Class_01",
                S.P_FAMILY: family,
                S.P_COLOR: "Color_Class_01",
                S.P_SUBGROUP: "Denier_Subgroup_02",
                S.SALES_LINE_ID: line_id,
                S.LOT_ID: lot or f"LOT-{cid}-{i:03d}",
                S.HEMBAFT_ID: hembaft,
                S.HEMBAFT_LOT_KEY: f"{hembaft}|{lot}" if hembaft and lot else None,
                S.AVAILABLE_AT: d,
                S.SOURCE_SYSTEM: "ERP_SALES",
                "_cost": float(cost),
                "_return_qty": float(return_qty),
                FIXTURE_FLAG: True,
            })

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def _build_sales() -> pd.DataFrame:
    b = SalesBuilder()

    # A healthy segment-B cohort on Family_03 — the peer group that makes
    # `margin_below_peer_cohort` and `cross_sell_peer_gap` meaningful. Two of
    # them also buy Family_05, which is the cross-sell gap for the rest.
    # FIX-004 and FIX-012 are deliberately *not* in this bulk loop: FIX-004 must
    # stay far below its peers to have headroom, and FIX-012's basket has to
    # narrow, which a broad steady baseline would mask.
    for cid in ("FIX-001", "FIX-003", "FIX-005", "FIX-006",
                "FIX-007", "FIX-008", "FIX-015"):
        b.add(cid, _series(300, 14, 20), qty=800, price=250, cost=205)
    for cid in ("FIX-005", "FIX-015"):
        b.add(cid, _series(250, 4, 30), qty=200, price=350, cost=280, family=F05)

    # FIX-001 protect: keeps buying to the end, then goes quiet past its rhythm
    b.add("FIX-001", _series(120, 3, 20), qty=800, price=255, cost=205)

    # FIX-002 fix: heavy volume, cost above price → negative risk-adjusted margin
    b.add("FIX-002", _series(300, 26, 11), qty=1500, price=180, cost=232)

    # FIX-003 reduce: buys with the cohort but sells below cost — small and
    # unprofitable, which is the "don't spend sales energy here" case
    b.add("FIX-003", _series(120, 3, 35), qty=60, price=185, cost=196)

    # FIX-004 grow: profitable, buys far below its peers, never touches Family_05
    b.add("FIX-004", _series(60, 2, 25), qty=100, price=270, cost=190)

    # FIX-005..007 share one همبافت through one lot (integration rule #7)
    for cid in ("FIX-005", "FIX-006", "FIX-007"):
        b.add(cid, _series(150, 5, 20), qty=400, price=245, cost=200,
              lot=SHARED_LOT, hembaft=SHARED_HEMBAFT)

    # FIX-008 same-day repeat buyer: four invoices on one day → median gap 0
    b.add("FIX-008", [_d(200)] * 4, qty=300, price=250, cost=200)
    b.add("FIX-008", _series(199, 6, 1), qty=300, price=250, cost=200)

    # FIX-009 one invoice, ever
    b.add("FIX-009", [_d(280)], qty=200, price=240, cost=200)

    # FIX-010 payment trouble: bounced cheque, exposure past a small limit
    b.add("FIX-010", _series(300, 12, 20), qty=800, price=250, cost=205)

    # FIX-011 volume surge: quiet baseline, heavy recent quarter
    b.add("FIX-011", _series(270, 6, 25), qty=100, price=250, cost=200)
    b.add("FIX-011", _series(80, 9, 9), qty=1200, price=250, cost=200)

    # FIX-012 mix downgrade + SKU narrowing: five SKUs inside two baseline months,
    # then a single cheaper SKU in the recent quarter
    for i in range(5):
        b.add("FIX-012", _series(200 - i * 3, 2, 20), qty=200, price=350, cost=280,
              family=F05, product=f"P-05-{i}")
    b.add("FIX-012", _series(70, 4, 20), qty=200, price=175, cost=150, family=F04,
          product="P-04-0")

    # FIX-013 price erosion: priced above the market, then well below it
    b.add("FIX-013", _series(300, 10, 22), qty=600, price=330, cost=200)
    b.add("FIX-013", _series(75, 4, 22), qty=600, price=170, cost=150)

    # FIX-014 discount without return: steady baseline, weaker recent quarter
    b.add("FIX-014", _series(300, 12, 20), qty=700, price=250, cost=205)
    b.add("FIX-014", _series(60, 2, 25), qty=250, price=250, cost=205)

    # FIX-015 DSO slippage: same buying, much slower paying lately (see collections)
    b.add("FIX-015", _series(70, 4, 20), qty=800, price=250, cost=205)

    # FIX-016 returns + a stalled R&D request
    b.add("FIX-016", _series(300, 10, 25), qty=500, price=250, cost=200)
    b.add("FIX-016", _series(60, 3, 20), qty=500, price=250, cost=200, return_qty=120)

    # FIX-017..020 — ordinary, healthy buyers. The point of these four is that
    # nothing is wrong with the *customer*: the open loop is entirely ours, and a
    # detector that only fires on accounts already in trouble would miss it.
    # They buy Family_04, which keeps them out of the (B, Family_03) peer group
    # that `cross_sell_peer_gap` is calibrated on — four extra members there
    # would push the Family_05 adoption rate under the threshold and silence a
    # detector that has nothing to do with open loops.
    for cid in ("FIX-017", "FIX-018", "FIX-019", "FIX-020", "FIX-021"):
        b.add(cid, _series(300, 12, 22), qty=600, price=255, cost=205, family=F04)

    # FIX-021's most recent line carries the lot the lab failed (see
    # `_build_lot_quality`). It is a normal line in every other respect — the
    # escape is ours, not a property of the customer.
    b.add("FIX-021", [_d(40)], qty=900, price=255, cost=205, family=F04,
          lot=LAB_REJECTED_LOT)

    return b.frame()


def _build_collections(sales: pd.DataFrame) -> pd.DataFrame:
    cid = sales[S.CUSTOMER_ID]
    days_late = pd.Series(10.0, index=sales.index)
    paid_share = pd.Series(1.0, index=sales.index)

    # FIX-010: pays late, partially, and bounces its first cheque
    late_payer = cid == "FIX-010"
    days_late[late_payer] = 80.0
    paid_share[late_payer] = 0.30

    # FIX-015: baseline paid quickly, recent invoices dragged out
    slipping = cid == "FIX-015"
    recent = sales[S.F_DATE] > pd.Timestamp(FIXTURE_AS_OF) - pd.DateOffset(months=6)
    days_late[slipping & ~recent] = 5.0
    days_late[slipping & recent] = 95.0

    bounced = np.where(late_payer & (sales[S.F_LINE_NO] == 1), S.BOUNCED_YES, S.BOUNCED_NO)
    event = sales[S.F_DATE] + pd.to_timedelta(30 + days_late, unit="D")
    return pd.DataFrame({
        S.V_ID: "COL-" + sales[S.SALES_LINE_ID],
        S.CUSTOMER_ID: cid,
        S.INVOICE_NO: sales[S.INVOICE_NO],
        S.V_INVOICE_DATE: sales[S.F_DATE],
        S.V_DUE_DATE: sales[S.F_DATE] + pd.Timedelta(days=30),
        S.V_EVENT_DATE: event,
        S.AVAILABLE_AT: event,
        S.V_AMOUNT: sales[S.F_AMOUNT] * paid_share,
        S.V_DAYS_LATE: days_late,
        S.V_BOUNCED: bounced,
        S.SOURCE_SYSTEM: "ERP_COLLECTIONS",
        FIXTURE_FLAG: True,
        "_universe": "fixture",
    })


def _build_complaints() -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = [
        # id, customer, title, text, severity, created_days_ago, resolved_days_ago, hembaft
        ("CMPFIX-001", "FIX-001", "فیلامنت و پرز", CHURN_TEXT, "زیاد", 200, None, None),
        ("CMPFIX-002", "FIX-001", "فیلامنت و پرز",
         "دوباره همان مشکل پرز و فیلامنت پارگی در محموله جدید تکرار شده است.",
         "زیاد", 80, 60, None),
        ("CMPFIX-003", "FIX-005", "بد پيچي",
         "بد پيچي و ريزش نخ در اين همبافت مشاهده شد.", "متوسط", 60, None, SHARED_HEMBAFT),
        ("CMPFIX-004", "FIX-016", "آسیب دیدگی در حمل و نقل",
         "آسيب ديدگي بار هنگام حمل و نقل.", "کم", 40, None, None),
        # #23 — two investigations that came back "not our fault", so the
        # unsubstantiated load has something to fire on.
        ("CMPFIX-005", "FIX-003", "نوسان دنیر",
         "نمره نخ خارج از تلرانس اعلام شد.", "متوسط", 150, 130, None),
        ("CMPFIX-006", "FIX-003", "شید رنگ",
         "اختلاف شید بین بسته ها گزارش شد.", "کم", 100, 85, None),
        # the open-investigation gate — a file still waiting on a sample
        ("CMPFIX-007", "FIX-005", "پیچش بسته/ تنشن پیچش",
         "تنشن پیچش نامناسب در بسته ها مشاهده شد.", "متوسط", 120, 110, None),
    ]
    # Resolution prose per complaint, so the resolution block has real input.
    # The first two use the Universe-A "claim not substantiated" frame, the third
    # the "awaiting a sample" frame — both matched by the templates, no model needed.
    RESOLUTIONS = {
        "CMPFIX-005": ("ابتدا موضوع از داخل سازمان بررسی گردید و نظرات واحدهای مرتبط "
                       "دریافت گردید. نتایج ثبت‌شده در محدوده الزام محصول قرار داشت و "
                       "مغایرتی که ادعای مشتری را تأیید کند مشاهده نشد."),
        "CMPFIX-006": ("نتایج ثبت‌شده در محدوده الزام محصول قرار داشت و مغایرتی که "
                       "ادعای مشتری را تأیید کند مشاهده نشد."),
        "CMPFIX-007": ("برای نتیجه‌گیری قطعی مقرر گردید دوک نمونه و تصاویر مربوطه "
                       "ارسال شود. تا زمان دریافت نمونه و انجام آزمون تکمیلی، موضوع "
                       "نیازمند بررسی تکمیلی است."),
        "CMPFIX-002": "در بررسی مستندات تولید مشخص گردید عیب تولیدی و مقرر شد اصلاح شود.",
    }
    complaints, links = [], []
    for kid, cid, title, text, severity, created_ago, resolved_ago, hembaft in specs:
        created = _d(created_ago)
        resolved = _d(resolved_ago) if resolved_ago is not None else pd.NaT
        complaints.append({
            S.K_ID: kid, S.CUSTOMER_ID: cid, S.PRODUCT_ID: "P-03",
            S.K_FAMILY: F03, S.K_TITLE: title, S.K_TEXT: text,
            S.K_HEMBAFT_REF: hembaft, S.K_SEVERITY: severity,
            S.K_CREATED_AT: created, S.AVAILABLE_AT: created,
            S.K_STATUS: "نیازمند بررسی" if pd.isna(resolved) else "بسته‌شده",
            S.K_RESOLVED_AT: resolved,
            S.K_RESOLUTION_AVAILABLE_AT: resolved,
            S.K_RESOLUTION_TEXT: (
                None if pd.isna(resolved)
                else RESOLUTIONS.get(kid, "بررسی و رفع شد.")
            ),
            S.SOURCE_SYSTEM: "QMS", FIXTURE_FLAG: True,
        })
        if hembaft:
            links.append({
                S.K_ID: kid, S.SALES_LINE_ID: "SL-FIX-005-014",
                S.INVOICE_NO: "INV-FIX-005-014", S.CUSTOMER_ID: cid,
                S.PRODUCT_ID: "P-03", S.HEMBAFT_ID: hembaft, S.LOT_ID: SHARED_LOT,
                S.HEMBAFT_LOT_KEY: f"{hembaft}|{SHARED_LOT}",
                S.KL_PURCHASE_DATE: created, S.KL_QTY: 400.0, S.KL_RETURN_QTY: 0.0,
                S.KL_RESULT: "باز", S.KL_AVAILABLE_AT: created, FIXTURE_FLAG: True,
            })
    link_cols = [S.K_ID, S.SALES_LINE_ID, S.INVOICE_NO, S.CUSTOMER_ID, S.PRODUCT_ID,
                 S.HEMBAFT_ID, S.LOT_ID, S.HEMBAFT_LOT_KEY, S.KL_PURCHASE_DATE,
                 S.KL_QTY, S.KL_RETURN_QTY, S.KL_RESULT, S.KL_AVAILABLE_AT, FIXTURE_FLAG]
    return (
        pd.DataFrame(complaints),
        pd.DataFrame(links, columns=link_cols) if links else pd.DataFrame(columns=link_cols),
    )


def _build_offers() -> pd.DataFrame:
    rows = []
    for i in range(5):
        d = _d(150 - i * 20)
        rows.append({
            S.O_ID: f"OFR-FIX-{i:03d}", S.CUSTOMER_ID: "FIX-014", S.O_DATE: d,
            S.AVAILABLE_AT: d, S.PRODUCT_ID: "P-03", S.O_FAMILY: F03,
            S.O_BASE_PRICE: 250.0, S.O_OFFERED_PRICE: 235.0,
            S.O_DISCOUNT_PCT: 0.06, S.O_TYPE: "قیمتی", S.O_VALIDITY_DAYS: 30,
            S.O_REASON: "افزایش حجم سفارش", S.O_RESULT: "قبول",
            S.O_DECISION_AT: d, S.O_DECISION_AVAILABLE_AT: d,
            S.SOURCE_SYSTEM: "CRM", FIXTURE_FLAG: True,
        })
    # #27 — three offers to FIX-020 with no knowable decision, all long past the
    # 30-day validity they set themselves. One of them already carries a
    # `Result` in the sheet, but its `Decision_Available_At` is in the future:
    # under rule #4 the sales manager could not have seen it, so it is still open.
    for i, (age, result) in enumerate(((200, None), (170, None), (140, "قبول"))):
        d = _d(age)
        rows.append({
            S.O_ID: f"OFR-FIX-1{i:02d}", S.CUSTOMER_ID: "FIX-020", S.O_DATE: d,
            S.AVAILABLE_AT: d, S.PRODUCT_ID: "P-04", S.O_FAMILY: F04,
            S.O_BASE_PRICE: 260.0, S.O_OFFERED_PRICE: 248.0,
            S.O_DISCOUNT_PCT: 0.046, S.O_TYPE: "قیمتی", S.O_VALIDITY_DAYS: 30,
            S.O_REASON: "افزایش حجم سفارش", S.O_RESULT: result,
            S.O_DECISION_AT: pd.NaT if result is None else _d(-30),
            S.O_DECISION_AVAILABLE_AT: pd.NaT if result is None else _d(-30),
            S.SOURCE_SYSTEM: "CRM", FIXTURE_FLAG: True,
        })
    return pd.DataFrame(rows).assign(_universe="fixture")


def _build_dev_requests() -> pd.DataFrame:
    def row(rid, cid, created, decided, status, outcome=None):
        return {
            S.D_ID: rid, S.CUSTOMER_ID: cid, S.PRODUCT_ID: "P-03",
            S.D_CREATED_AT: created, S.AVAILABLE_AT: created, S.D_TYPE: "کاهش پرز",
            S.D_REQUIREMENT: "کاهش پرز در نخ ارسالی", S.D_DECISION_AT: decided,
            S.D_STATUS: status, S.D_OUTCOME: outcome,
            S.D_OWNER_UNIT: "تحقیق‌وتوسعه", S.SOURCE_SYSTEM: "PLM_REQUESTS",
            FIXTURE_FLAG: True,
        }

    rows = [
        row("REQ-FIX-001", "FIX-016", _d(250), pd.NaT, "درحال بررسی"),
        # #24 — R&D said yes 200 days ago and FIX-017 has never been sent an offer.
        # The outcome text deliberately contradicts the status: on the real sheet
        # `Outcome_Text` is independent of `Status` (χ², p≈0.94), so a detector
        # that read the prose instead of the state would get this one backwards.
        row("REQ-FIX-002", "FIX-017", _d(260), _d(200), S.D_STATUS_APPROVED,
            "درخواست با محدودیت فنی فعلی سازگار نبود."),
        # #25 — rejected 180 days ago; the only CRM contact with FIX-018 predates it
        row("REQ-FIX-003", "FIX-018", _d(240), _d(180), S.D_STATUS_REJECTED,
            "نمونه برای آزمون مشتری آماده شد."),
    ]
    return pd.DataFrame(rows).assign(_universe="fixture")


def _build_crm() -> pd.DataFrame:
    """Interactions that exist to prove the next-action loop, and to prove that
    the *latest* interaction is the only one that counts."""
    def row(xid, cid, at, itype, next_action, version=1):
        return {
            S.X_ID: xid, S.X_VERSION: version, S.CUSTOMER_ID: cid,
            S.PRODUCT_ID: "P-03", S.X_EVENT_TIME: at, S.AVAILABLE_AT: at,
            S.X_UPDATED_AT: at, S.X_TYPE: itype,
            S.X_SUMMARY: "جمع‌بندی تماس | فوریت: متوسط | کد پیگیری: TRK-001",
            S.X_NEXT_ACTION: next_action, S.X_RECORD_STATUS: "ثبت اولیه",
            S.SOURCE_SYSTEM: "CRM", S.SALES_REP_ID: "REP-FIX-1",
            FIXTURE_FLAG: True,
        }

    rows = [
        # FIX-018: contact is older than the rejection, so nobody has told them
        row("INT-FIX-001", "FIX-018", _d(300), "برنامه خرید", "بدون اقدام"),
        # FIX-019: an old promise, then a newer conversation that supersedes it.
        # Only the later one may drive the signal — the earlier is history.
        row("INT-FIX-002", "FIX-019", _d(400), "کیفیت محصول", "بازدید فنی"),
        row("INT-FIX-003", "FIX-019", _d(150), "قیمت و تخفیف", "جلسه قیمت"),
        # FIX-020: a closed loop — the promise was kept, so #26 must NOT fire
        row("INT-FIX-004", "FIX-020", _d(250), "قیمت و تخفیف", "جلسه قیمت"),
    ]
    return pd.DataFrame(rows).assign(_universe="fixture")


def _build_lot_quality(sales: pd.DataFrame) -> pd.DataFrame:
    """Lab records for the fixture's lots.

    One of them matters: the line FIX-021 bought from ``LAB_REJECTED_LOT`` was
    measured ``رد`` **before** the purchase date and shipped anyway, with no
    complaint filed against it. That is detector #28's preemptive case, and the
    ordering is the whole point — a lot tested *after* shipment is a discovery,
    not an escape, and must not fire.

    The rest are ``قبول`` so the sheet has a distribution to place a customer
    against; without at least `min_percentile_observations` rows per family the
    lab band tool correctly declines to rank anyone.
    """
    rows = []
    for i, (_, line) in enumerate(sales.iterrows()):
        if i % 3 and line[S.LOT_ID] != LAB_REJECTED_LOT:
            continue
        rejected = line[S.LOT_ID] == LAB_REJECTED_LOT
        measured = line[S.F_DATE] - timedelta(days=6)
        rows.append({
            S.Q_ID: f"QLT-FIX-{len(rows):04d}",
            S.SALES_LINE_ID: line[S.SALES_LINE_ID],
            S.LOT_ID: line[S.LOT_ID],
            S.HEMBAFT_ID: line[S.HEMBAFT_ID],
            S.HEMBAFT_LOT_KEY: line[S.HEMBAFT_LOT_KEY],
            S.PRODUCT_ID: line[S.PRODUCT_ID],
            S.Q_PRODUCTION_DATE: measured,
            S.Q_MEASURED_AT: measured,
            S.AVAILABLE_AT: measured,
            S.Q_TENSILE: 2.90 if rejected else 3.60 + (i % 7) * 0.10,
            S.Q_ELONGATION: 19.0 if rejected else 24.0 + (i % 5) * 1.0,
            S.Q_EVENNESS: 2.35 if rejected else 1.40 + (i % 4) * 0.10,
            S.Q_OIL: 0.36 if rejected else 0.70 + (i % 3) * 0.05,
            S.Q_SAMPLE_COUNT: 8,
            S.Q_RESULT: S.Q_RESULT_REJECTED if rejected else "قبول",
            S.SOURCE_SYSTEM: "QMS_LAB",
            FIXTURE_FLAG: True,
        })
    return pd.DataFrame(rows).assign(_universe="fixture")


def build_fixture(settings: Settings | None = None) -> Fixture:
    """Compose the fixture dataset from scratch — it never touches DATASET.xlsx."""
    st = settings or get_settings()

    customers = pd.DataFrame([
        {
            S.CUSTOMER_ID: cid,
            S.C_LOCATION: "LOC-001",
            S.C_SEGMENT: segment,
            # FIX-004 carries a Jalali start date so the §1.5 defect stays covered
            S.C_START_DATE: ("1396/03/23" if cid == "FIX-004"
                             else str(_d(1200).date())),
            S.C_CREDIT_LIMIT: limit,
            S.C_PAYMENT_TERMS: terms,
            S.C_STATUS: "فعال",
            S.SOURCE_SYSTEM: "CRM_MASTER",
            S.SALES_REP_ID: "REP-001",
            FIXTURE_FLAG: True,
        }
        for cid, (segment, limit, terms, _why) in FIXTURE_CUSTOMERS.items()
    ])
    customers[S.C_START_DATE] = pd.to_datetime(
        customers[S.C_START_DATE].map(parse_date_any), errors="coerce"
    )
    customers["_universe"] = "fixture"

    sales = _build_sales()
    cost = pd.DataFrame({
        S.RC_ID: "CR-" + sales[S.SALES_LINE_ID],
        S.SALES_LINE_ID: sales[S.SALES_LINE_ID],
        S.INVOICE_NO: sales[S.INVOICE_NO],
        S.PRODUCT_ID: sales[S.PRODUCT_ID],
        S.RC_UNIT_COST: sales["_cost"],
        S.RC_RETURN_QTY: sales["_return_qty"],
        S.RC_RETURN_AMOUNT: sales["_return_qty"] * sales[S.F_UNIT_PRICE],
        S.RC_CLOSE_DATE: sales[S.F_DATE],
        S.AVAILABLE_AT: sales[S.F_DATE],
        S.SOURCE_SYSTEM: "ERP_COSTING",
        FIXTURE_FLAG: True,
    })
    collections = _build_collections(sales)
    sales = sales.drop(columns=["_cost", "_return_qty"]).assign(_universe="fixture")

    complaints, links = _build_complaints()
    # These must be normalised exactly as `io.loader._normalize_sheet` does, not
    # blanked. `complaint_recurrence` groups on `_title_norm`, so an empty string
    # made every complaint from one customer look like the same title — FIX-001's
    # recurrence signal was firing for the wrong reason, and any customer given a
    # second complaint fired it spuriously.
    complaints = complaints.assign(
        _universe="fixture",
        _title_norm=complaints[S.K_TITLE].map(normalize_fa),
        _text_norm=complaints[S.K_TEXT].map(normalize_fa),
        _resolution_norm=complaints[S.K_RESOLUTION_TEXT].map(normalize_fa)
    )
    links = links.assign(_universe="fixture")

    products = pd.DataFrame([
        {S.PRODUCT_ID: p, S.P_DESC: "نخ POY آزمایشی",
         S.P_QUALITY_CLASS: "Quality_Class_02", S.P_LUSTER: "Luster_Class_01",
         S.P_FAMILY: fam, S.P_COLOR: "Color_Class_01",
         S.P_SUBGROUP: "Denier_Subgroup_02", S.SOURCE_SYSTEM: "MDM",
         FIXTURE_FLAG: True}
        for p, fam in sorted({
            (p, f) for p, f in zip(sales[S.PRODUCT_ID], sales[S.P_FAMILY])
        })
    ])

    invoices = (
        sales.groupby([S.INVOICE_NO, S.CUSTOMER_ID], as_index=False)
        .agg(**{S.I_DATE: (S.F_DATE, "min")})
    )
    invoices[S.I_MONTH] = invoices[S.I_DATE].dt.month
    invoices[S.I_YEAR] = invoices[S.I_DATE].dt.year
    invoices[S.AVAILABLE_AT] = invoices[S.I_DATE]
    invoices[S.SOURCE_SYSTEM] = "ERP_SALES"
    invoices[FIXTURE_FLAG] = True
    invoices["_universe"] = "fixture"

    def empty(cols):
        return pd.DataFrame(columns=cols)

    frames = {
        S.S_CUSTOMERS: customers,
        S.S_PRODUCTS: products,
        S.S_INVOICES: invoices,
        S.S_SALES: sales,
        S.S_COST_REAL: cost,
        S.S_COLLECTIONS: collections,
        S.S_COMPLAINTS: complaints,
        S.S_COMPLAINT_LINK: links,
        S.S_CRM: _build_crm(),
        S.S_DEV_REQUESTS: _build_dev_requests(),
        S.S_LOT_QUALITY: _build_lot_quality(sales),
        S.S_HEMBAFT_LOT: pd.DataFrame([{
            S.HEMBAFT_LOT_KEY: f"{SHARED_HEMBAFT}|{SHARED_LOT}",
            S.HEMBAFT_ID: SHARED_HEMBAFT, S.LOT_ID: SHARED_LOT, S.PRODUCT_ID: "P-03",
            S.H_FIRST_OBSERVED: _d(300), S.AVAILABLE_AT: _d(300),
            S.SOURCE_SYSTEM: "ERP_SALES", FIXTURE_FLAG: True,
        }]),
        S.S_OFFERS: _build_offers(),
        S.S_WALLET: empty([S.CUSTOMER_ID, S.MONTH_KEY, S.AVAILABLE_AT,
                           S.W_ESTIMATED_TOTAL, S.W_NAFIS_PURCHASE, S.W_COMPETITOR]),
        S.S_MARKET: empty([S.M_WEEK_ID, S.CUSTOMER_ID, S.AVAILABLE_AT,
                           S.M_DEMAND_CHANGE]),
        S.S_COST_PLAN: empty([S.PC_ID, S.PRODUCT_ID, S.MONTH_KEY, S.AVAILABLE_AT,
                              S.PC_UNIT_COST, S.PC_VERSION]),
    }
    return Fixture(
        dataset=Dataset(frames=frames, settings=st),
        customer_ids=list(FIXTURE_CUSTOMERS),
        as_of=FIXTURE_AS_OF,
        intents={cid: why for cid, (_s, _l, _t, why) in FIXTURE_CUSTOMERS.items()},
    )


def run_fixture(settings: Settings | None = None):
    """Run the full pipeline over the fixture and return the pipeline state."""
    from ..llm.graph import run_pipeline

    fx = build_fixture(settings)
    state = run_pipeline(
        settings=fx.dataset.settings, as_of=fx.as_of, dataset=fx.dataset,
        use_graph=False, top_n=len(fx.customer_ids),
    )
    state["fixture"] = fx
    return state


def snapshot(state) -> dict:
    """A stable summary used as the regression snapshot."""
    run = state["signals"]
    queue = state["queue"]
    return {
        "as_of": state["as_of"].isoformat(),
        "customers": sorted(state["ctx"].population),
        "detectors_fired": sorted({s.detector for s in run.signals}),
        "signals_per_customer": {
            cid: sorted(s.detector for s in sigs)
            for cid, sigs in sorted(run.by_customer().items())
        },
        "buckets": {
            cid: state["quadrants"].bucket_of(cid)
            for cid in sorted(state["quadrants"].table.index)
        },
        "actions": [
            {"customer_id": a.customer_id, "bucket": a.bucket,
             "priority": a.priority, "n_evidence": len(a.evidence_ids)}
            for a in queue.actions
        ],
        "dropped": len(queue.dropped),
    }
