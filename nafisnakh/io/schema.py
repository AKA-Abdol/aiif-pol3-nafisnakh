"""Every sheet and column name in DATASET.xlsx as a constant (PLAN §5.1).

No magic string for a dataset column may appear anywhere else in the package.
Three documented columns are absent from the delivered file (PLAN §5.4):
``شکایات.Source_Type``, ``تعاملات_CRM.Channel``, ``درخواست_توسعه.Priority`` —
column lists are therefore always resolved dynamically against the frame.
"""

from __future__ import annotations

# ------------------------------------------------------------------- sheets
S_CUSTOMERS = "مشتریان"
S_PRODUCTS = "محصولات"
S_INVOICES = "فاکتورها"
S_SALES = "فروش"
S_COST_REAL = "اجزای_هزینه_تحقق"
S_COLLECTIONS = "وصول"
S_COMPLAINTS = "شکایات"
S_COMPLAINT_LINK = "اتصال_شکایت"
S_CRM = "تعاملات_CRM"
S_DEV_REQUESTS = "درخواست_توسعه"
S_LOT_QUALITY = "کیفیت_لات"
S_HEMBAFT_LOT = "همبافت_لات"
S_OFFERS = "آفرها"
S_WALLET = "سهم_سبد"
S_MARKET = "سیگنال_بازار"
S_COST_PLAN = "برآورد_هزینه_ماهانه"

ALL_SHEETS = [
    S_CUSTOMERS, S_PRODUCTS, S_INVOICES, S_SALES, S_COST_REAL, S_COLLECTIONS,
    S_COMPLAINTS, S_COMPLAINT_LINK, S_CRM, S_DEV_REQUESTS, S_LOT_QUALITY,
    S_HEMBAFT_LOT, S_OFFERS, S_WALLET, S_MARKET, S_COST_PLAN,
]

# expected row counts — regression guard (PLAN §5.1 / §5.5)
EXPECTED_ROWS = {
    S_CUSTOMERS: 644, S_PRODUCTS: 646, S_INVOICES: 14_423, S_SALES: 52_987,
    S_COST_REAL: 17_081, S_COLLECTIONS: 15_652, S_COMPLAINTS: 520,
    S_COMPLAINT_LINK: 597, S_CRM: 4_184, S_DEV_REQUESTS: 800,
    S_LOT_QUALITY: 13_865, S_HEMBAFT_LOT: 52, S_OFFERS: 2_500,
    S_WALLET: 7_488, S_MARKET: 130, S_COST_PLAN: 8_546,
}

# ------------------------------------------------------------ shared columns
CUSTOMER_ID = "Customer_ID"
PRODUCT_ID = "Product_ID"
INVOICE_NO = "شماره فاکتور"
SALES_LINE_ID = "Sales_Line_ID"
LOT_ID = "Lot_ID"
HEMBAFT_ID = "Hembaft_ID"
HEMBAFT_LOT_KEY = "Hembaft_Lot_Key"
AVAILABLE_AT = "Available_At"          # as-of control ONLY — never a feature
SOURCE_SYSTEM = "Source_System"
SALES_REP_ID = "Sales_Rep_ID"
MONTH_KEY = "Month_Key"

# --------------------------------------------------------------- مشتریان
C_LOCATION = "Location_ID"
C_SEGMENT = "Customer_Segment"
C_START_DATE = "Relationship_Start_Date"   # ⚠️ Jalali for the 20 CUST-* rows (§1.5)
C_CREDIT_LIMIT = "Credit_Limit"
C_PAYMENT_TERMS = "Payment_Terms_Days"
C_STATUS = "Customer_Status"

# --------------------------------------------------------------- محصولات
P_DESC = "شرح کالا"                 # concatenation of four columns — split, don't embed
P_QUALITY_CLASS = "Quality_Class_ID"
P_LUSTER = "دسته بندی براقیت"
P_FAMILY = "گروه کالا"
P_COLOR = "گروه رنگ"
P_SUBGROUP = "زیرگروه کالا"          # ordinal, never one-hot

# ---------------------------------------------------------------- فاکتورها
I_DATE = "تاریخ"
I_MONTH = "ماه"
I_YEAR = "سال"

# ------------------------------------------------------------------- فروش
F_LINE_NO = "ردیف فاکتور"
F_DATE = "تاریخ"
F_PAY_TYPE = "نوع پرداخت"
F_QTY = "مقدار"
F_UNIT_PRICE = "قیمت فی فروش"
F_AMOUNT = "مبلغ کل"
F_MONTH = "ماه"
F_YEAR = "سال"

# ------------------------------------------------- اجزای_هزینه_تحقق (realised)
RC_ID = "Cost_Record_ID"
RC_UNIT_COST = "هزینه کل به ازای واحد"
RC_RETURN_QTY = "مقدار برگشتی"
RC_RETURN_AMOUNT = "مبلغ برگشتی"
RC_CLOSE_DATE = "Cost_Close_Date"

# --------------------------------------------- برآورد_هزینه_ماهانه (planned)
PC_ID = "Estimate_ID"
PC_UNIT_COST = "هزینه کل برآوردی به ازای واحد"
PC_VERSION = "Estimate_Version"

# ------------------------------------------------------------------- وصول
V_ID = "Collection_ID"
V_INVOICE_DATE = "تاریخ فاکتور"
V_DUE_DATE = "تاریخ سررسید"
V_EVENT_DATE = "تاریخ رویداد وصول"
V_AMOUNT = "مبلغ وصول"
V_DAYS_LATE = "روز تأخیر"
V_BOUNCED = "چک برگشتی"
BOUNCED_YES = "بله"
BOUNCED_NO = "خیر"

# ---------------------------------------------------------------- شکایات
K_ID = "Complaint_ID"
K_FAMILY = "گروه کالا"
K_TITLE = "Complaint_Title"          # contained inside Complaint_Text → leakage
K_TEXT = "Complaint_Text"
K_HEMBAFT_REF = "Hembaft_Reference"
K_SEVERITY = "Severity"
K_CREATED_AT = "Created_At"
K_STATUS = "Complaint_Status"
K_RESOLVED_AT = "Resolved_At"
K_RESOLUTION_AVAILABLE_AT = "Resolution_Available_At"
K_RESOLUTION_TEXT = "Resolution_Text"
SEVERITY_ORDER = ["کم", "متوسط", "زیاد", "بحرانی"]

# --------------------------------------------------------- اتصال_شکایت
KL_PURCHASE_DATE = "Purchase_Date"
KL_QTY = "مقدار"
KL_RETURN_QTY = "مقدار برگشتی"
KL_RESULT = "Complaint_Result"
KL_AVAILABLE_AT = "Link_Available_At"

# -------------------------------------------------------------- تعاملات_CRM
X_ID = "Interaction_ID"
X_VERSION = "Record_Version"          # keep latest visible version (rule #5)
X_EVENT_TIME = "Event_Time"
X_UPDATED_AT = "Updated_At"
X_TYPE = "Interaction_Type"
X_SUMMARY = "Summary_Text"            # templated — regex the slots, don't embed
X_NEXT_ACTION = "Next_Action"
X_RECORD_STATUS = "Record_Status"

# ----------------------------------------------------------- درخواست_توسعه
D_ID = "Request_ID"
D_CREATED_AT = "Created_At"
D_TYPE = "Request_Type"
D_REQUIREMENT = "Requirement_Text"
D_DECISION_AT = "Decision_At"
D_STATUS = "Status"
D_OUTCOME = "Outcome_Text"            # categorical despite looking like prose
D_OWNER_UNIT = "Owner_Unit"
D_STATUS_APPROVED = "نمونه تأیید"
D_STATUS_REJECTED = "فنی رد"

# --------------------------------------------------------------- کیفیت_لات
Q_ID = "Quality_Record_ID"
Q_PRODUCTION_DATE = "Production_Date"
Q_MEASURED_AT = "Measured_At"
Q_TENSILE = "Tensile_Strength_cN_dtex"
Q_ELONGATION = "Elongation_Pct"       # stored as FRACTION despite the _Pct suffix
Q_EVENNESS = "Evenness_CV_Pct"        # stored as FRACTION
Q_OIL = "Oil_Pickup_Pct"              # stored as FRACTION
Q_SAMPLE_COUNT = "Sample_Count"
Q_RESULT = "Lab_Result"
Q_RESULT_REJECTED = "رد"          # 12 of 13,865 — every one shipped anyway (§3.4 #28)
FRACTION_PCT_COLUMNS = [Q_ELONGATION, Q_EVENNESS, Q_OIL]

# ------------------------------------------------------------ همبافت_لات
H_FIRST_OBSERVED = "First_Observed_Date"

# ----------------------------------------------------------------- آفرها
O_ID = "Offer_ID"
O_DATE = "Offer_Date"
O_FAMILY = "گروه کالا"
O_BASE_PRICE = "Base_Price_per_unit"
O_OFFERED_PRICE = "Offered_Price_per_unit"
O_DISCOUNT_PCT = "Offer_Discount_Pct"
O_TYPE = "Offer_Type"
O_VALIDITY_DAYS = "Validity_Days"
O_REASON = "Offer_Reason"
O_RESULT = "Result"
O_DECISION_AT = "Decision_At"
O_DECISION_AVAILABLE_AT = "Decision_Available_At"
O_TYPE_FINANCING = "مدت‌دار"          # a financing concession, NOT a price cut
O_RESULT_WON = "قبول"
O_RESULT_LOST = "رد"

# ---------------------------------------------------------------- سهم_سبد
W_ESTIMATED_TOTAL = "Estimated_Total_Purchase"
W_NAFIS_PURCHASE = "Nafis_Purchase"   # ⚠️ == 0 exactly when no sales → leakage (§1.2)
W_COMPETITOR = "Main_Competitor"
W_ESTIMATE_SOURCE = "Estimate_Source"

# ----------------------------------------------------------- سیگنال_بازار
M_WEEK_ID = "Week_ID"
M_REPORT_DATE = "Report_Date"
M_PRODUCT_MARKET = "Product_Market"
M_COMPETITOR = "Competitor"
M_CUSTOMER_SIGNAL = "Customer_Signal"
M_PRICE_INDEX = "Price_Index"          # concurrent descriptor, not leading
M_DEMAND_CHANGE = "Demand_Change"
M_MARKET_TREND = "Market_Trend"
M_ANALYSIS = "Analysis"                # categorical — do not embed

# ------------------------------------------------------------ derived names
D_MONTH = "_month"                     # period start (first of month), datetime64
D_GROSS_MARGIN = "_gross_margin"
D_UNIT_COST = "_unit_cost"
D_COST_SOURCE = "_cost_source"         # "realized" | "estimated" | "none"
D_REVENUE = "_revenue"

# family price ladder, rial/kg over the whole window (PLAN §3.4) — the ordinal
# behind `mix_downgrade`. Higher index = more valuable family.
FAMILY_PRICE_LADDER = {
    "Product_Family_04": 176.2,
    "Product_Family_03": 212.6,
    "Product_Family_06": 214.1,
    "Product_Family_01": 235.4,
    "Product_Family_02": 247.8,
    "Product_Family_GENERALIZED": 277.2,
    "Product_Family_05": 346.4,
}
FAMILY_LADDER_RANK = {
    name: i for i, name in enumerate(
        sorted(FAMILY_PRICE_LADDER, key=FAMILY_PRICE_LADDER.get)
    )
}

# date-ish columns per sheet, used by the loader to coerce types
DATE_COLUMNS = {
    S_CUSTOMERS: [C_START_DATE],
    S_INVOICES: [I_DATE, AVAILABLE_AT],
    S_SALES: [F_DATE, AVAILABLE_AT],
    S_COST_REAL: [RC_CLOSE_DATE, AVAILABLE_AT],
    S_COLLECTIONS: [V_INVOICE_DATE, V_DUE_DATE, V_EVENT_DATE, AVAILABLE_AT],
    S_COMPLAINTS: [K_CREATED_AT, AVAILABLE_AT, K_RESOLVED_AT,
                   K_RESOLUTION_AVAILABLE_AT],
    S_COMPLAINT_LINK: [KL_PURCHASE_DATE, KL_AVAILABLE_AT],
    S_CRM: [X_EVENT_TIME, AVAILABLE_AT, X_UPDATED_AT],
    S_DEV_REQUESTS: [D_CREATED_AT, AVAILABLE_AT, D_DECISION_AT],
    S_LOT_QUALITY: [Q_PRODUCTION_DATE, Q_MEASURED_AT, AVAILABLE_AT],
    S_HEMBAFT_LOT: [H_FIRST_OBSERVED, AVAILABLE_AT],
    S_OFFERS: [O_DATE, AVAILABLE_AT, O_DECISION_AT, O_DECISION_AVAILABLE_AT],
    S_WALLET: [AVAILABLE_AT],
    S_MARKET: [M_REPORT_DATE, AVAILABLE_AT],
    S_COST_PLAN: [AVAILABLE_AT],
}

# the as-of gate column per sheet (integration rule #4)
ASOF_COLUMN = {s: AVAILABLE_AT for s in ALL_SHEETS}
ASOF_COLUMN[S_COMPLAINT_LINK] = KL_AVAILABLE_AT
ASOF_COLUMN.pop(S_CUSTOMERS, None)      # dimension table, always visible
ASOF_COLUMN.pop(S_PRODUCTS, None)
