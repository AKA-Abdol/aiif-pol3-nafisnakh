# PLAN — Nafis Nakh AI B2B CRM Copilot

**Status:** design complete · nothing implemented yet · ready to start Phase 0
**Last updated:** 2026-08-19
**Working dir:** `/Users/amirhossein/Desktop/work/aiif/pol-3-nakhrisi`

> This file is the durable state of the project. **If context is lost, read this first.**
> It carries everything needed to implement without re-deriving: what the data actually
> is, every decision the user made and why, the full architecture, concrete detector and
> schema specs, the build checklist, and what still needs asking.
>
> **Do not re-derive facts recorded in §1 and §2.** They were verified by direct query.

---

## 0. Project goal

Build an AI B2B CRM copilot for **نفیس نخ (Nafis Nakh)**, a polyester filament yarn
producer. The project folder is `pol-3-nakhrisi` (پلی ۳ / نخ‌ریسی) — this is the **POY
spinning plant**, with a company-wide sales ledger attached.

### What it must do
1. Analyse and retain customer data across all needed dimensions.
2. Detect **signals**: an opportunity to make an offer, a needed retention action, or —
   for low/negative-margin accounts — a decision to *stop* pursuing them.
3. Rank triggered customers by signal importance × customer importance into a queue for
   the **sales manager**.
4. Every recommended action carries **evidence**.

### Strategic frame (user's words)
> هدف اصلی بیزینس درآمد بیشتر است. پس نگهداری مشتریان با رفتار منظم و خرید با حاشیه سود
> مناسب را باید نگه داریم و آنهایی که سودی ندارند و یا حتی ضرر هم باید عدم همکاری داشته
> باشیم. یکی از اهداف کلی ما این است که **تعداد مشتریان را کمتر ولی حاشیه سود را بیشتر و
> ثابت نگه داریم**.

*Maximise profit by keeping fewer customers at higher, more stable margin.*

### The 4 target buckets
| Bucket | Definition (user's words, condensed) |
|---|---|
| **grow** | جای رشد دارد — wallet share is below their capacity |
| **protect** | فقط باید مراقب آنها باشیم — they spend, take little time, are profitable |
| **fix** | تعداد خرید بالا، سودی ندارند — contract terms must change; tell the sales manager |
| **reduce** | خرید کم، سود کم — don't continue, no special offers, spend no sales energy |

### Data integration goal (user's words)
> ما در دیتاست ترکیب داده‌های ERP, MDM, CRM, PLM و complaints را در اختیار داریم. یکی از
> اهداف اصلی این پروژه **یکپارچه‌سازی این داده‌ها برای تولید action** است. یعنی با
> evidence درست بتوانیم اشاره کنیم که این اکشنی که پیشنهاد شده صحیح است.

### Reference
User's concept doc: https://claude.ai/code/artifact/47f23efd-864a-4890-9e93-d05fa8a0818d

---

## 1. DATA REALITY — verified findings (do not re-derive)

### 1.1 The dataset is two disjoint universes

| | Universe A | Universe B |
|---|---|---|
| Date range | 2019-12 → 2022-06 | 2025-03 → 2026-08 |
| Customers | 624, IDs `C_*` (Source_System = MDM) | 20, IDs `CUST-001..020` (CRM_MASTER) |
| Sales lines | 52,935 | 52 |
| Complaints | 480 | 40 |
| Collections | 15,618 | 34 |
| CRM · offers · سهم‌سبد · dev requests · market signals | present | **entirely absent** |

**No customer appears in both.** Customers with rich commercial history have no recent
complaints; customers with real complaint prose have no commercial history.

### 1.2 Universe A is synthetically generated — three published claims are artifacts

Verified by statistical test, not assumption. **These correct `PROCESSING.md`.**

| Claim in `PROCESSING.md` | Reality |
|---|---|
| `corr(discount, win) = -0.018` → *"discounting buys nothing, margin is being given away for nothing"* | The `آفرها` sheet has **no association with anything**: `Offer_Reason` χ² p=0.217, `Offer_Type` χ² p=0.132, `Offer_Discount_Pct` uniform on [0.010, 0.085], `corr(Validity_Days, win) = -0.129`. This is the *absence of a generator link*, not a commercial finding. **Must not appear in a client deck — it is falsifiable.** |
| `wallet_share` top churn predictor (0.227); *"customers leave when Nafis is a minor supplier, not when they stop buying"* | `Nafis_Purchase == 0` **exactly** when there were no sales that month — 0 exceptions in 7,488 rows; corr with actual monthly sales = 0.83. `wallet_share` mechanically encodes recency → **label leakage**. The conclusion is inverted: it *is* "they stopped buying". Among active months, share is uniform on [0.25, 0.75] = pure noise. The 9.8% mean is an artifact of averaging in 80% zero-months. |
| *"Median 23d late, 0.59% bounced"* | `روز تأخیر` is uniform on [0, 56] with hard walls; 23 is the generator midpoint. Bounces random at 0.59%. |

Same uniform-between-hard-walls signature in realised margin (−10.7% … +20.1%, median
7.7%) and in the four lab columns (already noted in `PROCESSING.md` §11).

**User's ruling (Q6):** *"نرخ‌های مالی فقط فیک شدن. تاریخ‌ها هم البته منطقی نیست."* —
only the **financial rates** are fake and the dates are unrealistic. The structure and
the behavioural patterns are workable. **This is the final data; build on it.**

**Consequence:** no quantitative business claim may be sourced from Universe A values.
The deliverable is the *architecture*, demonstrated on this data.

### 1.3 What is genuinely real and usable

- **The schema** — 16 sheets, 26 declared relationships, 7 integration rules. A faithful
  picture of their real ERP / MDM / CRM / QMS / PLM. Building against it *is* the deliverable.
- **The 45-title complaint taxonomy** and the whole domain vocabulary (`DOMAIN_GUIDE.md`).
- **The 40 Universe-B complaints + resolutions** — 100% unique, human-written Persian
  prose with typos, mixed Arabic/Persian orthography, real Jalali dates (۱۴۰۴/۰۱/۳۱),
  real corrective actions, escalation to committees. Median body 68 chars, median
  resolution 239 chars.
- Product SKU grammar — 11 un-anonymised POY codes (`DOMAIN_GUIDE.md` §3).

**The single best proof of LLM value in the whole dataset** (Universe B complaint text):

> «نخ در بعضي جاها سيمي ميباشد و همچنين پرز شديد نيز در بعضي بسته ها وجود دارد.
> **اين مشکل تکراري ميباشد** و قبلا هم وجود داشته و مشتري اعلام نموده که
> **درصورت تکرار قطع همکاري ميکند**.مشتري عکس ارسال نموده است»

An explicit churn threat + a repeat claim + photographic evidence supplied. Nothing in
the structured columns carries any of this. This is the demo centrepiece.

### 1.4 The two universes use different enums

| Field | Universe A | Universe B |
|---|---|---|
| `Complaint_Status` | بسته‌شده / درحال بررسی | پذیرفته‌شده / ردشده / نیازمند بررسی |
| Complaint text | 166 unique over 480 rows (2.9× duplication), templated | 40 unique over 40 rows |
| Resolution text | templated, 161 unique | real narrative, 40 unique |

Modelling on the 480 fits the generator. **All NLP/LLM evaluation must use the 40.**

### 1.5 Data defect not handled by `main.ipynb`

The 20 `CUST-*` rows carry `Relationship_Start_Date` in **Jalali** (`1395/08/12`); the
other 624 are Gregorian ISO (`2020-07-20`). Tenure and LTV silently break or go NaN for
exactly the 20 real customers. Must be normalised in `io/normalize.py`.

Jalali values present: 1394, 1395, 1396, 1397, 1398, 1399, 1400, 1401, 1402, 1403 (2 each).

### 1.6 Correct as-of anchor

`main.ipynb` anchors on p99 of sales dates (2022-05-09). Wrong for signal work — the
extract is winding down there, so *everyone* looks lapsed:

| as_of | eligible (≥6 invoices) | cadence breach >2× own median | active (<1×) |
|---|---|---|---|
| 2021-06-30 | 257 | **134 (52%)** | 94 |
| 2021-12-31 | 301 | 224 (74%) | 42 |
| 2022-03-31 | 313 | 223 (71%) | 61 |
| 2022-06-30 | 314 | **294 (94%)** ✗ | 4 |

**Demo anchor = `2021-06-30`.** Keep `as_of` a parameter. Row volume by year confirms
the taper: 2019: 241 · 2020: 26,195 · 2021: 21,898 · 2022: 4,601 · 2025: 41 · 2026: 11.

### 1.7 ASP must be deflated, never absolute

Absolute ASP trend flags **250 of 254** customers as "price rising >10%" — that is rial
inflation, not signal. Normalised against our own monthly index
(`customer_asp ÷ all_customer_asp_that_month`): 98 erosion, 63 gain, median −2.5%.
Cross-customer price-position spread p10 = 0.75 → p90 = 1.50 (a real 2× spread) — usable.

**Rule: every price/money metric is compared to a cohort or to the customer's own
baseline, never in absolute rials.**

### 1.8 Scale

At `as_of = 2021-06-30`: ~257 customers with enough history. Top 50 customers = 73% of
revenue (whole window: top 20% = 90.2%). The sales manager's real book is ~150–250
accounts. Small enough to afford an LLM pass per triggered account.

Activity at as_of 2022-06-30 for reference: 172 active in 90d, 243 in 180d, 383 in 365d.

### 1.9 Environment

- `.venv` Python **3.12.11** — has pandas, openpyxl, matplotlib, scikit-learn,
  arabic-reshaper, python-bidi, ipywidgets.
- **No LLM libraries installed yet. No `.env` file yet.**
- Ollama at `/usr/local/bin/ollama`. Models present:

| Model | Dim | Speed (4 Persian texts) | Use |
|---|---|---|---|
| `bge-m3:567m` | 1024 | 1.6 s | **default embedding** |
| `qwen3-embedding:8b-q8_0` | 4096 | 5.1 s | quality option |
| `embeddinggemma:300m` | — | — | fallback |
| `paraphrase-multilingual:278m` | — | — | fallback |
| `all-minilm:33m` | — | — | not multilingual, avoid |
| `gemma4:e4b-mlx`, `ornith:9b-bf16` | — | — | local generative, unused for now |

- Persian embedding smoke test (same-mechanism pair vs unrelated pairs):
  `bge-m3` 0.590 vs 0.454 → ratio **1.30** · `qwen3-8b` 0.406 vs 0.274 → ratio **1.48**.
  Both discriminate correctly. qwen3 separates better; bge-m3 is 3× faster.
- Ollama embed endpoint: `POST http://localhost:11434/api/embed`
  body `{"model": ..., "input": [...]}` → `{"embeddings": [[...]]}`.

---

## 2. DECISIONS MADE — every question asked and answered

| # | Question | User's answer | Consequence for implementation |
|---|---|---|---|
| **Q1** | Universe A looks generated — is real data coming? | **"همین است و همین می‌ماند — باید با همین دمو بزنیم"** | No real values will arrive. Build the architecture; make no quantitative business claims from Universe A. |
| **Q2** | Deliverable shape? | **Modular Python service + CLI** | A package with independent, testable blocks; JSON action-queue output; no UI. Convertible to an API later. `main.ipynb` stays as the exploration artifact only. |
| **Q3** | LLM access? | **"برای embedding می‌تونی از ollama local استفاده کنی که مدل‌های qwen و gemma embedding رو دارم و عالی‌ان. برای llm ترجیح من استفاده از langchain langgraph با ساختار استفاده فعلی از openrouter که بعداً بهت api key می‌دم. مدل هم فعلاً از gemini flash (or lite) استفاده کن. می‌تونیم بعداً قوی‌ترش هم بکنیم فعلاً همین کافیه برای تست که یهو هزینه زیاد نشه"** | Embeddings → Ollama local. Generation → LangChain + LangGraph over **OpenRouter**, model `google/gemini-2.0-flash-001` (or `-lite`). Key comes later. Both behind swappable interfaces. Optimise for low cost first. |
| **Q4** | Phase 1 scope? | **Signal engine + Complaint LLM block with golden set on the 40 real + Final aggregator with action queue.** (Metric layer *not* selected.) | ⚠️ The metric layer is a **strict prerequisite** — detectors are nothing but metric consumers. Building a **minimal** version: only what the 22 detectors need, not a full feature mart. Flagged to the user. |
| **Q5** | Interruption handling | **"we may stop you for some reasons — create your plan with todos and checkmarks, include all Q&A, future questions, and anything needed"** | This file. Keep §4 checkboxes current as work proceeds. |
| **Q6** | Demo strategy across two disjoint universes? | **"ببین روی هردوی اینها ترین کن. نکته اینه که نرخ‌های مالی فقط فیک شدن. تاریخ‌ها هم البته منطقی نیست. می‌تونی روی دیتایی که روی ناحیه ۲۰۲۲ هست کار کنی ولی یک نمونه طلایی هم برای تست آماده کنی. در واقع این دیتا دیتای نهایی ما است و باید روی این کار کنیم."** | Run the pipeline over **both** universes. Anchor commercial work in the ≤2022 region. Additionally build a **golden sample fixture** (§6) that exercises the full chain end-to-end for testing. This data is final. |
| **Q8** | Who labels the 40 real complaints? | **I propose labels, user reviews and corrects** | Produce `eval/golden_labels.yaml` covering all 40, human-editable, with a `reviewed: false` flag per row that the user flips. |
| **Q16** | Add a second model (`gpt-5.6-sol` via AgentRouter) without disturbing the Gemini choice? | **"in doc i say use gemeni, dont change it … add it as a new model but dont change previous configs for gemeni"** | Generation backends are now **named profiles** in `config.py`. `gemini` reproduces the Q3 decision byte-for-byte and stays the default; `agentrouter` is additive. Selected with `NN_LLM_PROFILE` or `--profile`. ⚠️ **AgentRouter is not usable yet — see §8 Q17.** |
| **Q19** | Which gateway and model for every LLM call? | **"for any llm api call use openrouter and use the google/gemini-3.7-flash model through the google-vertex/global provider"** | **Supersedes Q3's model and Q16's extra profiles.** One gateway: OpenRouter. One model: `google/gemini-3.7-flash`, pinned with OpenRouter provider routing to the `google-vertex/global` endpoint tag. The `agentrouter`, `agentrouter-claude` and `avalai` profiles were removed — both were already dead (§8 Q17, Q18). Embeddings became backend-selectable from env: `NN_EMBED_BACKEND=openrouter|ollama`, same bge-m3 model either way. |
| **Q20** | Should `Credit_Limit` feed the wallet/headroom metric? | **"credit limit برای wallet نیست که سهم سبد در بیاریم. ولی رابطشون اگر منطق داره باید اضافه بشه… آره اینو اضافه کن به اکشن نهایی دادن ازونجایی که credit limit در پیشنهاد کاملا موثر است"** | **Not as a capacity anchor** — against lifetime revenue it is spearman +0.900 / pearson −0.031, a monotone re-encoding of what the customer already buys, so it adds nothing to a headroom estimate built from the same quantity. **Yes as a gate on the recommended action**: credit room decides whether a growth step is executable at all. Ranking is untouched — it stays pure arithmetic over signals. |
| **Q10** | Is the 4%/month late charge real? | **"بله، ۴٪ ماهانه روی مانده و واقعاً وصول می‌شود"** | The late charge is **compensating revenue**, not pure opportunity cost. Formula in §3.5 reflects this. Raises Q11. |

### Standing instruction from the user
> ازت می‌خوام که خودت هم خلاقیت به خرج بدی … پس سوالاتو بعد از بررسی‌هات حتماً از من بپرس
> و **برای پیاده‌سازیشون حتماً از من approval بگیر**.

**Get explicit approval before implementing each phase.** Do not start Phase 0 without asking.

---

## 3. ARCHITECTURE

### 3.1 Layering principle

```
  deterministic metric layer ──emits──▶ typed Evidence objects
              │                                   │
              ▼                                   │
        signal detectors ──emits──▶ Signal (cites evidence_ids)
              │                                   │
              ▼ (only for customers with ≥1 signal)
          LLM blocks ──emits──▶ structured extraction + new Evidence
              │                                   │
              ▼                                   ▼
        aggregator LLM ─────────────────▶ Action (cites evidence_ids only)
              │
              ▼
         validate.py ── rejects any action whose numbers are not in the evidence set
```

**The LLM never writes a number.** It references `evidence_id`s. `validate.py` asserts
programmatically that (a) every cited id exists, (b) every id belongs to that customer,
and (c) no numeral appears in the action text that is absent from the cited evidence.
This is the only way "evidence-backed" is a guarantee rather than a claim. It is also
the direct technical answer to the user's stated goal in §0.

### 3.2 Package layout

```
nafisnakh/
  __init__.py
  config.py            Settings (pydantic-settings): paths, as_of, thresholds, models
  io/
    loader.py          read DATASET.xlsx + METADATA.xlsx → typed frames, parquet cache
    normalize.py       normalize_fa · Jalali→Gregorian · dual customer-ID namespace
    schema.py          sheet/column constants — no magic strings anywhere else
  core/
    evidence.py        ★ Evidence dataclass + EvidenceRegistry
    spine.py           invoice-grain-safe sales spine + as-of filter
    cohort.py          peer-cohort construction (segment × family × month)
  metrics/
    cadence.py         personalised inter-purchase rhythm
    economics.py       revenue, gross margin, risk-adjusted margin, LTV
    payment.py         DSO, late-charge revenue, capital cost, bounces, exposure
    wallet.py          share of wallet + headroom (leak caveat encoded)
    mix.py             family mix, deflated price position, SKU breadth
    quality.py         complaints, returns, همبافت blast radius
    engagement.py      CRM, offers, dev requests
  signals/
    base.py            Signal dataclass, Detector protocol, registry
    detectors/         the 22 detectors (§3.4), one module per group
    engine.py          run all · dedupe · score · rank
  llm/
    client.py          LangChain ChatOpenAI → OpenRouter, behind an interface
    embeddings.py      Ollama embeddings (bge-m3 default, qwen3-8b option)
    taxonomy.py        10-mechanism taxonomy + deterministic 45→10 map
    blocks/
      complaint.py     structured extraction from complaint text
      relationship.py  per-customer relationship-quality synthesis
    graph.py           LangGraph orchestration
  aggregate/
    quadrant.py        grow / protect / fix / reduce
    aggregator.py      final LLM: signals + metrics → ranked actions
    validate.py        ★ evidence-citation enforcement
  eval/
    golden.py          loader + scorer for the 40 real complaints
    golden_labels.yaml the labels themselves (user-reviewable)
    fixture.py         the golden-sample end-to-end fixture (§6)
  feedback.py          ★ manager decisions → detector ranking weights
  report.py            self-contained RTL HTML artifact for the sales manager
  api.py               FastAPI surface over the same library calls
  cli.py               typer: build · signals · calibrate · brief · report ·
                       eval · label · fixture · feedback · serve
tests/
```

### 3.3 Core contracts

```python
# core/evidence.py
@dataclass(frozen=True)
class Evidence:
    id: str                          # "EV-C_009817-cadence-001"
    customer_id: str
    kind: Literal["metric","event","text","comparison"]
    claim_fa: str                    # display-ready Persian sentence
    value: float | str
    unit: str | None                 # "روز" | "درصد" | "ریال" | "کیلوگرم" | None
    as_of: date
    window: tuple[date, date] | None
    source_rows: str                 # "فروش:1234,1240" — traceable back to the data
    provenance: dict                 # the formula that produced it
    confidence: float = 1.0          # <1.0 for LLM-derived and estimated evidence
```

```python
# signals/base.py
@dataclass(frozen=True)
class Signal:
    id: str
    customer_id: str
    detector: str                    # detector name, e.g. "cadence_breach"
    category: Literal["risk","opportunity","efficiency"]
    severity: float                  # 0–100, detector-normalised
    direction: Literal["deteriorating","improving","static"]
    headline_fa: str
    evidence_ids: list[str]
    first_detected_at: date
    value_at_stake: float            # money — drives ranking
    suggested_bucket: str | None     # hint toward grow/protect/fix/reduce
```

```python
# aggregate/aggregator.py
@dataclass(frozen=True)
class Action:
    customer_id: str
    rank: int
    priority: Literal["فوری","بالا","متوسط","پایین"]
    bucket: Literal["grow","protect","fix","reduce"]
    title_fa: str
    rationale_fa: str                # must cite [EV-...] inline
    recommended_step_fa: str
    owner: str                       # e.g. "مدیر فروش" | "کارشناس فنی"
    evidence_ids: list[str]
    signals: list[str]
    value_at_stake: float
```

**Detector protocol**

```python
class Detector(Protocol):
    name: str
    category: str
    requires: list[str]              # metric table names it consumes
    def detect(self, ctx: MetricContext) -> list[Signal]: ...
```

### 3.4 The 22 detectors

Thresholds are **starting defaults**; all live in `config.py` and must be calibrated
(§4, Phase 1b) so that no detector fires on >60% or <2% of the book at `as_of=2021-06-30`.

**Purchase behaviour**
| # | Name | Rule | Notes |
|---|---|---|---|
| 1 | `cadence_breach` | `days_since_last ÷ own_median_gap > 2.0` | needs ≥6 invoices; **personalised**, never global recency |
| 2 | `volume_decline` | last-3-month qty vs prior baseline < −30% | validated: 98 fire at as_of 2021-12 |
| 3 | `volume_surge` | > +30% | opportunity **and** a credit/capacity check |
| 4 | `first_order_no_repeat` | 1 invoice only, past 2× median first-repeat gap | onboarding failure |
| 5 | `mix_downgrade` | value-weighted family price-ladder position falling | see ladder below |
| 6 | `sku_narrowing` | distinct products/month shrinking ≥33% | losing share of their line |

Family price ladder (rial/kg, whole window, for the `mix_downgrade` ordinal):
`Family_04 176.2 < Family_03 212.6 < Family_06 214.1 < Family_01 235.4 < Family_02 247.8 < GENERALIZED 277.2 < Family_05 346.4`

**Price & margin**
| # | Name | Rule |
|---|---|---|
| 7 | `price_erosion` | **deflated** price position falling > 5% (§1.7) |
| 8 | `negative_risk_adj_margin` | risk-adj margin < 0 at meaningful volume → **fix** |
| 9 | `margin_below_peer_cohort` | margin percentile < 20 within segment × family cohort |
| 10 | `discount_without_return` | cumulative discount given vs realised volume/margin change |

**Payment**
| # | Name | Rule |
|---|---|---|
| 11 | `dso_slippage` | recent DSO vs own baseline, > +15 days |
| 12 | `bounced_cheque` | any `چک برگشتی = بله` in window — hard signal |
| 13 | `credit_exposure` | open exposure ÷ `Credit_Limit` > 0.8 |
| 14 | `late_interest_drag` | late-charge/capital-cost net eats > 25% of gross margin |

**Quality & relationship**
| # | Name | Rule |
|---|---|---|
| 15 | `complaint_recurrence` | same **mechanism** (not title), same customer, within 180d |
| 16 | `churn_threat_language` | explicit termination threat ← **LLM** |
| 17 | `unresolved_aging` | complaint open longer than median resolution days (24d) |
| 18 | `hembaft_blast_radius` | **preemptive**: other customers who received a همبافت someone already complained about |
| 19 | `return_rate_spike` | returned qty ÷ shipped qty above cohort p90 |
| 20 | `dev_request_stalled` | R&D request open > 90d (median decision 59d) — relationship debt |

**Opportunity**
| # | Name | Rule |
|---|---|---|
| 21 | `wallet_headroom` | high estimated total, low our share, good margin → **grow** |
| 22 | `cross_sell_peer_gap` | buys family X; similar-profile peers also buy Y |

**Detector #18 is the differentiator.** When one customer complains about a همبافت,
every other customer shipped that همبافت is a complaint *in flight*. Nobody asked for
this; it is unique to this domain (§5, integration rule #7) and is the strongest demo.

### 3.5 Key metric definitions

**Risk-adjusted margin** — the metric that makes the 4-bucket call defensible.
Confirmed by the user (Q10): the business charges **4% per month on the outstanding
balance and actually collects it**. So the late charge is *compensating revenue*, and
what slowness really costs is the firm's own cost of capital over the same period.

```
risk_adj_margin = gross_margin
                + (days_late / 30) × 4.0%  × outstanding    # late charge — collected
                − (days_outstanding / 30) × wacc_monthly × outstanding   # our capital cost
                − bad_debt_provision(bounce_history)
                − cost_to_serve(complaints, returns, R&D requests)
```

`wacc_monthly` is a config parameter — **needs a real figure from Nafis Nakh (Q11)**.
If their cost of capital is below 4%/month, a slow payer is *net accretive*, which
inverts the naive reading of payment behaviour. This parameter matters more than it looks.

**Personalised cadence** — use the distribution of each customer's *own* inter-purchase
gaps. A monthly buyer 45 days silent is critical; a quarterly buyer 90 days silent is
normal. Global recency gets both wrong. Median own-gap across the book is **14 days**.

**Deflated price position** — `customer_asp_month ÷ all_customer_asp_that_month`. Trend
the last 3 months against the prior baseline. Never trend absolute rials (§1.7).

**Cost-to-serve** — complaints × handling cost + returns value + open R&D request load.
Needs a rate card from the business; until then use a config-set nominal per event and
label it clearly as an assumption in the evidence `provenance`.

**LTV** — tenure-aware cumulative risk-adjusted margin, not cumulative revenue.
⚠️ Requires the Jalali fix (§1.5) or it is NaN for exactly the 20 real customers.

### 3.6 Complaint LLM block

Do **not** cluster from scratch. Prior KMeans (k=8) got only 36.3% purity against the 45
titles because the 45 are near-synonyms. Instead: deterministically map the 45 titles →
**10 physical mechanisms**, then let the LLM do only what the taxonomy cannot.

**The 10 mechanisms (proposed map — user should review):**

| Mechanism | Titles folded in |
|---|---|
| `M01_package_formation` | بدپیچی · بد پيچي · بدپیچی بسته · بدپیچی / سفتی بسته · بدپیچی و ریزش نخ · پیچش بسته/ تنشن پیچش · حلقه‌های نامنظم |
| `M02_filament_damage` | فیلامنت و پرز · فیلامنت پارگی و پرز · پارگی فیلامنت · پرز و حلقه‌های بلند · گره و اسنارل |
| `M03_mass_count_deviation` | تلرانس نمره · خارج بودن نمره · نوسان دنیر · نوسان دنیر / CV · اختلاف وزنی · حجم کمتر از انتظار |
| `M04_dye_shade` | شید رنگ · شید رنگ / راه‌راهی · اختلاف شید بین لاها |
| `M05_intermingling` | مینگل بیشتر از حد · مینگل کمتر از حد |
| `M06_spin_finish` | روغن نامتوازن · آلودگی / لکه روغن |
| `M07_twist_ply` | جهت تاب اشتباه · نوسان تعداد تاب · اختلاف تعداد لا · بازشدن لا / جدایش · باز شدن لای نخ · کم شدن لای نخ · تنشن و تاب مجازی · جداشدن مغزی و افکت |
| `M08_tube_packaging` | دوک دست دوم / خرابی دوک · خرابی دوک و بسته‌بندی |
| `M09_labelling_logistics` | الصاق لیبل اشتباه · لیبل پایه نخ اشتباه · آسیب حمل و نقل · آسیب دیدگی در حمل و نقل · بازشدن نخ درجه C |
| `M10_mechanical_properties` | استحکام پایین · استحکام پایین / پارگی · اختلاف ازدیاد طول · جمع‌شدگی خارج از محدوده · کریمپ / حجم ناهمگون · سیمی بودن · نامناسب بودن زير دست پتو |

The LLM then does only what the taxonomy cannot:
- assign free text to a mechanism (with confidence)
- flag **"none of these"** *and write the description* for a proposed new category
- **extract what no column holds:**

```python
class ComplaintExtraction(BaseModel):
    mechanism: MechanismId | Literal["UNKNOWN"]
    mechanism_confidence: float
    proposed_new_category_fa: str | None    # only when UNKNOWN
    churn_threat: bool                      # "قطع همکاری" / "دیگر خرید نمی‌کنیم"
    churn_threat_quote_fa: str | None
    repeat_claim: bool                      # "تکراری است" / "قبلاً هم بوده"
    financial_demand: bool                  # refund / credit / compensation asked
    escalation_level: Literal["عادی","پیگیری","تشدید","بحرانی"]
    attributed_fault: Literal["تولید","بسته‌بندی","حمل","مشتری","نامشخص"]
    evidence_supplied: bool                 # photo / sample / lab report mentioned
    hembaft_mentioned: list[str]            # 10-digit campaign numbers in the text
    affected_quantity_kg: float | None
    summary_fa: str                         # one sentence for the sales manager
```

**These extractions are worth more than the category.** `churn_threat` alone drives
detector #16, which is the highest-severity signal in the whole system.

Preprocessing before any LLM or embedding call: `normalize_fa()` (Arabic ي/ك → Persian
ی/ک, Arabic-Indic → Persian digits, ZWNJ handling). This collapsed **11.5%** of the raw
complaint vocabulary as pure orthographic noise in the prior work — reuse that function
from `main.ipynb` §2.

### 3.7 Aggregator

Input per customer: profile card + quadrant assignment + all signals with their evidence
`claim_fa` strings. **Never raw dataframes, never raw numbers outside evidence.**

Output: ranked `Action` list. Ranking key: `severity × log1p(value_at_stake) × bucket_weight`,
computed **deterministically in Python**, not by the LLM. The LLM writes the *reasoning
and the recommended step*, not the ordering — ordering must be reproducible and auditable.

`validate.py` rejects any action that fails the three checks in §3.1. On rejection: one
retry with the validator's complaint appended, then drop the action and log it.

### 3.8 Cost control

Metric layer runs for all customers (free). LLM blocks fire **only** for customers with
≥1 triggered signal. At `as_of = 2021-06-30` that is roughly 40–80 customers → ~120
gemini-flash calls per run, not 2,750. Cache LLM responses keyed by content hash so
re-runs during development cost nothing.

---

## 4. TODO

### Phase 0 — scaffolding ✅ **DONE**
- [x] `pyproject.toml` — deps: `langchain`, `langgraph`, `langchain-openai`, `pydantic`,
      `pydantic-settings`, `typer`, `pandas`, `pyarrow`, `openpyxl`, `httpx`, `pyyaml`, `pytest`
- [x] `nafisnakh/config.py` — Settings (§7 parameter list)
- [x] `.env.example` — `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OLLAMA_HOST`, model names
- [x] `io/schema.py` — every sheet and column name as a constant (§5.1)
- [x] `io/loader.py` — load + parquet cache + metadata contract parse
- [x] `io/normalize.py` — `normalize_fa` (port from `main.ipynb` §2), **Jalali→Gregorian (§1.5)**,
      customer-ID namespace unification
- [x] `core/evidence.py` — `Evidence` + `EvidenceRegistry`
- [x] `core/spine.py` — invoice-grain-safe spine, as-of filter (**integration rule #2**)
- [x] `core/cohort.py` — peer cohorts (segment × family × month)
- [x] tests: loader round-trip, Jalali conversion, spine row count = 52,987, rule-2 non-fanout

> **Phase 0 verification (all reproduce PLAN §5.5 exactly):** spine 52,987 lines ·
> 4,422.7M revenue · 644 customers · cost basis realised 32.24% / planned 67.76% ·
> blended GM 10.09% · 10,405 loss-making lines · 93 bounced cheques · median 23d late.
> The 20 Jalali `Relationship_Start_Date` values now parse (`1395/08/12` → `2016-11-02`).
> 28 tests green.

### Phase 1a — minimal metric layer ✅ **DONE** *(prerequisite; not user-selected but required)*
- [x] `metrics/base.py` — `MetricContext`, table registry, dependency `BUILD_ORDER`, evidence helpers
- [x] `metrics/cadence.py`
- [x] `metrics/economics.py` — incl. **risk-adjusted margin** (§3.5)
- [x] `metrics/payment.py`
- [x] `metrics/mix.py` — incl. **deflated price position** (§1.7)
- [x] `metrics/quality.py` — incl. همبافت blast-radius traversal (**integration rule #7**)
- [x] `metrics/wallet.py` — leakage caveat encoded in `provenance`, not hidden
- [x] `metrics/engagement.py`
- [x] tests: every metric emits well-formed Evidence with traceable `source_rows`

> **Phase 1a verification.** Whole layer builds in ~1 s for 526 customers and emits
> ~7.4k Evidence objects. Reproduces the anchor figures: 257 customers eligible at
> `as_of=2021-06-30`, median own-gap 14 days, deflated price position centred on 1.0.
>
> **Two deviations from §1.6 / §1.2, both deliberate:**
> 1. `cadence_ratio` uses an **effective gap** (median, falling back to the mean,
>    floored at 1 day). 33 customers place several invoices on one day, so their
>    median gap is 0; §1.6 implicitly treated them as an infinite ratio. Counting
>    them properly gives **115 breaches** at the anchor, not 134 — the fastest-cadence
>    accounts are now scored rather than divided by zero.
> 2. `سهم_سبد` has **zero rows visible at the anchor** (its `Available_At` starts
>    2021-08-05). Headroom therefore falls back to a **peer-capacity estimate**
>    (segment p75 of revenue per active month), emitted at confidence 0.5 and
>    labelled `peer_capacity_estimate`. Detector #21 stays alive without pretending
>    the wallet sheet said something it cannot say at this date.
>
> **همبافت blast radius works and lands in universe B**, where the real complaint
> prose is: 18 of the 20 `CUST-*` customers were shipped from a همبافت another
> customer has already complained about (e.g. `CUST-003`: 7 lines, 40,120 kg across
> 5 همبافت). This is the demo centrepiece and it is real, not constructed.

### Phase 1b — signal engine ✅ **DONE** ★ user-selected
- [x] `signals/base.py` — `Signal`, `Detector` protocol, registry, severity `scale()`
- [x] 22 detectors in `signals/detectors/` (§3.4) — behaviour · price_margin · payment · quality · opportunity
- [x] `signals/engine.py` — run · dedupe · severity score · `value_at_stake` ranking
- [x] **Calibration pass** — all 22 within the guard-rails at `as_of=2021-06-30`
- [x] Emit `outputs/signals_<as_of>.json` + `outputs/calibration_<as_of>.csv`

> **Phase 1b verification.** 1,661 signals over 518 customers, 2.8 s, no detector errors.
> Ranking is `severity × log1p(value_at_stake/scale) × bucket_weight × category_weight`,
> computed in Python — the LLM never orders the queue.
>
> **Calibration is measured against each detector's *eligible* population, not the whole
> book.** A returns detector cannot fire on a customer with no returns; dividing by 526
> would condemn a correctly-scoped detector as "too narrow". `BaseDetector.eligible()`
> declares that population per detector. Final fire rates (fired/eligible):
> `volume_decline` 56% · `discount_without_return` 55% · `cross_sell_peer_gap` 47% ·
> `sku_narrowing` 46% · `cadence_breach` 44% (114/257) · `wallet_headroom` 38% ·
> `late_interest_drag` 38% · `negative_risk_adj_margin` 27% · `dev_request_stalled` 30% ·
> `unresolved_aging` 29% · `volume_surge` 26% · `price_erosion` 21% ·
> `margin_below_peer_cohort` 20% · `first_order_no_repeat` 19% · `credit_exposure` 18% ·
> `mix_downgrade` 14% · `dso_slippage` 11% · `return_rate_spike` 10% · `bounced_cheque` 9% ·
> `complaint_recurrence` 7% · `churn_threat_language` 0 · `hembaft_blast_radius` 0.
> The last two are correct zeros at this anchor: #16 needs the LLM block (Phase 1c) and
> refuses to fall back to a keyword heuristic, and #18 has no cross-customer همبافت
> complaint yet in universe A — it fires on 18 customers at the full horizon.
>
> **Threshold changes made during calibration, and why:**
> - Age-based detectors (#17, #20) now fire above `max(config floor, p70 of the open
>   population)`. At a mid-extract `as_of` later resolutions are not yet visible, so 94%
>   of open complaints are older than the book median — a fixed floor was a tautology.
> - `sku_narrowing` (#6) now requires the customer to still be buying. A customer who
>   stopped entirely is a cadence breach; counting them twice charged one fact to two
>   detectors.
> - `discount_without_return` (#10) needs ≥4 price offers (median per customer is 1).
> - `cross_sell_peer_gap` (#22) adoption threshold is 25%, not 60%. Customers in this
>   book are strongly specialised by product family — no non-dominant family reaches 30%
>   adoption inside a peer group, so a "most of your peers buy this" rule found nothing.
>
> **Two scale bugs found and fixed by looking at the output:**
> - `cost_to_serve` was configured in absolute rials (5,000,000/complaint) while the
>   median invoice in this file is ~72,800 units — the currency unit is never declared
>   (§5.4). One complaint cost more than most customers' lifetime revenue and produced
>   risk-adjusted margins of −3,249%. It is now expressed as a **multiple of the median
>   invoice value**, which is scale-free. Risk-adjusted margin now has median +5.1% and
>   144/526 customers negative.
> - `effective_gap` is floored at 1 day. Sub-daily mean gaps were producing cadence
>   ratios of 875×.

### Phase 1c — complaint LLM block ✅ **DONE** ★ user-selected
- [x] `llm/embeddings.py` — Ollama, `bge-m3` default, `qwen3-8b` option, disk cache
- [x] `llm/client.py` — LangChain → OpenRouter, gemini-flash, behind an interface, response cache
- [x] `llm/taxonomy.py` — the deterministic 45→10 map from §3.6 (all 45 titles map, 0 unmapped)
- [x] `llm/blocks/complaint.py` — `ComplaintExtraction` structured output + offline rule path
- [x] `eval/golden_labels.yaml` — **labels proposed for all 40, `reviewed: false`** (Q8)
- [x] `eval/golden.py` — scorer: mechanism accuracy, per-field P/R, title baseline
- [x] Eval report → `outputs/eval_complaints_golden.txt`

> **Phase 1c verification.** No live model call was made — the key is still pending (Q14).
> Everything around the call is built and tested: 83 tests green.
>
> **⚠️ The eval currently certifies nothing, and says so.** With no key the block runs a
> narrow keyword extractor tagged `extraction_source="rules"`. Its mechanism accuracy is
> **0.875 — identical to the title-lookup baseline**, because the rule path *is* the title
> lookup. The report prints the baseline and the lift (`+0.000`) next to the accuracy and
> refuses to mark the run as a pass. That is the honest reading: the model's real value is
> on the rows where the text disagrees with the title, and those have not been tested yet.
>
> Offline scores on the 40 (rule path): `churn_threat` P=1.00 R=1.00 · `repeat_claim`
> P=0.67 R=1.00 · `evidence_supplied` P=1.00 R=1.00 · `escalation_level` 0.825 ·
> `attributed_fault` **0.475** ← the field with the most headroom for the model.
>
> **`financial_demand` has zero positives in all 40 texts.** The scorer reports it as
> unscoreable rather than printing a meaningless 0.0 or 1.0. Worth telling the client:
> customers here describe defects, they do not ask for money in the complaint itself.
>
> **11 of the 40 are flagged `ambiguous: true`** — texts describing more than one
> mechanism (e.g. CMP-0003 is both bobbin damage and ribbon winding; CMP-0021's text says
> package-end breakage while the resolution traces it to a damaged tube edge). On the 29
> unambiguous rows the title map is already 100% correct. **CMP-0033's complaint text is
> nothing but two همبافت numbers** — a deliberate test that the model does not invent a
> mechanism from an empty description.
>
> **The centrepiece works end-to-end.** Once the block has run, detector #16 fires exactly
> once across the whole book — on CUST-003's «درصورت تکرار قطع همکاري ميکند» — at severity
> 95 with the repeat claim attached.
>
> Ollama is **not installed on this machine**, so `bge-m3` was not re-benchmarked here;
> `OllamaEmbeddings.available()` returns False and the class raises rather than returning
> zero vectors, so "no backend" can never be mistaken for "these texts are unrelated".

### Phase 1d — aggregator & action queue ✅ **DONE** ★ user-selected
- [x] `aggregate/quadrant.py` — grow/protect/fix/reduce on risk-adjusted margin × headroom
- [x] `aggregate/aggregator.py` — final LLM, evidence-ids only, deterministic offline composer
- [x] `aggregate/validate.py` — citation enforcement (§3.1), retry-once-then-drop
- [x] `llm/graph.py` — LangGraph wiring (6 nodes, also runnable sequentially for tests)
- [x] `eval/fixture.py` — the golden sample (§6) + checked-in regression snapshot
- [x] `cli.py` — `build` · `signals` · `brief` · `eval` · `label` · `fixture` · `calibrate`
- [x] End-to-end run → ranked JSON action queue + a readable Persian brief

> **Phase 1d verification.** 117 tests green. Full run at `as_of=2021-06-30`:
> 1,663 signals → 518 triggered customers → quadrants **حفظ 204 · رشد 178 · کاهش 79 ·
> اصلاح 65** → 25 actions, **0 dropped in validation**.
> Outputs: `actions_2021-06-30.json` · `brief_2021-06-30.txt` ·
> `signals_2021-06-30.json` · `evidence_2021-06-30.json` (7.7k evidence objects) ·
> `calibration_2021-06-30.csv` · `eval_complaints_golden.txt`.
>
> **The validator earns its place.** On the first end-to-end run it rejected **every
> action** — the offline composer was citing only the first four evidence ids while its
> title quoted a number backed by the fifth. Two real bugs surfaced through it:
> 1. Evidence ids were being read as numeric claims (`[EV-C_117580-cadence-001]` parsed
>    as the numbers 117580 and 001). Identifiers are now stripped before numeral
>    extraction and checked separately as citations.
> 2. Rounding: the metric layer emits `11.34`, a signal headline says `11.3`. A numeral
>    is now accepted when some cited value rounds to it **at the numeral's own
>    precision** — a text may round a number it was given, but never invent precision.
>
> **The offline composer is held to the same standard as the model** and passes it: no
> number appears in an action that is not in its cited evidence.
>
> **The golden-sample fixture fires all 22 detectors** and covers all four buckets.
> §6 asked for 8–12 customers; it needed **16** to reach every detector — cross-sell
> alone requires a peer group of 8. `nafisnakh/eval/fixture_snapshot.json` is checked in
> as the regression baseline.
>
> **Three generalisable bugs the fixture caught** (each would have hit a real small book):
> - `days_since_*` metrics crashed when a source sheet was empty (all-NaN float column
>   minus a Timestamp). Now routed through `days_since()` and degrade to NaN.
> - Percentile-based detectors (#17, #19, #20) could never fire when fewer than 5
>   observations existed — a p70 of three values is just the largest of the three.
>   Below `min_percentile_observations` they now use the configured floor.
> - Priority bands were computed over the truncated top-N, so the same customer was
>   labelled «پایین» at `--top 5` and «فوری» at `--top 50`. They are now computed over
>   the whole book before truncation.
>
> **A data finding worth recording:** the generator seeded the real universe-B churn
> complaint (CUST-003's «درصورت تکرار قطع همکاري ميکند») **verbatim into two universe-A
> customers** (C_117580, C_180745). Detector #16 now detects when a complaint body is
> shared across customers, **halves the severity** and appends a warning to the headline
> — one copied string is not three customers threatening to leave. This is another
> instance of the §5.4 duplication problem and another argument for evaluating NLP only
> on the 40.

### Phase 2 ✅ **DONE**
- [x] `llm/blocks/relationship.py` — per-customer relationship synthesis
- [x] `report.py` — presentation artifact for the sales manager (self-contained RTL HTML)
- [x] `api.py` — FastAPI surface (`nafisnakh serve`)
- [x] `feedback.py` — sales manager marks actions done/dismissed → ranking recalibration

> **Phase 2 verification.** 117 tests still green; graph now has 8 nodes
> (`load → metrics → complaint_llm → feedback → detect → quadrant → relationship → aggregate`).
>
> **`relationship.py`** reads the relationship rather than a document: CRM interaction mix
> → dominant theme, repeated complaint mechanisms, open R&D requests and open complaints
> → *unmet promises from our side*, and a recommended opening tone. It runs only for the
> top-N triggered accounts (cost bounded by the queue, not the book) and is offline-safe
> with a rule composer at confidence 0.5. On the real book at the anchor it puts
> C_117580 at «بحرانی» and the rest of the top 10 at «در معرض خطر».
>
> **The feedback loop is deliberately shy, and that is the design.**
> - Feedback is append-only JSONL; one decision credits every detector on that action.
> - `done` vs `dismissed`/`wrong` becomes a **ranking weight**, never a threshold change
>   and never a mute. A detector that stops firing could never earn its way back, and one
>   bad month should not delete a signal that matters twice a year.
> - Weights are shrunk toward 1.0 by a prior (`feedback_prior_strength=10`) and are
>   **exactly 1.0 below `feedback_min_events=10`**. Three dismissals is an opinion, not
>   evidence. Weights stay inside [0.65, 1.35].
> - `snoozed` is excluded from the ratio — it is neither a yes nor a no. `wrong` is
>   recorded separately because it means *the fact was not true*, which is a data problem,
>   not a prioritisation one.
>
> **The artifact** (`outputs/report_<as_of>.html`, ~64 KB, no external assets) leads with
> the four buckets, shows every evidence id inline rather than behind a tooltip, and marks
> ⚠ on anything resting on Q7/Q11/Q12 — the sales manager should never discover in a
> meeting that a number was a config default. If any action was dropped in validation, the
> page says so.
>
> **The API adds no logic of its own** — every endpoint projects something the library
> already computes, so there is no second ranking implementation to drift. The pipeline is
> cached per `as_of`; `POST /feedback` is the only write and invalidates the cache, because
> the next queue must be ranked with the verdict just given.
> `GET /health · /summary · /actions · /customers/{id} · /evidence/{id} · /calibration ·
> /feedback · /report` · `POST /feedback`.

---

## 4b. HOW TO RUN AND TEST — every block is independently runnable

Install once: `.venv/bin/pip install -e .` — then `nafisnakh` is on the path.
**Nothing here needs an API key.** Every command works offline today; the LLM
blocks fall back to a labelled rule path and say so (Q14).

### Test one layer at a time

| What you want to check | Command | What you should see |
|---|---|---|
| Loader, Jalali fix, spine, metric layer | `nafisnakh build` | 526 customers · 36,880 visible lines · 7 metric tables · ~7.4k evidence |
| The 22 detectors + calibration | `nafisnakh calibrate` | one row per detector with `fired / eligible / fire_rate / status`; exits non-zero if any is out of range |
| Signal file only | `nafisnakh signals` | 1,663 signals over 518 customers → `outputs/signals_<as_of>.json` |
| Complaint LLM block vs the 40 real complaints | `nafisnakh eval` | mechanism accuracy vs the title baseline, per-field P/R, and an explicit refusal to certify a rules-only run |
| Golden labels for human review (Q8) | `nafisnakh label --show 5` | the proposed labels, one complaint at a time |
| **The whole chain, on synthetic data, in ~5 s** | `nafisnakh fixture` | `آشکارسازهای فعال‌شده: 22 از 22` · all four buckets · `رد شده: 0` |
| **The whole chain, on the real book** | `nafisnakh brief --top 25` | the ranked Persian brief + `outputs/actions_<as_of>.json` |
| Sales-manager artifact (HTML) | `nafisnakh report --top 25` | `outputs/report_<as_of>.html` — opens in any browser, RTL, no assets |
| Record what the manager did | `nafisnakh feedback --customer C_245948 --decision done` | the event, plus what it does (and does not yet) change |
| Effect of feedback so far | `nafisnakh feedback --show` | per-detector acted/dismissed and the resulting weights |
| HTTP API | `nafisnakh serve` | `http://127.0.0.1:8000/docs` |
| Which model backends exist, and do they answer? | `nafisnakh models --test` | one line per profile, its key status, and a live HTTP probe |

Any command that calls a model takes `--profile`, but `gemini` is the only
profile now (Q19 — OpenRouter only). The response cache keys on the model name,
so changing model never serves an answer written by the previous one. Provider
routing is deliberately *not* in that key: a pin selects a datacentre, not a
model.

Any command takes `--as-of 2021-12-31` to move the anchor, and `-v` for logs.

### Test a different point in time

```bash
nafisnakh calibrate --as-of 2021-12-31     # do the thresholds still hold?
nafisnakh brief --as-of 2022-03-31 --top 10
```

### The test suite

```bash
.venv/bin/python -m pytest tests -q          # 117 tests, ~45 s
.venv/bin/python -m pytest tests/test_spine.py -q      # Phase 0 regressions vs §5.5
.venv/bin/python -m pytest tests/test_metrics.py -q    # Phase 1a
.venv/bin/python -m pytest tests/test_signals.py -q    # Phase 1b + calibration
.venv/bin/python -m pytest tests/test_llm.py -q        # Phase 1c + golden set
.venv/bin/python -m pytest tests/test_aggregate.py -q  # Phase 1d + fixture + validator
```

### Use it as a library — each block standalone

```python
from datetime import date
from nafisnakh.io.loader import load_dataset
from nafisnakh.metrics.base import make_context, build_metrics
from nafisnakh.signals.engine import run_detectors, calibrate

ds  = load_dataset()                                   # parquet-cached, ~1 s after first read
ctx = build_metrics(make_context(ds, as_of=date(2021, 6, 30)))
ctx.table("payment").head()                            # any metric table on its own
run = run_detectors(ctx, only=["cadence_breach"])      # one detector in isolation
print(calibrate(run, ctx))
```

The pipeline is also a LangGraph, so a single stage can be run or replaced:

```python
from nafisnakh.llm.graph import run_pipeline
state = run_pipeline(as_of=date(2021, 6, 30), top_n=10)   # or use_graph=False
state["ctx"], state["signals"], state["quadrants"], state["queue"]
```

### What changes when the OpenRouter key arrives (Q14)

Put `OPENROUTER_API_KEY=...` in `.env`. Nothing else changes: `llm/client.py`
switches from `rules` to `live`, responses are cached by content hash so re-runs
are free, and `nafisnakh eval` starts producing a verdict instead of refusing to
issue one.

---

## 5. REFERENCE DATA

### 5.1 Sheets (16) — rows × columns

| Sheet | Rows | Cols | Source system |
|---|---:|---:|---|
| `مشتریان` | 644 | 9 | MDM / CRM_MASTER |
| `محصولات` | 646 | 8 | MDM |
| `فاکتورها` | 14,423 | 7 | ERP_SALES |
| `فروش` | 52,987 | 22 | ERP_SALES |
| `اجزای_هزینه_تحقق` | 17,081 | 10 | ERP_COSTING |
| `وصول` | 15,652 | 11 | ERP_COLLECTIONS |
| `شکایات` | 520 | 15 | QMS |
| `اتصال_شکایت` | 597 | 13 | QMS bridge |
| `تعاملات_CRM` | 4,184 | 13 | CRM |
| `درخواست_توسعه` | 800 | 12 | PLM_REQUESTS |
| `کیفیت_لات` | 13,865 | 16 | QMS lab |
| `همبافت_لات` | 52 | 7 | ERP_SALES |
| `آفرها` | 2,500 | 16 | CRM |
| `سهم_سبد` | 7,488 | 8 | CRM |
| `سیگنال_بازار` | 130 | 12 | MARKET_3C |
| `برآورد_هزینه_ماهانه` | 8,546 | 7 | COSTING_PLAN |

### 5.2 The 7 integration rules (from `METADATA.xlsx`)

1. All customer-bearing sheets join to `مشتریان` on `Customer_ID`.
2. **Never join `فروش` to `وصول` directly** — both hang off the invoice at different
   grains. Aggregate `وصول` to invoice level first. *This one silently destroys analyses.*
3. Complaints reach sales lines only through the `اتصال_شکایت` bridge.
4. A record is usable only from its `Available_At` onward.
5. Use the latest visible `Record_Version` per `Interaction_ID`.
6. Realised and estimated cost are separate; realised wins.
7. `Hembaft_ID` ≠ `Lot_ID`; they meet only via `Hembaft_Lot_Key` (52 rows).
   19,354 distinct `Lot_ID`, 48 distinct `Hembaft_ID`. **Blast radius groups on
   `Hembaft_ID`, never `Lot_ID`.**

### 5.3 Categorical enums (complete)

| Column | Values |
|---|---|
| `مشتریان.Customer_Segment` | A (231) · B (206) · C (207) |
| `مشتریان.Customer_Status` | فعال (273) · غیرفعال (371) |
| `مشتریان.Payment_Terms_Days` | 0 (526) · 30 (77) · 45 (8) · 60 (4) · 75 (4) · 90 (25) |
| `مشتریان.Source_System` | MDM (624) · CRM_MASTER (20) |
| `فروش.نوع پرداخت` | cash_or_prepaid · short_term · long_term · payment_generalized |
| `گروه کالا` | Product_Family_01…06 · Product_Family_GENERALIZED |
| `زیرگروه کالا` | Denier_Subgroup_01…05 · Denier_GENERALIZED — **ordinal, never one-hot** |
| `دسته بندی براقیت` | Luster_Class_01 · Luster_Class_02 · Luster_GENERALIZED · Luster_Unknown |
| `گروه رنگ` | Color_Class_01/02/03 · Color_GENERALIZED |
| `Quality_Class_ID` | Quality_Class_01…08 · _GENERALIZED · _OTHER — **ordinal (commercial grade AA/A/B/C)** |
| `Location_ID` | LOC-001…016 (16 provinces) |
| `Sales_Rep_ID` | 8 distinct |
| `شکایات.Severity` | کم · متوسط · زیاد · بحرانی |
| `شکایات.Complaint_Status` | بسته‌شده · درحال بررسی *(Universe A)* / پذیرفته‌شده · ردشده · نیازمند بررسی *(Universe B)* |
| `اتصال_شکایت.Complaint_Result` | رسیدگی‌شده (382) · باز (163) · پذیرفته‌شده (37) · ردشده (11) · نیازمند بررسی (4) |
| `تعاملات_CRM.Interaction_Type` | پیگیری سفارش (840) · قیمت و تخفیف (734) · برنامه خرید (617) · وصول مطالبات (568) · کیفیت محصول (549) · خدمات فنی (441) · نمونه محصول (435) |
| `تعاملات_CRM.Next_Action` | پیگیری تلفنی · بازدید فنی · ارسال نمونه · جلسه قیمت · بدون اقدام |
| `تعاملات_CRM.Record_Status` | ثبت اولیه · اصلاح‌شده |
| `درخواست_توسعه.Request_Type` | تغییر دنیر · تغییر تعداد فیلامنت · بهبود استحکام · کاهش پرز · بهبود شید رنگ · بسته‌بندی اختصاصی |
| `درخواست_توسعه.Status` | نمونه تأیید · درحال توسعه · درحال بررسی · فنی رد |
| `درخواست_توسعه.Owner_Unit` | تحقیق‌وتوسعه · کنترل کیفیت · برنامه‌ریزی تولید |
| `آفرها.Offer_Type` | مدت‌دار (918) · قیمتی (798) · حجمی (784) |
| `آفرها.Offer_Reason` | تسویه سریع · افزایش حجم سفارش · معرفی محصول جدید · افزایش سهم از سبد · حفظ مشتری کلیدی · رقابت قیمتی · آزمون محصول |
| `آفرها.Result` | رد (662) · قبول (651) · منقضی‌شده (642) · درحال مذاکره (545) |
| `سیگنال_بازار.Customer_Signal` | وصول متمرکز · تحویل سریع · ظرفیت محدود · قیمت رقابتی |
| `سیگنال_بازار.Demand_Change` | افزایش · ثابت · کاهش |
| `سیگنال_بازار.Market_Trend` | افزایش تقاضا · تقاضای ثابت · فشار قیمتی · کاهش تقاضا |
| `سهم_سبد.Main_Competitor` | رقیب X · رقیب Y · رقیب Z · تأمین‌کننده محلی |
| `سهم_سبد.Estimate_Source` | مشتری اظهار · فروش کارشناس · برآورد بازدید |
| `وصول.چک برگشتی` | بله (93) · خیر (15,559) |

⚠️ **`Offer_Type = مدت‌دار` is a financing concession, not a price cut.** Comparing its
`Offer_Discount_Pct` to a `قیمتی` offer on the same scale is an apples-to-oranges error.

### 5.4 Gotchas — carry these into every module

- **Rule #2** is the one that silently destroys analyses (§5.2).
- Three documented columns are **absent** from the delivered file:
  `شکایات.Source_Type` · `تعاملات_CRM.Channel` · `درخواست_توسعه.Priority`.
  Resolve column lists dynamically.
- `Available_At` columns are **as-of control only — never features.** They encode *when
  we learned* something, not what happened.
- `Lab_Result` is 99.91% pass (13,853 vs 12) — near-useless. Use band position of the
  four continuous values; 62% of lots sit at a spec-band edge.
- `Elongation_Pct`, `Evenness_CV_Pct`, `Oil_Pickup_Pct` are stored as **fractions**
  despite the `_Pct` suffix. Multiply by 100 before display.
- `Tensile_Strength_cN_dtex` is correctly named — normalise by **dtex**, not denier.
- Currency unit is never declared in the metadata. Keep one scale throughout
  (`currency_scale = 1e6`, label `M`, as in the prior run).
- Realised cost covers only **32.2%** of lines; quote every margin with its `cost_source` mix.
- `Outcome_Text` (7 distinct) and `Analysis` (28 distinct over 130 rows) look like prose
  but are **categorical**. Do not embed them.
- `شرح کالا` is a concatenation of four existing columns — split, don't embed.
- `Summary_Text` is **templated** (`فوریت`, `کد پیگیری` slots) — regex the slots first;
  embedding the whole string mostly encodes the template.
- `Complaint_Title` is contained inside `Complaint_Text` — training body→title leaks.
  Honest score with a group split on deduplicated bodies: 0.806.
- **67% of Universe-A complaint bodies are verbatim duplicates.** Naive
  "cosine > 0.75 vs any earlier complaint" flags 87.5% as recurrence. Scope to the *same
  customer* and separate exact from near duplicates → 8.7% genuine.
- Complaints concentrate in large, active, long-tenured accounts (10× mean revenue,
  22.5% vs 63.4% dormancy). **Any "complaints cause churn" claim needs tenure controls.**
- `سهم_سبد` covers only 2021-07 … 2022-06. Never trend across the gap.
- **`Credit_Limit` mixes two incompatible scales across the universes.** Universe A:
  5,000 … 11,700,000 (median 330,000). Universe B: 2,000,000,000 … 18,000,000,000
  (median 6bn, only 6 distinct round values). That is a **~18,000× jump**, while the
  two universes' median sales-line amounts differ by only 54× (10,680 vs 577,342).
  Consequence: `open_balance / Credit_Limit` — the `credit_exposure` detector — is
  structurally ~0 for every Universe-B customer, so the detector goes silent on them.
  Harmless at `as_of = 2021-06-30` (Universe B has no visible sales then); it becomes a
  real blind spot at any 2025–2026 anchor.
- **`Credit_Limit` is monotone in revenue but not proportional to it.** Against lifetime
  revenue: **spearman +0.900, pearson −0.031**. So it ranks customers by size almost
  perfectly while carrying no usable level information (`Credit_Limit / lifetime revenue`
  spans 0.072 … 2.53, median 0.615). Do not use it as a capacity anchor for
  wallet/headroom — being a monotone function of what they already buy from us, it adds
  nothing to a headroom estimate built from the same quantity. Its *residual* (limit
  relative to own purchases) is the part that carries information, and it answers a
  different question: how much more the customer is **permitted** to buy.
- `Price_Index` correlates −0.545 *contemporaneously* with realised ASP and weakens with
  lag — a concurrent descriptor, **not a leading indicator**.

### 5.5 Prior-run baseline numbers (for regression testing)

```
Spine: 52,987 sales lines · 4,422.7M revenue · 644 customers · 646 products
Cost basis coverage: planned 67.8% / realised 32.2%
Blended gross margin 10.09% · 10,405 loss-making lines
Revenue concentration: top 20% of customers = 90.2% of revenue
Collections: median 23d late · 0.59% bounced · 545.4M open exposure
Lab: 0.09% fail rate · 62.0% of lots at a spec-band edge
Complaints: 520 rows · 45 curated types · 8.7% recurrences · median 24d to resolve
Offers: 49.6% win rate on decided quotes · corr(discount, win) = −0.018
Wallet share: mean 9.8% (⚠️ see §1.2) · 12 months only
Dev requests: 23.0% approved · median 59d to decide
```

---

## 6. THE GOLDEN SAMPLE FIXTURE

Per Q6: *"یک نمونه طلایی هم برای تست آماده کنی"*.

**Purpose:** a small, fixed, checked-in fixture that exercises **every block end-to-end**,
so the full chain can be tested and demoed without depending on which universe a customer
falls in. It is a **test fixture**, not a claim about reality.

**Requirements**
- 8–12 customers, hand-picked or composed, covering all four buckets and at least one
  instance of each of the 22 detectors.
- Must include a customer with an explicit `churn_threat` in the complaint text (take the
  real Universe-B text quoted in §1.3).
- Must include a همبافت blast-radius case: one complainant + ≥2 other customers shipped
  the same `Hembaft_ID`.
- Must include a `fix` case: high volume, negative risk-adjusted margin.
- Must include a `reduce` case and a `grow` case with real wallet headroom.
- **Every fixture row carries `is_fixture: true`** and is excluded from any output
  presented as analysis of real customers.
- Expected outputs are snapshotted so the fixture doubles as a regression test.

---

## 7. CONFIG PARAMETERS

```python
# nafisnakh/config.py — every tunable, nothing hard-coded below this
dataset_path        = "DATASET.xlsx"
metadata_path       = "METADATA.xlsx"
out_dir             = "outputs"
cache_dir           = ".cache"

as_of               = "2021-06-30"      # §1.6 — the demo anchor
date_from           = "2019-12-01"
date_to             = "2026-12-31"
currency_scale      = 1e6
currency_label      = "M"

# economics
cost_basis          = "realized_then_estimated"   # | "realized_only"
late_charge_monthly = 0.04               # confirmed by user (Q10), actually collected
wacc_monthly        = None               # ⚠️ Q11 — needs a real figure
bad_debt_rate       = None               # ⚠️ derive from bounce history or ask
cost_to_serve_rates = {"complaint": None, "return": None, "dev_request": None}  # ⚠️ Q12

# detector thresholds (§3.4) — calibrate in Phase 1b
cadence_breach_ratio      = 2.0
cadence_min_invoices      = 6
volume_decline_pct        = -0.30
volume_surge_pct          = 0.30
price_erosion_pct         = -0.05
sku_narrowing_pct         = -0.33
dso_slippage_days         = 15
credit_exposure_ratio     = 0.80
margin_peer_percentile    = 20
complaint_recurrence_days = 180
dev_request_stall_days    = 90
late_interest_drag_pct    = 0.25

# LLM — OpenRouter only (Q19). Every call goes through this one gateway.
llm_profile         = "gemini"
llm_provider        = "openrouter"
llm_model           = "google/gemini-3.7-flash"
llm_base_url        = "https://openrouter.ai/api/v1"
llm_provider_only   = "google-vertex/global"   # OpenRouter provider-routing pin
llm_temperature     = 0.0
llm_cache           = True

# LLM_PROFILES in config.py
#   gemini   google/gemini-3.7-flash   https://openrouter.ai/api/v1   OPENROUTER_API_KEY
#            pinned to endpoint tag google-vertex/global
#   valid tags for a model: GET /api/v1/models/<model>/endpoints
#   (gemini-3.7-flash: google-vertex/global[/flex|/priority], google-ai-studio)

# embeddings — same bge-m3 model either way, so the geometry does not move
embed_backend          = "openrouter"        # | "ollama"
openrouter_embed_model = "baai/bge-m3"       # 1024-dim, used when backend=openrouter
embed_base_url         = "https://openrouter.ai/api/v1"
embed_model            = "bge-m3:567m"       # ollama tag, used when backend=ollama
ollama_host            = "http://localhost:11434"

# output
plot_lang           = "fa"
top_n_actions       = 25
random_state        = 42
```

---

## 8. OPEN QUESTIONS — still need user answers

| # | Question | Blocks | Why it matters |
|---|---|---|---|
| **Q7** | Does Nafis Nakh have **real per-product cost data**? Realised cost covers 32% of lines and the values are generated. | Phase 1a completion | The entire margin thesis — and therefore the grow/protect/fix/reduce call — rests on it. If not available, the quadrant ships as mechanism-only, driven by whatever cost basis they later plug in. |
| **Q11** | What is Nafis Nakh's **monthly cost of capital** (`wacc_monthly`)? | risk-adj margin | If it is below the 4%/month late charge, a slow payer is **net accretive** — which inverts the naive reading of payment behaviour and moves customers between `fix` and `protect`. |
| **Q12** | Rate card for **cost-to-serve**: what does handling one complaint, one return, one R&D request actually cost? | risk-adj margin | Without it, `cost_to_serve` is a config guess labelled as an assumption. |
| **Q13** | Should the **10-mechanism taxonomy** in §3.6 be reviewed by a Nafis Nakh QC person before it becomes the system's backbone? | Phase 1c | It is my mapping of their 45 titles. Getting it wrong propagates into every complaint signal. Cheap to validate, expensive to fix later. |
| **Q14** | OpenRouter **API key** — user said it comes later. | Phase 1c live calls | Until then LLM blocks are written and unit-tested against recorded fixtures; no live calls. |
| **Q15** | Who is the **actual end user** — one sales manager, or several reps with their own books? | aggregate/ output shape | Determines whether the queue is one global ranked list or partitioned by `Sales_Rep_ID` (8 distinct reps exist in the data). |
| **Q17** | **AgentRouter blocks non-whitelisted API clients. The keys are fine; the client is the problem.** Verified: `GET /v1/dashboard/billing/subscription` returns **200** with both keys (valid, payment method present, $50 limit) — so authentication works. But `/v1/chat/completions` and `/v1/models` are gated. Enforcement is **layered and intermittent**: the same key/model/prompt returns `401 unauthorized_client_error` in one minute and `400 content-blocked` the next. Decisive proof it is not our request: **a deliberately nonexistent model name (`definitely-not-a-real-model`) returns the same 401**, so the gate fires *before* model resolution — nothing about model, prompt or language reaches it. Tested across 2 keys × 4+ models × 2 languages. AgentRouter whitelists specific coding-agent clients (OmniRoute, OpenCode, ForgeCode all hit this). → **Need a key for a provider without client gating**: OpenRouter (the Q3 choice), OpenAI, or an Iranian gateway (AvalAI, Metis). | all live runs | ⚠️ **Correction to an earlier note in this file:** I previously recorded that Persian prompts specifically were content-blocked while English passed. That was wrong — it was an artifact of the intermittent enforcement. A clean 2×2×2 matrix showed language makes no difference. | 
| **Q18** | **AvalAI works — the account does not.** `https://api.avalai.ir/v1` authenticates cleanly (no client gating): `GET /v1/models` returns **385 models**, and errors are specific and actionable. Two account-side blocks, both fixable by the user: (1) the key is **restricted to `gpt-5.5`** — every other model, including cheap ones, returns `403 model_access_limited`; AvalAI's own message says *"consider creating a new key without 'Advanced settings' to grant access to all models"*; (2) `gpt-5.5` itself returns `429 insufficient_quota` — **balance 0.132 UNIT does not cover one call**, let alone 348. → Add credit at https://ava.al/billing, and ideally issue an unrestricted key so a cheap model (`gemini-2.5-flash-lite`) can carry the bulk run. | all live runs | This is the first provider where the block is entirely on the user's side of the account rather than a wall we cannot pass. The `avalai` profile is wired and verified end-to-end through `LLMClient`; the 429 arrives from our own client code path, which proves the plumbing is correct. |

---

## 9. THINGS TO TELL THE CLIENT (honest-reporting obligations)

1. **The measurement gap.** The lab panel tests polymer properties; customers complain
   about *package* properties (بدپیچی, پلیسه سر دوک, ریبونی, مینگل, شید). That is why lab
   data barely predicts complaints — it is not a data problem, it is a
   **measurement-coverage** problem. This is a concrete, actionable recommendation and it
   is better than any model that could be fitted.
2. **Severity is recorded but not driving priority.** Time-to-resolution is flat across
   severity levels (23–25 days median) and *critical* complaints have the **lowest**
   resolution rate (58.8%).
3. **Scope.** This is POY-plant data with a company-wide sales ledger attached — say so;
   it changes how the complaint findings generalise.
4. **Do not repeat the three claims corrected in §1.2.** They are falsifiable.

---

## 10. FILES

| File | Role |
|---|---|
| `DATASET.xlsx` | 16 sheets, source data |
| `METADATA.xlsx` | the contract: grains, PKs, 189 column definitions, 26 relationships, 7 integration rules, 8 DQ caveats |
| `DOMAIN_GUIDE.md` | industry + company domain reconstruction (yarn chemistry, SKU grammar, defect vocabulary, FA→EN glossary) |
| `PROCESSING.md` | prior processing writeup — ⚠️ **§1.2 above corrects three of its headline claims** |
| `main.ipynb` | prior exploration notebook, 54 cells, runnable; reuse `normalize_fa()` and `fa()` from §2 |
| `outputs/` | 23 CSVs + `COLUMN_PROCESSING_CATALOG.xlsx` + `RUN_SUMMARY.txt` from the prior run |
| `PLAN.md` | **this file** |

---

## 11. CHANGELOG

- **2026-08-20 (calibrate review)** — Calibration used to pass a verdict on any
  eligible population, however small, so every subset run produced a wall of false
  alarms — "1 fired of 1 eligible = 100%, too_broad" — which trains the reader to
  ignore the table. New status **`insufficient`** below `calib_min_eligible = 30`:
  reported in the table, excluded from `failures`, and surfaced as a count by the CLI
  so a quiet table is not misread as a clean bill. On the full book the smallest
  eligible population is 51, so **no full-book verdict changed** (22/22 ok at
  2021-06-30; still exit 1 with `cadence_breach` + `volume_decline` too_broad at
  2021-12-31). 2 new tests; 127 passing.

- **2026-08-20 (signals review)** — `nafisnakh signals` and `nafisnakh calibrate` were
  running the **whole 8-node pipeline** and discarding everything past `detect`: with a
  key present that is one relationship call per customer plus one drafting call per
  action, for two commands whose only output is a signal file and a fire-rate table.
  `llm/graph.py` gained `nodes_upto()` and `run_pipeline(stop_after=...)`; both commands
  now stop at `detect`. Measured: 4.3 s with a live key, byte-identical 1,663 signals,
  and no LLM call at all. `signals` also gained `--sample` / `--customers` with the same
  subset filename suffix `build` uses, so a 12-customer run writes
  `signals_<as_of>__12c.json` instead of overwriting the full book. 3 new tests; 125 passing.

- **2026-08-20 (credit gate on actions)** — Q20 applied. `Credit_Limit` now shapes the
  *recommended step*, never the ranking and never the headroom estimate.
  `metrics/payment.py` gained `credit_room_value`, `credit_limit_months` and
  `credit_room_state` ∈ {`open`, `exhausted`, `unknown`}, plus a `credit-room`
  evidence for the 427 customers with room. `exhausted` is `exposure_ratio ≥
  credit_exposure_ratio` (0.80); `unknown` is the scale guard —
  `credit_room_max_months = 60`, which catches the 5 Universe-A outliers here and
  every Universe-B customer at a late anchor (§5.4). `aggregate/aggregator.py`
  gained `credit_state()`, `CREDIT_NOTE_FA` and `CREDIT_BLOCKED_STEP_FA`: on
  `exhausted`, a **grow** or **protect** step becomes a credit-limit review owned
  by «واحد مالی و مدیر فروش», while **fix** and **reduce** are left alone because
  neither asks the customer to buy more. The model is told the credit state in the
  prompt and instructed to respect it; the state is recorded on every action as
  `detail.credit_room`. The credit-room claim is stated as a **share of the limit**,
  not in rials: 29% of the values are under 50,000 and the project-wide M scale
  would have printed them as "0.0M" — a claim asserting room while showing zero.
  Full book at the demo anchor: open 427 · exhausted 94 · unknown 5.
  5 new tests in `tests/test_aggregate.py`; 122 passing.

- **2026-08-20 (OpenRouter only)** — Q19 applied. Generation consolidated onto
  OpenRouter / `google/gemini-3.7-flash`, pinned to the `google-vertex/global`
  endpoint tag via OpenRouter provider routing (`extra_body={"provider": {...}}`,
  configurable as `NN_LLM_PROVIDER_ONLY`). The dead AgentRouter and AvalAI
  profiles were deleted along with their key fields. Embeddings gained a second
  backend: `NN_EMBED_BACKEND=openrouter|ollama`, defaulting to `openrouter` on
  `baai/bge-m3` — the same model as the local Ollama default, at the same 1024
  dims, so §1.9's benchmark still holds. `OllamaEmbeddings` and the new
  `OpenRouterEmbeddings` now share a `BaseEmbeddings` that owns normalisation,
  the disk cache (keyed on backend **and** model) and batching.
  Verified live: pinned structured call returns `source="live"`; a deliberately
  wrong pin returns 404 rather than silently routing elsewhere; OpenRouter
  embeddings return 1024-dim vectors for Persian; 117/117 tests still pass.
  **The retired `google/gemini-2.0-flash-001` default is gone** — it no longer
  resolves on OpenRouter.

- **2026-08-19 (build)** — **Phases 0, 1a, 1b, 1c and 1d implemented and green.**
  `nafisnakh/` package: 7 metric tables, 22 detectors, complaint LLM block with the
  45→10 taxonomy, quadrant assignment, evidence-citation validator, LangGraph pipeline,
  16-customer golden fixture firing all 22 detectors, Typer CLI, 117 tests.
  Phase 0 reproduces every §5.5 baseline exactly. See the per-phase verification notes
  in §4 for the deviations from this plan and the reasons for each.
  **Still outstanding:** Q7, Q11, Q12, Q13, Q14, Q15; user review of
  `eval/golden_labels.yaml`.
- **2026-08-19 (profiles)** — Second generation backend added as a **named profile**
  (`agentrouter` / `gpt-5.6-sol`) alongside the untouched `gemini` default; `nafisnakh
  models --test` probes both. AgentRouter currently rejects all direct API clients
  (Q17), so no live run has been made yet.
- **2026-08-19 (Phase 2)** — Relationship synthesis block, sales-manager HTML artifact,
  FastAPI surface and the feedback→ranking loop implemented. Pipeline graph grew to 8
  nodes. Every checkbox in §4 is now ticked; what remains is not code but the six open
  questions in §8 and the human review of the golden labels.

- **2026-08-19** — Data investigation complete. Two-universe structure identified;
  Universe A confirmed synthetic by statistical test; three `PROCESSING.md` headline
  claims corrected; Jalali date defect found; as-of anchor (2021-06-30) and ASP
  deflation requirement established; Ollama Persian embeddings benchmarked.
  Q1–Q6, Q8, Q10 answered by user. Full architecture, 22 detectors, 10-mechanism
  taxonomy, evidence contract and config surface specified.
  **Nothing implemented yet — awaiting approval to start Phase 0.**
