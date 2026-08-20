# Manual review guide — `test_runs/`

Two different jobs live in this folder:

| Job | Who | What |
|---|---|---|
| **A. Smoke / regression** | Machine | Files `01`–`15` already ran. You only spot-check pass/fail. |
| **B. Golden label review** | **You** | The 11 ambiguous complaint labels (file `11`). This is the real human work. |

Start here: [`00_SUMMARY.md`](00_SUMMARY.md) for the run overview.  
Use **this file** when you review by hand (or copy the sheet into Excel/Google Sheets).

---

## A. What each test file checks

| # | File | Command | What it proves | You look for | Expected |
|---|---|---|---|---|---|
| 01 | `01_unit_tests.txt` | `pytest tests -q` | Code units + Phase-0 number regressions | last line: `117 passed` | ✅ exit 0 |
| 02 | `02_fixture.txt` | `nafisnakh fixture` | All 22 detectors fire on synthetic book | `22 از 22`, `رد شده: 0` | ✅ |
| 03 | `03_build_full.txt` | `nafisnakh build` | Metric layer on full book | ~526 customers, thousands of evidence | ✅ |
| 04 | `04_build_sample8.txt` | `nafisnakh build --sample 8` | Same path on tiny sample | builds without crash | ✅ |
| 05 | `05_calibrate.txt` | `nafisnakh calibrate` | Detectors in band @ **2021-06-30** | every row `status = ok` | ✅ |
| 06 | `06_signals.txt` | `nafisnakh signals` | Signal engine full book | ~1600+ signals | ✅ |
| 07 | `07_brief_sample12.txt` | `nafisnakh brief --sample 12` | End-to-end queue, 12 customers | actions > 0, **dropped = 0** | ✅ read actions |
| 08 | `08_brief_named.txt` | brief 3 named accounts | Named-account path | 3 actions, 0 dropped | ✅ |
| 09 | `09_brief_full.txt` | `nafisnakh brief --top 25` | Full queue | **25 actions, 0 dropped** | ✅ |
| 10 | `10_eval_golden.txt` | `nafisnakh eval` | Complaint scorer vs 40 golden | mechanism printed; **refuses to certify** without LLM | ⚠️ OK as-is |
| 11 | `11_labels_ambiguous.txt` | `nafisnakh label --only-ambiguous` | **Your review queue** | 11 rows with proposed labels | ℹ️ **you decide** |
| 12 | `12_models.txt` | model probe | Live backends | keys/quota — not product logic | ❌ infra |
| 13 | `13_report.txt` | `nafisnakh report` | HTML for sales manager | file written under `outputs/` | ✅ open HTML |
| 14 | `14_feedback.txt` | `nafisnakh feedback --show` | Feedback store | empty until you log decisions | ℹ️ empty OK |
| 15 | `15_asof_2021_12.txt` | `calibrate --as-of 2021-12-31` | Guard-rail at bad anchor | exit **1**, `cadence`/`volume` too_broad | ❌ **correct** |

### Quick pass checklist (copy into a sheet)

| Test | Pass? (Y/N) | Note |
|---|---|---|
| 01 unit 117 passed | | |
| 02 fixture 22/22, 0 dropped | | |
| 05 calibrate all `ok` @ 2021-06-30 | | |
| 07 / 08 / 09 brief: 0 dropped | | |
| 10 eval refuses certify (no model) | | |
| 13 HTML report opens | | |
| 15 exit 1 on purpose | | |
| 12 models (optional / keys) | | |

---

## B. What YOU must review (golden labels)

**Goal (PLAN Q8):** Claude proposed labels for 40 real complaints. You accept or correct them.  
Until `reviewed: true`, eval prints `بازبینی‌شده توسط کاربر : 0/40`.

**Priority:** the **11 ambiguous** rows (text fits more than one mechanism). File: `11_labels_ambiguous.txt`.  
**Source of truth to edit:** `nafisnakh/eval/golden_labels.yaml`

### Mechanism cheat sheet (10 codes)

| Code | Meaning (FA cue) |
|---|---|
| `M01_package_formation` | بدپیچی / تنشن پیچش / ریبونی / حلقه نامنظم |
| `M02_filament_damage` | فیلامنت پارگی / پرز / گره |
| `M03_mass_count_deviation` | نوسان دنیر / نمره اشتباه / اختلاف وزن |
| `M04_dye_shade` | شید رنگ |
| `M05_intermingling` | مینگل زیاد/کم |
| `M06_spin_finish` | روغن / لکه روغن |
| `M07_twist_ply` | تاب / لا / جدایش لا |
| `M08_tube_packaging` | دوک دست دوم / خرابی دوک |
| `M09_labelling_logistics` | لیبل / حمل / درجه C (عنوان لجستیکی) |
| `M10_mechanical_properties` | استحکام / ازدیاد طول / سیمی / زیر‌دست |

Also check (when present): `churn_threat`, `repeat_claim`, `escalation_level`, `attributed_fault`, `evidence_supplied`, `hembaft_mentioned`.

### How to review one row

1. Read **title** + **text** (not only the proposed label).
2. Pick the **dominant** mechanism (what the customer mostly complains about).
3. Compare with proposed `labels.mechanism`.
4. If wrong → edit that field in `golden_labels.yaml`.
5. Set `reviewed: true` for that row.
6. Optional: update `labeller_note_fa` with your reason.

```bash
# re-list what still needs you
.venv/bin/nafisnakh label --only-ambiguous --show 11

# after edits, re-score
.venv/bin/nafisnakh eval
```

---

## C. Review sheet — 11 ambiguous rows

Fill columns **Your mechanism**, **OK?**, **Your note**. Then mirror decisions into `golden_labels.yaml`.

| # | ID | Title | Proposed | Conflict (from note) | Your mechanism | OK? (Y/N/edit) | Your note |
|---|---|---|---|---|---|---|---|
| 1 | CMP-0003 | دوک دست دوم / خرابی دوک | `M01` | text: آسیب بوبین (M08) + ریبونی (M01) | | | |
| 2 | CMP-0007 | فیلامنت و پرز | `M02` | فیلامنت پارگی (M02) + پلیسه دوک (M08) | | | |
| 3 | CMP-0009 | بازشدن نخ درجه C | `M10` | متن خیلی مبهم؛ عنوان→M09، کارکرد→M10 | | | |
| 4 | CMP-0018 | نوسان دنیر | `M03` | «به حالت خام» → M03 یا M10؟ | | | |
| 5 | CMP-0021 | پیچش بسته/ تنشن پیچش | `M01` | متن پارگی انتها؛ ریشه ممکن M08 | | | |
| 6 | CMP-0024 | فیلامنت و پرز | `M01` | بدپیچی (M01) + فیلامنت (M02) | | | |
| 7 | CMP-0027 | پیچش بسته/ تنشن پیچش | `M01` | ظهور = پارگی (M02)، ریشه = تنشن (M01) | | | |
| 8 | CMP-0032 | فیلامنت و پرز | `M02` | M02 + پیچش نامنظم (M01) | | | |
| 9 | CMP-0033 | آسیب دیدگی در حمل | `M09` | **no descriptive text** — only hembaft IDs | | | |
| 10 | CMP-0037 | کم شدن لای نخ | `M03` | نمره ۲۵۰ vs ۵۰۰ (M03) + سیمی/پرز (M02/M10)؛ title suggests M07 | | | |
| 11 | CMP-0039 | بازشدن نخ درجه C | `M01` | ظاهر بهم‌ریخته؛ title map → M09 | | | |

Full text for each row is in `11_labels_ambiguous.txt` (or the matching block in `golden_labels.yaml`).

### After the sheet

1. Edit `nafisnakh/eval/golden_labels.yaml` for any **N / edit** rows.
2. Set `reviewed: true` on all 11 (and ideally all 40 when you finish the easy ones).
3. Run `nafisnakh eval` again — `بازبینی‌شده` should rise.
4. Real model quality still needs a live key (`12` / PLAN Q14); rules-only accuracy will stay ≈ title baseline.

---

## D. Optional: spot-check the action queue (not labels)

Open `07_brief_sample12.txt` (or `outputs/brief_2021-06-30.txt` / HTML from `13`) and for 2–3 actions ask:

1. Does the **why** match the named signals?
2. Does every number have an `[EV-…]` citation?
3. Is the quadrant (رشد / حفظ / اصلاح / کاهش) believable for that customer?

Validation already drops actions whose numbers are not in cited evidence — so **0 dropped** in 07–09 is the hard check. Human review here is product judgment, not a pass/fail gate.

---

## Reproduce

```bash
zsh scripts/run_tests.sh   # refreshes all files under test_runs/
```
