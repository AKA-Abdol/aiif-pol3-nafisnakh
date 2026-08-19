# نفیس نخ (Nafis Nakh) — Business & Domain Guide

**For:** `pol-3-nakhrisi` analytics project
**Compiled:** 2026-08-19
**Sources:** nafisnakh.com (company site), the project's own `DATASET.xlsx` / `METADATA.xlsx` / `PROCESSING.md`, and general polyester-filament industry references.

> **Evidence legend used throughout**
> **[SITE]** stated on nafisnakh.com · **[DATA]** observed directly in your DATASET.xlsx · **[IND]** standard industry knowledge, not company-specific · **[INFER]** my reconstruction, with the evidence given

---

## 1. What the company is

| | |
|---|---|
| Name | نفیس نخ / Nafis Nakh **[SITE]** |
| Founded | 18 June 2003 (۲۸ خرداد ۱۳۸۲) **[SITE]** |
| Headcount | 720+ **[SITE]** |
| Business | Manufacturer of **polyester filament yarn** (نخ فیلامنت پلی‌استر) **[SITE]** |
| Position | Sells B2B to *downstream* weavers, knitters, texturisers and carpet makers ("صنایع پایین‌دستی", "بافندگان") **[SITE]** |
| Product breadth claim | "DTY, FDY, POY, ATY, TFO, ایر تکسچره, نخ تابیده, آنتی‌باکتریال" **[SITE — legacy site tagline]** |

**The one-sentence business model:** melt-spin PET into continuous filament, sell it by the kilogram on bobbins/pallets to fabric producers, and compete on *consistency* (denier tolerance, dye shade, breakage rate) rather than price. Your dataset confirms this: `corr(discount, win) = -0.018` — discounting buys nothing, because the purchase decision is technical, not commercial.

**Critically for your project:** the folder is `pol-3-nakhrisi` (پلی ۳ / نخ‌ریسی = "Poly 3 / spinning"), and the complaint-linked records in your data are *entirely* POY (`PRD-POY-001…012`, `سالن POY`, `بسته‌بندی POY`). **You are working on the POY spinning plant, not the whole company.** **[DATA]**

---

## 2. The product families — what they actually make

Polyester filament yarn is a chain. Each stage is both a sellable product and the feedstock for the next. Nafis Nakh sells at *every* stage, which is why they have five categories on their site.

```
PTA + MEG
   │  polymerisation
   ▼
PET chip  (چیپس / گرانول پلی‌استر)
   │  melt spinning through a spinneret (رشته‌ساز / اسپینرت)
   ├──────────────► FDY   full draw + wind in one pass → sellable as-is
   │                       (نخ کاملاً کشیده‌شده)
   ▼
  POY  (نخ نیمه‌آرایش‌یافته)   ← ★ this plant ★
   │
   ├── false-twist texturing (تکسچرایزینگ تاب مجازی) ──► DTY (نخ تکسچره)
   ├── air-jet texturing (ایر تکسچره) ─────────────────► ATY
   └── (DTY or FDY) → TFO twisting (تابندگی) ──────────► TFY / نخ تابیده
```

### 2.1 The five families in detail

#### POY — Partially Oriented Yarn · نخ نیمه‌آرایش‌یافته
**[SITE]** category exists at `/product-category/poy/`.

Spun at ~3,000–3,500 m/min, the polymer chains are only *partially* oriented. It is deliberately unfinished: high residual elongation (~120–150%), low tenacity, and it will shrink and creep if used as-is. **[IND]**

- **Almost never woven directly.** It is an *intermediate* — 90%+ of world POY goes into texturising machines. **[IND]**
- Sold on **bobbins (بوبین)** wound on a paper/plastic **tube (دوک / سر دوک)**. Package weights in your data: **~10 kg for CW wind, ~20 kg for ACW wind.** **[DATA — resolution text]**
- Typical POY deniers: 80–600 den. Your un-anonymised SKUs span **120 to 750 den**. **[DATA]**
- Because the customer *processes* it further, POY complaints are overwhelmingly about **runnability**: does it break on the texturising machine, does the package unwind cleanly. That is exactly what your 45 complaint titles show.

#### DTY — Draw Textured Yarn · نخ تکسچره / نخ تاب مجازی
**[SITE]** category at `/product-category/dty/`; they have a technical article on it.

POY is simultaneously drawn and false-twist textured — heated above Tg, twisted by friction discs, cooled to set the crimp, then untwisted. The filaments keep a permanent zig-zag (کریمپ), giving bulk, stretch and a cotton-like hand. **[SITE — their own article]**

Their article gives the process stages verbatim: **گرمکن اول** (first heater) → **صفحات خنک‌کننده** (cooling plate) → **واحد تاب‌دهنده / دیسک اصطکاکی** (friction disc twist unit) → **گرمکن دوم** (second heater). **[SITE]**

Two commercial sub-types, both named in their article and in your complaint data: **[SITE]+[DATA]**
- **DTY استرچ (stretch)** — single-heater, high elasticity retained.
- **DTY ست (set)** — second heater engaged, elasticity killed, dimensionally stable. Used where the fabric must not pucker.

Also from their article, the **denier-to-application map they themselves publish**: **[SITE]**

| Denier band | Applications (their wording) |
|---|---|
| < 100 | shirts, t-shirts, sportswear, headscarves (روسری), socks, curtain, automotive textiles |
| 150–200 | dress fabric, hosiery, bedding, medical bandage, shoe upper |
| 200–400 | prayer rugs (جانماز), upholstery, curtain fabric, industrial textiles |
| 400–1600 | carpet warp/weft (تار و پود فرش), heavy industrial, filters |

#### FDY — Fully Drawn Yarn · نخ کاملاً کشیده‌شده
**[SITE]** category at `/product-category/fdy/`, described there as *"ماده اولیه برای تولید نخ تابیده"* (feedstock for twisted yarn).

Spun and drawn in one continuous pass — fully oriented, low elongation (~25–35%), high tenacity, **flat and lustrous** (no crimp). Used where you want a silk-like smooth surface: lining, satin, taffeta, and as the input to TFO twisting. **[IND]**

#### ATY — Air Textured Yarn · نخ ایرتکسچره
**[SITE]** category at `/product-category/aty/`.

Bulked by blasting the yarn with a turbulent **air jet (جت هوا)** while over-feeding it, so filaments form loops and entanglements on the surface. The result mimics **spun (staple) yarn** — matte, hairy, low sheen. Used for upholstery, curtain, and apparel that should not look synthetic. **[IND]**

Note the `Overfeed` term appearing in your complaint corpus — that is the ATY/DTY control parameter (how much more yarn is fed than taken up; it sets the loop density). **[DATA]**

#### TFY / TFO — Twisted Filament Yarn · نخ تابیده
**[SITE]** category at `/product-category/tfy/`.

Two or more ends are plied and twisted on a **Two-For-One twister**. Twist is measured in **TPM (tab dar meter / تاب در متر)**; direction is **S** or **Z**. Twist raises strength and changes hand ("زیردست"); high twist gives crepe effects. **[IND]**

This is why your complaint titles include **`جهت تاب اشتباه`** (wrong twist direction), **`نوسان تعداد تاب`** (twist-count variation), **`اختلاف تعداد لا`** (wrong ply count) and **`چند لا کنی / چند لا تابی`** — those are TFO-specific defects. **[DATA]**

#### Specialty / functional yarns
The legacy site advertises **آنتی‌باکتریال** (antibacterial) yarn. **[SITE]** Common companions in this industry are ضد UV, ضد آتش (FR), جاذب رطوبت (moisture-wicking), دوپ‌دای (dope-dyed / محلول‌رنگ). **[IND]**

---

## 3. How to read a Nafis Nakh product code

This is the single most valuable thing recovered from your data. Eleven product rows in `محصولات` escaped anonymisation and reveal the real SKU grammar: **[DATA]**

```
POY   150 / 72   BR    مستطیلی
 │     │    │     │        │
 │     │    │     │        └── cross-section of the filament (مقطع)
 │     │    │     └─────────── luster code (براقیت)
 │     │    └───────────────── filament count (تعداد فیلامنت)
 │     └────────────────────── nominal denier (دنیر / نمره)
 └──────────────────────────── product family
```

All eleven observed:

`POY 120/36 SD سه‌پر` · `POY 120/72 SD مستطیلی` · `POY 150/72 BR مستطیلی` · `POY 150/144 BR پلاس` · `POY 200/144 SBR پلاس` · `POY 200/288 SBR گرد` · `POY 250/288 SD گرد` · `POY 400/72 SBR مستطیلی` · `POY 500/144 SD پلاس` · `POY 600/288 BR گرد` · `POY 750/36 SBR سه‌پر`

### 3.1 Denier and the `/` notation — the thing to get right first

**Denier (دنیر)** = grams per 9,000 metres of yarn. It is a *linear density*, so **bigger denier = thicker yarn**. `150/72` means: the whole strand weighs 150 g per 9,000 m, and it is made of 72 individual filaments. **[IND]**

Two derived quantities you will want as features:

- **dpf — denier per filament** = `denier / filament_count`. This is the single most important handle quality: 150/72 → 2.08 dpf (normal), 200/288 → 0.69 dpf (**microfilament** — soft, peach-skin hand, but far more prone to پرز and فیلامنت‌پارگی). Your `تغییر تعداد فیلامنت` development requests are customers asking to move along this axis at constant denier. **[INFER — arithmetic + their own request taxonomy]**
- **dtex** = grams per 10,000 m = `denier × 10/9`. Your lab column `Tensile_Strength_cN_dtex` is in cN/dtex, so any strength normalisation must use dtex, not denier. **[DATA]**

**Trap:** "نمره" (count/number) is used loosely in this industry to mean denier. Your complaint titles `تلرانس نمره`, `خارج بودن نمره` and `نوسان دنیر` are all the *same* defect class — the yarn is not the weight it says it is. Merge them. **[DATA]+[INFER]**

### 3.2 Luster codes (براقیت)

| Code | Persian | Meaning | TiO₂ delustrant |
|---|---|---|---|
| **SBR** | سوپر براق | Super Bright | none |
| **BR** | براق | Bright | none / trace |
| **SD** | نیمه مات | Semi-Dull | ~0.3% |
| **FD** | فول دال | Full Dull | ~2% |

**[IND]** for the chemistry; **[SITE]** confirms SBR/BR/SD in the SKU names and Nafis Nakh has a dedicated product page **نخ فول دال** (Full Dull). Luster is set by titanium dioxide loaded into the melt; it is a *polymer* property, decided before spinning, and cannot be changed downstream. That is why it is a first-class product-master attribute in their ERP (`دسته بندی براقیت`) and why a luster mismatch is a scrap event, not a rework. **[INFER]**

### 3.3 Cross-section (مقطع)

The spinneret hole shape. It controls sheen, bulk, soil-hiding and hand: **[IND]**

| Persian in their SKU | English | Effect |
|---|---|---|
| **گرد** | round | baseline; highest packing density, glassy sheen |
| **سه‌پر** | trilobal | sparkle/silk-like glitter; the classic carpet & apparel profile |
| **مستطیلی** | rectangular / flat | flat ribbon-like reflection, cotton-ish |
| **پلاس** | cross / plus (+) | high bulk and covering power at low weight; wicking channels |

Your complaint title **`جداشدن مغزی و افکت`** (core/effect separation) belongs to this family — an "effect yarn" combines two different cross-sections or shrinkages and they are delaminating. **[DATA]+[INFER]**

### 3.4 The colour axis (گروه رنگ)

Filament yarn is sold in three commercial colour states: **[IND]**

- **خام / RW (raw white)** — undyed, the customer dyes the fabric afterwards. The bulk of volume.
- **دوپ‌دای / محلول‌رنگ (dope-dyed / spun-dyed)** — pigment added to the melt. Colour-fast and water-saving, but locked in at spinning.
- **مشکی (black)** — usually a dope-dyed sub-case, high volume, sold separately.

Your `شید رنگ` (36 complaints), `اختلاف شید بین لاها` and `شید رنگ / راه‌راهی` (barré / streaking) complaint titles are the classic *dyeing-uniformity* failure: the yarn dyed unevenly, producing visible stripes in the finished fabric. For RW yarn this is caused by variation in **draw ratio, oil pickup or filament tension** across positions — the yarn is chemically identical but takes up dye differently. **[IND]**

---

## 4. Decoding the anonymised dimensions in your data

Your `METADATA.xlsx` replaced the real labels with placeholders. Here is the reconstruction, with the confidence I would attach to each.

### 4.1 `گروه کالا` → Product_Family_01…06

**[DATA]** Observed sales facts:

| Placeholder | SKUs | Qty share | Sales lines | Median unit price | Median line qty | Denier-band mix | Years present |
|---|---:|---:|---:|---:|---:|---|---|
| Product_Family_04 | 197 | 38.8% | 13,144 | 105.8 | 87 | 70% band-04 | SY01–04 |
| Product_Family_03 | 296 | 32.4% | 21,752 | 131.4 | 39 | 52% band-04, 23% band-01 | **SY01–06** |
| Product_Family_05 | 84 | 16.3% | 8,240 | **212.5** | 178 | 56% band-03 | SY01–04 |
| Product_Family_02 | 13 | 6.5% | 6,376 | 139.8 | 116 | **99% band-03** | SY01–04 |
| Product_Family_06 | 4 | 4.0% | **241** | **78.7** | **3,822** | — | SY01–04 |
| Product_Family_01 | 51 | 1.8% | 3,161 | 153.1 | 22 | 44% band-04 | SY01–04 |

**Family_03 = POY. High confidence.** Three independent proofs: (a) all eleven un-anonymised SKUs are `POY …` and all carry Family_03; (b) it is the *only* family with SY05/SY06 rows — which is precisely the 2025–26 complaint-traced extract, and that extract's product keys are literally `PRD-POY-001…012`; (c) the complaint and resolution prose for those rows talks about `سالن POY`, `بسته‌بندی POY`, `تکسچره ۸ دوک POY`. **[DATA]**

For the rest, ranked by evidence: **[INFER — treat as hypotheses to confirm against the un-anonymised master]**

- **Family_04 → DTY.** Largest tonnage, lowest median price of the yarn families, huge SKU count, and dominated by the heavy denier band (70% in band-04) — matches carpet/upholstery DTY, which is the volume product in Iran.
- **Family_05 → TFY (twisted) or ATY.** Highest price per unit by 60%, few SKUs, large order lines. Value-added conversion.
- **Family_02 → FDY.** Only 13 SKUs but 6,376 lines and 99% concentrated in a *single* denier band with 90% one luster class — the signature of a narrow, standardised, repeat-ordered range. FDY ranges are typically far narrower than DTY.
- **Family_01 → specialty / small-lot.** Tiny median line size (22 units), 51 SKUs, high price. Antibacterial / functional / trial products.
- **Family_06 → not filament yarn at all.** Four SKUs, 241 lines, median line **3,822 units**, cheapest price, and it is the only family where `براقیت = Luster_Unknown` (82%) and `رنگ = Color_Class_01` (82%). Luster and colour are meaningless for it. Most likely **PET chip / گرانول**, **ضایعات (waste)** or bulk **درجه‌دو (off-grade)** sold by the tonne.

**How to verify in one query** once you have the real master: `SELECT DISTINCT گروه کالا FROM محصولات` and check the ordering of median `قیمت فی فروش` — POY < DTY < FDY < ATY < TFY is the near-universal value ladder. **[IND]**

### 4.2 The other dimensions

| Placeholder | Real meaning | Reconstruction |
|---|---|---|
| `زیرگروه کالا` = Denier_Subgroup_01…05 | **Denier bands** | Their own DTY article publishes the bands: <100, 100–200, 200–400, 400–1600 (+ a micro/heavy tail). Band-04 is 47% of all volume → that is the heavy carpet/upholstery band. Ordinal — encode it as ordered, never one-hot. **[SITE]+[INFER]** |
| `دسته بندی براقیت` = Luster_Class_01/02 | **SD vs BR** (the two dominant) with SBR/FD folded into GENERALIZED. Class_02 = 51% of volume, Class_01 = 35%. | Semi-Dull is normally the volume grade → **Class_02 ≈ SD, Class_01 ≈ BR**, moderate confidence. **[INFER]** |
| `گروه رنگ` = Color_Class_01/02/03 | **RW / dope-dyed / black.** Class_03 = 52%, Class_02 = 35%, Class_01 = 3.5%. | Class_03 or Class_02 is raw white. Class_01 is rare and is the *only* colour Family_06 uses → Class_01 is the "no colour / N-A" bucket. **[INFER]** |
| `Quality_Class_ID` 01–08 | **درجه — commercial grade.** | Filament yarn is universally graded **AA / A / B / C / …** by visual + lab inspection, with off-grade sold at a discount. Your complaint titles `بازشدن نخ درجه C`, `لیبل درجه`, `تعداد بالای درجات پارگی` confirm this vocabulary is in use. This is an **ordinal** variable and probably the strongest single price driver you have. **[DATA]+[IND]** |
| `Location_ID` LOC-001…016 | استان/شهر of the customer | 16 values ≈ Iranian provinces with textile clusters (Qazvin, Isfahan, Yazd, Mashhad, Tehran, Kashan…). **[INFER]** |

---

## 5. The production & traceability vocabulary — this is where your data lives

### 5.1 The physical package hierarchy

```
فیلامنت (filament)  — one continuous strand from one spinneret hole
   └─ نخ / لا (yarn / ply)   — the bundle of filaments = one "end"
        └─ بوبین (bobbin)     — the wound package of yarn, ~10 kg (CW) / ~20 kg (ACW)
             └─ دوک (tube/spool)  — the paper or plastic core the bobbin is wound on
                  └─ پالت (pallet) — the shipping unit; separated by لایی (interleaf sheets)
```

**`دوک` is the term you asked about, and it is genuinely ambiguous in their data.** Strictly it is the *tube/spool* — the empty core. Colloquially on the shop floor it means the whole wound package (they say "تکسچره ۸ دوک POY"). Your complaint titles use it both ways: **[DATA]**

- `خرابی دوک` / `دوک دست دوم` — the **tube** is damaged or reused. Resolution text repeatedly says *"سر دوک ارسال گردید"* (we shipped replacement tube ends), which only makes sense for the physical core.
- `بدپیچی / سفتی بسته` — the **winding** on the package is bad.

**Treat `دوک` as tube-when-paired-with-خرابی/دست‌دوم/سر, and package-otherwise.** **[INFER]**

`سر دوک` = the tube's end flange/cap. `پلیسه` = the burr or flash on a damaged tube edge — this is the specific defect that snags yarn and is the #1 complaint driver in their `دوک` cluster. **[DATA]**

### 5.2 Winding and package defects — decoded

Your complaint taxonomy is almost entirely a **package-formation** taxonomy. This makes sense: POY's customer runs it at 800+ m/min on a texturiser, so *how the package unwinds* matters more than the polymer.

| Their term | What it physically is |
|---|---|
| **بدپیچی** | bad winding — the generic parent term |
| **ریبونی شدن** (ribboning) | successive wraps land on top of each other instead of at an angle, building a hard ridge that later collapses. Named verbatim in a complaint: *"حالت پیچش نخ روی بوبین زاویه‌دار نبوده و اصطلاحاً ریبونی شده"* |
| **سفتی بسته / تنشن پیچش** | package wound too tight — won't unwind, or crushes the tube |
| **بازشدن لا / جدایش / کم شدن لای نخ** | the plies separate, or one end is missing — the yarn was supposed to be N-ply and isn't |
| **حلقه‌های نامنظم / پرز و حلقه‌های بلند** | loose loops standing off the package surface — will snag |
| **گره و اسنارل** (snarl) | the yarn kinks back on itself from residual torque |
| **ریزش نخ** | the wound package sloughs off the edge |
| **الصاق لیبل اشتباه / لیبل پایه نخ اشتباه** | mislabelled package — the grade or lot on the label doesn't match the contents. Pure logistics defect, but 26 complaints. |

**[DATA]** — all quoted from `Complaint_Title` and `Complaint_Text`.

### 5.3 Yarn-quality defects — decoded

| Their term | What it is | Root cause **[IND]** |
|---|---|---|
| **پرز** (fuzz/hairiness) | broken filaments protruding from the strand | rough guide, worn ceramic, over-draw, low oil |
| **فیلامنت پارگی** | individual filaments broken inside the bundle | spinneret contamination, quench turbulence |
| **سیمی بودن** ("wiry") | a stiff, wire-like section | localised over-drawing / cooling fault |
| **مینگل** (intermingling/interlace) | the deliberate air-jet knots that hold filaments together. Measured in **nips/metre**. Both `مینگل بیشتر از حد` and `مینگل کمتر از حد` are complaints — it is a **two-sided spec**. Too little and the bundle splits; too much and the fabric shows pinholes. | interlace-jet air pressure ("فشار بادجت" in their resolution text) |
| **روغن نامتوازن / آلودگی، لکه روغن** | **spin finish (روغن نخ)** — the antistatic/lubricant emulsion applied at spinning. Your lab column `Oil_Pickup_Pct` measures it. Uneven = static, breakage, and dye streaks. | oiling-roller wear, emulsion concentration drift |
| **استحکام پایین / پارگی** | low tenacity | measured by `Tensile_Strength_cN_dtex` |
| **اختلاف ازدیاد طول** | elongation variation | measured by `Elongation_Pct`; driven by **draw ratio** |
| **کریمپ / حجم ناهمگون** | crimp or bulk not uniform (DTY/ATY) | heater temperature, D/Y ratio |
| **جمع‌شدگی / شرینکیج** | boiling-water shrinkage out of spec | heat-setting |
| **تنشن و تاب مجازی** | tension / false-twist irregularity | disc wear, threadline tension |
| **نوسان دنیر / CV** | mass irregularity along the strand | measured by `Evenness_CV_Pct` (Uster CV%) |
| **زیردست** (hand feel) | subjective fabric handle | the ultimate customer judgement; not measurable in the lab |

### 5.4 Process vocabulary appearing in their resolution text **[DATA]**

`سالن POY` (POY hall) · `سرپرست سالن` (hall supervisor) · `پوزیشن` (spinning position — one spinneret/winder station; defects are traced to a position) · `وایندر` (winder) · `CW / ACW` (clockwise / anticlockwise wind — different package weights and machines) · `ستینگ` (machine setting recipe) · `نخ‌کشی` (string-up — threading the machine) · `گاید` (yarn guide) · `هیتر` (heater) · `Draw Ratio` · `Overfeed` · `Tenacity` · `فشار بادجت` (air-jet pressure) · `هوای تغذیه` (feed air) · `دانسیته` · `کالیبراسیون` · `استروبوسکوپ` (strobe — used to visually inspect a running package) · `راندمان` (efficiency) · `درجات` (off-grade material) · `تفکیک / جداسازی` (segregation of defective packages) · `اقدام اصلاحی` (corrective action, CAPA) · `کمیته S&OP`.

### 5.5 همبافت (Hembaft) — the concept that will bite you

**`همبافت` literally means "co-woven".** In their ERP it is a **production campaign / co-weavable batch identifier** — a 10-digit number like `1173910000`, `1215810000`. **[DATA]**

The industrial meaning: a weaver cannot mix yarn from different production runs in one fabric, because tiny differences in draw or oil pickup produce a **visible stripe (راه‌راهی / barré)**. So the producer certifies a set of packages as *interchangeable within one fabric* and stamps them with the same همبافت number. Customers order and complain **by همبافت**. **[INFER — but strongly supported: complaint texts say "در همبافت 1178710000 …", "نخ‌های POY با همبافت 1215810000 به تعداد ۱۶ پالت"]**

**This is why your metadata has integration rule 7: `Hembaft_ID ≠ Lot_ID`.** They are different granularities of the same physical material:

- **`Lot_ID`** = the production lot (19,354 distinct) — a manufacturing batch.
- **`Hembaft_ID`** = the shade/campaign group (48 distinct) — spans lots, and is the unit the *customer* recognises.
- **`Hembaft_Lot_Key`** (52) = the bridge. Join only through it.

**Analytical consequence:** the blast radius of a quality problem is the **همبافت**, not the lot. One bad همبافت can invalidate every pallet shipped to every customer under that number. Your §11 "blast radius" traversal is the right shape — and `Hembaft_ID` is the correct grouping key for any quality-incident cost model.

The number itself appears to be sequential and time-ordered (1173910000 → 2025-03-25, later numbers → later dates), so **the first 5–6 digits are usable as a monotone production-sequence feature.** **[INFER]**

---

## 6. Commercial vocabulary

### 6.1 The sales & collections chain **[DATA]**

| Persian | Meaning | Sheet |
|---|---|---|
| فاکتور / شماره فاکتور | invoice / invoice number | `فاکتورها` (14,423) |
| ردیف فاکتور | invoice line number | `فروش` |
| مقدار | quantity — **in kg** (yarn is always sold by weight) | `فروش` |
| قیمت فی فروش | unit selling price (per kg) | `فروش` |
| مبلغ کل | line total | `فروش` |
| مقدار برگشتی / مبلغ برگشتی | returned quantity / credit value | `اجزای_هزینه_تحقق`, `اتصال_شکایت` |
| وصول | **collection** — a cash/cheque receipt event | `وصول` (15,652) |
| تاریخ سررسید | due date | `وصول` |
| روز تأخیر | days late | `وصول` |
| چک برگشتی | **bounced cheque** — the key Iranian credit-risk signal | `وصول` |
| نوع پرداخت | payment type: `cash_or_prepaid` / `short_term` / `long_term` | `فروش` |

> **The invoice-grain trap, restated:** a sales line and a collection event both hang off an invoice but at different grains. `فروش ⋈ وصول` directly multiplies revenue by the number of collection events. Always aggregate `وصول` to invoice level first. Your metadata makes this integration rule #2 for a reason.

### 6.2 CRM and commercial process **[DATA]**

`Interaction_Type` — the seven things a rep actually talks about, with observed frequency:
پیگیری سفارش (840) · قیمت و تخفیف (734) · برنامه خرید (617) · وصول مطالبات (568) · کیفیت محصول (549) · خدمات فنی (441) · نمونه محصول (435)

`Next_Action` — پیگیری تلفنی · بازدید فنی · ارسال نمونه · جلسه قیمت · بدون اقدام

`Offer_Type` — **قیمتی** (price discount) · **حجمی** (volume tier) · **مدت‌دار** (extended payment terms). Note the third: in Iranian B2B, *credit period is a price*. A `مدت‌دار` offer is a financing concession, and comparing its `Offer_Discount_Pct` to a `قیمتی` one on the same scale is an apples-to-oranges error your margin model should avoid. **[INFER]**

`Offer_Reason` — رقابت قیمتی · حفظ مشتری کلیدی · افزایش سهم از سبد · افزایش حجم سفارش · تسویه سریع · معرفی محصول جدید · آزمون محصول

`سهم سبد` = **share of wallet** — their estimate of what fraction of a customer's total yarn purchasing they capture (`Nafis_Purchase / Estimated_Total_Purchase`). Your §16 found this is the *top* churn predictor (importance 0.227), ahead of every recency proxy. That is the real commercial insight in this dataset: **customers leave when Nafis is a minor supplier, not when they stop buying.**

### 6.3 R&D funnel vocabulary **[DATA]**

`Request_Type` — the six things customers ask them to change, which is a direct map of the product's tunable axes:

| Request | The axis it moves |
|---|---|
| تغییر دنیر | linear density |
| تغییر تعداد فیلامنت | dpf → hand and softness |
| بهبود استحکام | tenacity → runnability at speed |
| کاهش پرز | hairiness → fabric appearance |
| بهبود شید رنگ | dye uniformity |
| بسته‌بندی اختصاصی | package/pallet format for the customer's line |

`Status`: نمونه تأیید / درحال توسعه / درحال بررسی / **فنی رد** (technically rejected).
`Owner_Unit`: تحقیق‌وتوسعه (R&D) / کنترل کیفیت (QC) / برنامه‌ریزی تولید (production planning).

---

## 7. Lab measurements — units and traps **[DATA]**

`کیفیت_لات` carries four continuous measurements. **The stored units are not what the column names say:**

| Column | Stored range | Actual meaning | Trap |
|---|---|---|---|
| `Tensile_Strength_cN_dtex` | 2.80 – 4.99 | **cN/dtex** — correct as named. This span covers DTY/FDY territory; **true POY tenacity is ~2.0–2.5**. | Normalise by dtex, not denier |
| `Elongation_Pct` | 0.180 – 0.349 | a **fraction**, i.e. 18.0% – 34.9% | Despite `_Pct`, multiply by 100 before reporting. Note: **real POY elongation is ~120–150%** — 18–35% is FDY/DTY territory, further evidence these values are generated rather than measured |
| `Evenness_CV_Pct` | 0.0080 – 0.0239 | a **fraction**, i.e. CV 0.80% – 2.39% (Uster CV%) | same |
| `Oil_Pickup_Pct` | 0.0035 – 0.0124 | a **fraction**, i.e. 0.35% – 1.24% spin finish | same. Typical POY target is ~0.8–1.2% |

All four are near-uniform between hard min/max walls, which is why **62% of lots sit at a spec-band edge** and why `Lab_Result` is 99.91% `قبول` — the pass/fail flag carries almost no signal. Model the **band position** of the continuous values, as your notebook already does.

**Domain note on why this matters commercially:** a lot can pass every lab test and still generate a complaint, because the defects customers actually report (`بدپیچی`, `پلیسه سر دوک`, `ریبونی`, `مینگل`, `شید`) are **package and process** defects that the four-measurement lab panel does not test for at all. That is the honest explanation for your finding that lab data barely predicts complaints — it is not a data problem, it is a **measurement-coverage** problem. Worth stating explicitly in your writeup.

---

## 8. Quick-reference glossary (FA → EN)

**Materials & products**
نخ yarn · نخ فیلامنت filament yarn · الیاف fibre · پلی‌استر polyester (PET) · چیپس / گرانول PET chip · نخ نیمه‌آرایش‌یافته POY · نخ کاملاً کشیده‌شده FDY · نخ تکسچره DTY · نخ ایرتکسچره ATY · نخ تابیده TFY/TFO · نخ خام raw white · دوپ‌دای / محلول‌رنگ dope-dyed · آنتی‌باکتریال antibacterial

**Measurement**
دنیر denier (g/9000 m) · دسی‌تکس dtex (g/10000 m) · نمره count · تعداد فیلامنت filament count · استحکام tenacity · ازدیاد طول elongation · یکنواختی / CV evenness · جمع‌شدگی / شرینکیج shrinkage · تاب twist · تاب در متر TPM · لا ply/end · مینگل intermingling · کریمپ crimp · براقیت luster · مقطع cross-section

**Package & logistics**
بوبین bobbin · دوک tube/spool · سر دوک tube end · پالت pallet · لایی interleaf · بسته‌بندی packaging · لیبل label · درجه grade · درجات off-grade · همبافت production campaign / co-weavable batch · لات lot · وزن بسته package weight

**Process**
نخ‌ریسی spinning · ذوب‌ریسی melt spinning · رشته‌ساز / اسپینرت spinneret · کشش drawing · نسبت کشش draw ratio · تکسچرایزینگ texturing · تاب مجازی false twist · گرمکن heater · دیسک اصطکاکی friction disc · وایندر winder · پوزیشن spinning position · سالن production hall · ستینگ machine setting · نخ‌کشی string-up · گاید guide · جت هوا air jet · اورفید overfeed · روغن نخ spin finish · راندمان efficiency

**Defects**
پرز fuzz/hairiness · فیلامنت پارگی filament breakage · سیمی wiry · بدپیچی bad winding · ریبونی ribboning · اسنارل snarl · گره knot · شید رنگ shade · راه‌راهی barré/streaking · بازشدن لا ply separation · پلیسه burr · نوسان دنیر denier variation · تلرانس نمره count tolerance · زیردست hand feel

**Commercial**
فاکتور invoice · وصول collection · سررسید due date · چک برگشتی bounced cheque · مطالبات receivables · تخفیف discount · آفر / پیشنهاد offer · سهم سبد share of wallet · شکایت complaint · اقدام اصلاحی corrective action · صنایع پایین‌دستی downstream industries · بافنده weaver

---

## 9. Recommendations for your project

1. **Reframe the scope in your writeup.** This is POY-plant data with a company-wide sales ledger attached. Say so — it changes how the complaint findings generalise.
2. **Build `dpf` as a feature** the moment you have the real product master. `denier / filament_count` will almost certainly out-predict either component alone for hairiness and breakage complaints.
3. **Collapse the 45 complaint titles into ~8 physical mechanisms** — package formation, filament damage, mass/count deviation, dye/shade, intermingling, spin finish, twist/ply, logistics/labelling. Your KMeans found 36.3% purity against 45 labels because the 45 are *near-synonyms*, not distinct classes. A hand-built mapping to 8 will beat the clusters and beat the raw taxonomy.
4. **Use `Hembaft_ID` as the quality blast-radius key**, and as an ordinal production-sequence feature.
5. **Treat `Quality_Class_ID` as ordinal, not nominal.** It is a commercial grade (AA/A/B/C…), and it is very likely the strongest price driver in your margin model. One-hot encoding throws that away.
6. **Fix the `_Pct` columns** (×100) before any figure goes in front of a business reader — an elongation of "0.26%" will be read as a data error and cost you credibility.
7. **Name the measurement gap.** The lab panel tests polymer properties; the customers complain about package properties. That is a concrete, actionable recommendation to the business, and it is better than any model you could fit.

---

## Sources

- [نفیس نخ — English site](https://nafisnakh.com/en) — company profile, founding date, headcount, product positioning
- [DTY یا نخ‌های تکسچره تاب مجازی — Nafis Nakh](https://nafisnakh.com/dty-or-virtually-twisted-textured-yarns/) — their own DTY process description, denier/application table, stretch vs set
- [انواع نخ و طبقه‌بندی آن — Nafis Nakh](https://nafisnakh.com/انواع-نخ/) — their yarn classification: staple vs filament, S/Z twist, twist levels
- [POY نخ نیمه آرایش‌یافته — Nafis Nakh](https://nafisnakh.com/product-category/poy/)
- [DTY نخ تکسچره — Nafis Nakh](https://nafisnakh.com/product-category/dty/)
- [FDY نخ کاملاً کشیده‌شده — Nafis Nakh](https://nafisnakh.com/product-category/fdy/)
- [ATY نخ ایرتکسچره — Nafis Nakh](https://nafisnakh.com/product-category/aty/)
- [TFY نخ تابیده — Nafis Nakh](https://nafisnakh.com/product-category/tfy/)
- [نخ فول دال — Nafis Nakh](https://nafisnakh.com/product/نخ-فول-دال/)
- [تولیدکننده انواع نخ‌های DTY, FDY, POY, ATY, TFO — Nafis Nakh (legacy site)](http://www.nafisnakh.com/Pages.aspx?id=HR)
- [نخ فیلامنت تابیده (Twisted/TFO) — Mr Yarn](https://mr-yarn.com/en/twisted-or-tfo-yarn/) — TFO process, TPM and denier ranges
- Project files: `DATASET.xlsx`, `METADATA.xlsx`, `PROCESSING.md`
