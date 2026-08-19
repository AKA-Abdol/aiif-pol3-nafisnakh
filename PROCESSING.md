# Processing Guide — `DATASET.xlsx` × `METADATA.xlsx`

Companion document to [`main.ipynb`](main.ipynb). The notebook *does* the work; this file explains
**what each section processes, why it processes it that way, and which columns need which technique**.

---

## 1. What this data actually is

A polyester/POY filament producer (نفیس نخ), with **six source systems** flattened into one workbook:

| Source system | Sheets it feeds | What it knows |
|---|---|---|
| `ERP_SALES` | `فاکتورها`, `فروش`, `همبافت_لات` | Invoices, 52,987 sales lines, production-lot traceability |
| `ERP_COSTING` / `COSTING_PLAN` | `اجزای_هزینه_تحقق`, `برآورد_هزینه_ماهانه` | Realised line cost, planned product-month cost |
| `ERP_COLLECTIONS` | `وصول` | 15,652 collection events, days late, bounced cheques |
| `QMS_*` | `شکایات`, `اتصال_شکایت`, `کیفیت_لات` | Complaints + free text, complaint→line bridge, lab measurements |
| `CRM_*` | `تعاملات_CRM`, `آفرها`, `سهم_سبد` | Interactions, quotes and outcomes, share-of-wallet estimates |
| `PLM_REQUESTS` / `MARKET_3C` | `درخواست_توسعه`, `سیگنال_بازار` | Product-development funnel, weekly competitor intelligence |

Two master sheets (`مشتریان` 644 rows, `محصولات` 646 rows) anchor everything. All personally
identifying information has been stripped — no names, no cities, no industries. `Location_ID`,
`Quality_Class_ID` and the `Product_Family_*` labels are the anonymised replacements.

**The metadata file is not documentation, it is a contract.** It declares the grain and primary key of
every sheet, the business definition and allowed-value domain of all 189 columns, 26 relationships
with cardinality and obligation, seven integration rules, and eight data-quality caveats. §3–§5 of the
notebook read it programmatically and *test the data against it* rather than trusting either one.

### The seven integration rules and where they are enforced

| # | Rule | Enforced in |
|---|---|---|
| 1 | All customer-bearing sheets join to `مشتریان` on `Customer_ID` | §5 orphan check |
| 2 | **Never join `فروش` to `وصول`** — both go via `فاکتورها` | §10 (collections aggregated to invoice grain first) |
| 3 | Complaints reach sales lines only through the `اتصال_شکایت` bridge | §7 spine build |
| 4 | A record is usable only from its `Available_At` onward | §6 `apply_as_of()`, `P["as_of"]` |
| 5 | Use the latest visible `Record_Version` per `Interaction_ID` | §6 CRM de-duplication |
| 6 | Realised and estimated cost are separate; realised wins | §7 `cost_source` fallback chain |
| 7 | `Hembaft_ID` ≠ `Lot_ID`; they meet only via `Hembaft_Lot_Key` | §11 blast-radius traversal |

Rule 2 is the one that silently destroys analyses. Sales lines and collection events both hang off an
invoice; joining them directly fans out revenue by the number of collection events and inflates every
figure downstream.

---

## 2. Section-by-section processing

### §1–§2 · Parameters and text infrastructure
Every downstream cell reads the `P` dict — window, as-of date, population filters, cost basis, churn
threshold, NLP backend, cluster/topic counts. Nothing is hard-coded below §1.

Two Persian-specific problems are solved before any analysis:

* **`normalize_fa()`** — the free text mixes Arabic `ي/ك` with Persian `ی/ک`, Arabic-Indic with
  Persian digits, and ZWNJ with plain spaces. Normalisation collapses **11.5% of the raw complaint
  vocabulary** as pure orthographic noise. Without it TF-IDF treats `ميباشد` and `می‌باشد` as two
  unrelated tokens and every text model degrades.
* **`fa()`** — handles fonts, shaping and chart language. Three things had to be right:

  1. **Font coverage.** macOS `Geeza Pro` is the obvious Persian font and the wrong choice: it has
     **no Latin digits and no `/`**, so every numeric axis tick renders as a tofu box. The notebook
     therefore *tests* coverage (`_covers()`) instead of trusting a font name, and picks
     `Arial Unicode MS`, which covers Persian letters and digits together.
  2. **Shaping must be detected, not assumed.** matplotlib ≥3.7 built against **libraqm** does
     HarfBuzz shaping and bidi natively — and this build does. Pre-processing with
     `arabic_reshaper` + `python-bidi` on such a build *double-processes* the string and renders it
     reversed and disconnected. `_raqm_shapes()` probes it by measuring whether cursive joining
     collapses the width of `ببب`, and only applies the manual workaround when it is genuinely needed.
  3. **Chart language.** Titles and axis labels are authored in English and translated through
     `TITLE_FA` when `P["plot_lang"] == "fa"` (the default), so charts read in Persian for a Persian
     audience. Set `P["plot_lang"] = "en"` to flip the whole notebook back to English.

### §3–§5 · Conformance and integrity (processing type: *validation*)
Generated from the metadata, not written by hand:

* **Schema drift** — three columns are documented but **absent from the delivered file**:
  `شکایات.Source_Type`, `تعاملات_CRM.Channel`, `درخواست_توسعه.Priority`. Every cell that would have
  used them resolves its column list dynamically and says so.
* **Domain validation** — every enumerated `Allowed_Values_or_Rule` is tested. **Zero violations.**
* **Referential integrity** — all 26 declared edges. **Zero orphans**, including across the two
  co-existing ID namespaces (`C_009817`-style and `CUST-003`-style both resolve).
* **Primary-key uniqueness** — all 16 grains hold, including the two composite keys.

The file is exceptionally clean structurally. The problems it does have are *semantic*, and they are
the subject of §6–§7.

### §6 · As-of discipline (processing type: *point-in-time control*)
Every event sheet carries an event date **and** an `Available_At`. Publication lag is a median of 1 day
everywhere, never negative. Setting `P["as_of"]` rewinds the entire notebook to what was knowable on
that date — this is what makes leak-free model training possible, and it is the single most valuable
structural property of the dataset.

`Available_At` columns are classified `as-of-control` in the catalogue: they govern filtering and must
**never** be used as predictors, because they encode *when we learned* something, not what happened.

### §7 · The spine, and a temporal discontinuity you must know about
`spine` = one row per sales line + invoice + customer + product + cost + lab + complaint flags.

**Finding:** the ERP body ends around **2022-06**, but 52 lines are stamped **2025–2026**. Those 52 are
all `SL-CMP` — the recently-traced, complaint-linked shipments, a different extract spliced into the
same sheet at the same grain. Consequence: `max(date)` is *not* a valid "today". Anchoring recency on
it labels **99.1%** of customers as churned. The notebook therefore anchors on the p99 of sales dates
(2022-05-09), which yields a usable **52.6%** churn base rate. The diagnostic prints itself in §7.

### §8–§11 · Structured analytics
| Section | Processing | Key output |
|---|---|---|
| §8 Commercial | Time-series aggregation, mix cross-tabs, Pareto/ABC | Top 20% of customers = **90.2%** of revenue |
| §9 Profitability | Cost fallback chain, margin distribution | Blended margin **10.09%**; **19.6%** of lines sold at a loss |
| §10 Collections | Invoice-grain aggregation (rule 2), ageing buckets, rank-blended risk score | Median **23d** late, **0.59%** bounced, **545M** open exposure |
| §11 Quality | Distribution analysis, band-position capability proxy, lot traversal (rule 7) | Lab fail rate **0.09%** — the verdict is near-useless; **62%** of lots sit at a spec-band edge |

Two processing notes that matter more than the numbers:

* **Cost basis is only 32% realised.** Any margin figure must be quoted with its `cost_source` mix,
  which is why that column travels on every spine row and the coverage table prints immediately above
  every margin result.
* **`Lab_Result` is a near-constant** (13,853 pass vs 12 fail). Model the four *continuous*
  measurements and their position inside the spec band, not the pass/fail flag.

### §12 · Complaint NLP — the section ordinary BI cannot reach
Pipeline: `normalize_fa` → TF-IDF (1–2 grams, Persian stopwords) → optional SVD to 64-d → clustering /
topics / retrieval / classification. Swapping `P["text_backend"]` to `sentence_transformers` changes
the encoder and nothing else, because every consumer is written against a generic `embed()`.

**Three traps this section is explicitly built to avoid** — each one produces an impressive but false
result if ignored:

1. **67% of complaint bodies are verbatim duplicates.** A naive "cosine > 0.75 against any earlier
   complaint" flags **87.5%** of rows as recurrences, which is noise. Scoping the comparison to the
   *same customer* and separating exact from near duplicates gives **45 genuine recurrences (8.7%)** —
   a usable churn watch-list.
2. **`Complaint_Title` is inside `text_raw`.** Training on title+body to predict the title scores
   macro-F1 **1.000**. Using the body alone still scores 0.995 because duplicate strings land on both
   sides of the CV split; a **group split on deduplicated body text gives 0.806** — the honest number,
   and still strong enough to auto-route intake.
3. **Prose-shaped columns that are not prose.** `Outcome_Text` (7 distinct values), `Analysis`
   (28 distinct over 130 rows) and `شرح کالا` (a concatenation of four existing columns) look like text
   and must be one-hot encoded or parsed, never embedded.

Other results: KMeans (k=8, silhouette 0.163) rediscovers the business taxonomy with **36.3% purity** —
the emergent themes (پرز/فیلامنت, شید رنگ, دوک/پالت, استحکام, مینگل) cut across the 45 curated titles.
Severity prediction from body text reaches 0.50 accuracy against a 0.43 majority baseline: weak, so
severity is only partly linguistic. **Time-to-resolution is flat across severity levels (23–25 days
median), and critical complaints have the *lowest* resolution rate (58.8%)** — severity is recorded but
is not driving priority.

### §13–§15 · CRM, offers, wallet share, R&D, market
* `Summary_Text` is **templated** — regex the slots (`فوریت`, `کد پیگیری`) before embedding; the
  embedding of the whole string mostly encodes the template.
* **`آفرها` is a price-elasticity experiment the business ran without noticing.** 2,500 quotes with
  base price, offered price, discount and outcome. Result: `corr(discount, win) = -0.018` —
  **discounting is not buying acceptance.** Margin is being given away for nothing.
* `سهم_سبد` covers **12 months only** (2021-07 … 2022-06) against sales running far longer. Never
  trend across the gap.
* Market `Price_Index` correlates **-0.545** contemporaneously with our realised ASP and weakens with
  lag — it is a concurrent descriptor, not a leading indicator.

### §16 · Customer 360 and churn
50 features per customer: RFM + credit + engagement + offers + wallet + complaints + NLP-derived
recurrence counts. The churn model reaches ROC-AUC 0.986 — **which is the label leaking**, since
recency-adjacent features define the target. It is printed as a descriptive ranking with that caveat
stated in the cell, and the deployable artefact is the transparent rank-blended
`value_at_risk` board instead.

Interestingly the top importances are `wallet_share` (0.227) and `asp` (0.204), not the obvious
recency proxies — customers with low share of wallet and atypical pricing lapse first.

### §17 · The column catalogue
Generated from metadata + measurements + hand-written overrides for the text columns. Exports to
`outputs/COLUMN_PROCESSING_CATALOG.xlsx`.

---

## 3. Column processing catalogue

### Distribution across all 189 source columns

| Processing class | Columns | Meaning |
|---|---:|---|
| `categorical-lowcard` | 44 | One-hot / target-encode |
| `identifier-join` | 42 | Keys — never features |
| `numeric-continuous` | 28 | Scale, winsorise, watch skew |
| `datetime` | 20 | Calendar expansion, deltas, recency |
| `as-of-control` | 16 | Point-in-time filter only |
| `constant-drop` | 15 | Single value — zero information |
| `categorical-highcard` | 11 | Frequency/target-encode, entity embeddings |
| `binary-flag` | 5 | Map to 0/1 |
| `text-templated-slotfill` | 3 | Regex the slot; embedding adds little |
| `numeric-count` | 2 | Ordinal/count, bucket |
| `text-freeform-NLP` | 2 | Full NLP pipeline |

### The columns that need NLP or embeddings

| Sheet | Column | Class | Processing | Generated columns |
|---|---|---|---|---|
| `شکایات` | `Complaint_Text` | **text-freeform-NLP** | normalize → TF-IDF / multilingual sentence embeddings → KMeans + NMF + cosine retrieval; severity & type classification | `cluster_id`, `topic_id`, `topic_strength`, `embedding[64]`, `prior_similarity`, `is_recurrence`, `says_repeat`, `predicted_severity` |
| `شکایات` | `Resolution_Text` | **text-freeform-NLP** | normalize → embeddings; summarisation; action-item extraction; stance (accepted vs refuted) | `resolution_embedding[64]`, `resolution_theme`, `contains_corrective_action` |
| `شکایات` | `Complaint_Title` | **label-taxonomy** | Supervision target, not input — 45 curated values | `title_label` |
| `تعاملات_CRM` | `Summary_Text` | **text-templated-slotfill** | Regex slots first (urgency, tracking code), embed the residual; intent classification | `urgency`, `tracking_code`, `intent`, `summary_embedding[64]` |
| `درخواست_توسعه` | `Requirement_Text` | **text-templated-slotfill** | Regex numeric slot + TF-IDF over the request phrase; topic model to validate `Request_Type` | `sample_kg`, `requirement_embedding[64]`, `requirement_topic` |
| `محصولات` | `شرح کالا` | **text-templated-slotfill** | Split on `/` — the four components already exist as columns | *(already decomposed)* |
| `درخواست_توسعه` | `Outcome_Text` | **categorical-lowcard** | 7 distinct values. **Do not embed.** | `outcome_class` |
| `سیگنال_بازار` | `Analysis` | **categorical-lowcard** | 28 distinct over 130 rows — fully templated | `market_trend_parsed` |

The last two are the important lesson: *prose-shaped is not the same as free text.* Check cardinality
before you reach for an encoder.

### Columns the notebook generates (24 total, exported to `outputs/91_generated_columns.csv`)

Highlights by layer:

* **spine** — `revenue`, `unit_cost`/`cost_source`, `gross`/`margin_pct`, `has_lab`,
  `has_complaint`/`n_complaints`, `month`/`quarter`
* **invoice** — `settle_ratio`, `open_amount`
* **customer** — `utilisation`, `collection_rate`, `risk_score`
* **lot** — `band_position`, `at_edge`, blast radius per `Hembaft_Lot_Key`
* **complaint** — normalised `text`, `cluster`, `topic`, `prior_similarity`,
  `prior_sim_same_customer`, `says_repeat`, `is_recurrence`, `resolution_days`
* **crm / offers / wallet / devreq** — `urgency`, `tracking_code`, `won`/`disc_decile`,
  `share`/`headroom`, `sample_kg`, `decision_days`
* **customer360** — RFM triplet, `is_churned`, `value_at_risk`

---

## 4. Data-quality findings, ranked by impact

| # | Finding | Impact | Where |
|---|---|---|---|
| 1 | **Temporal discontinuity** — ERP ends 2022-06, 52 complaint-traced lines stamped 2025–26 | Destroys any naive recency/churn measure (99% false churn rate) | §7 |
| 2 | **Realised cost covers only 32% of lines** | Margin on realised cost alone analyses a biased third of the business | §9 |
| 3 | **67% of complaint bodies are verbatim duplicates** | Inflates recurrence detection 10× and leaks across CV splits | §12 |
| 4 | **`Lab_Result` is 99.91% pass** | The flag carries almost no information; use the continuous measures | §11 |
| 5 | **3 documented columns absent** (`Source_Type`, `Channel`, `Priority`) | Breaks any pipeline coded from the metadata alone | §4 |
| 6 | **`سهم_سبد` covers 12 months, `آفرها`/`سیگنال_بازار` stop at 2022-06** | Cannot trend against the full sales history | §13, §15 |
| 7 | **Currency unit is never declared** (stated in the metadata caveats) | All money is scale-relative; keep one scale throughout | §8 |
| 8 | **Complaints concentrate in the recent tail** | "Complaints cause churn" is confounded by tenure — control for it | §12 |

Finding 8 deserves emphasis: complaining customers have **10× the mean revenue** and a *lower*
dormancy rate (22.5% vs 63.4%). That is not "complaints are good" — it is that only large, active,
long-tenured accounts ever bother to file one. Any causal claim here needs tenure controls.

---

## 5. Running it

```bash
uv pip install --python .venv/bin/python \
    pandas openpyxl matplotlib scikit-learn arabic-reshaper python-bidi ipywidgets
```

Open `main.ipynb`, edit the `P` dict in §1 (or use the ipywidgets panel in §1b), then
*Restart & Run All*. Artefacts land in `outputs/`: 23 CSVs, the catalogue workbook, and
`RUN_SUMMARY.txt` recording the exact parameters behind that run.

Parameters worth exploring first:

| Parameter | Try | To see |
|---|---|---|
| `as_of` | `"2021-06-30"` | The point-in-time view — how much of what you "know" was not yet visible |
| `cost_basis` | `"realized_only"` | How much the margin picture changes on the 32% that has real cost |
| `churn_inactivity_days` | 90 / 365 | How unstable the churn label is |
| `segments` | `["A"]` | Whether the top segment behaves differently on quality and collections |
| `text_backend` | `"sentence_transformers"` | Whether a real multilingual encoder beats TF-IDF on 520 short docs |
| `plot_lang` | `"en"` | Every chart title and axis label in English instead of Persian |
| `n_clusters` | 4 / 12 | Whether the complaint taxonomy is really 8 themes |
