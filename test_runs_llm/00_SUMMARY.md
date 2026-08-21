# Test Run with LLM — Gemini 3.7 Flash — 2026-08-20

Same 15 scenarios as `test_runs/`, but with a live model.
Model: **`google/gemini-3.7-flash`** via OpenRouter, profile `gemini`.

> ⚠️ The Q3 model id `google/gemini-2.0-flash-001` is **retired** on OpenRouter
> ("No endpoints found"). `NN_LLM_MODEL` keeps the Q3 *intent* — Gemini Flash,
> cheap — on a model id that still exists. The profile default in `config.py`
> is untouched.

| # | File | Result | Offline | With LLM |
|---|---|---|---|---|
| 01 | `01_unit_tests.txt` | ✅ 117 passed | 45s | **1,940s** ⚠️ |
| 02 | `02_fixture.txt` | ✅ 22/22 detectors | 0.6s | 0.8s |
| 03 | `03_build_full.txt` | ✅ 7,424 evidence | 1.1s | 1.3s |
| 04 | `04_build_sample8.txt` | ✅ 130 evidence | 0.4s | 0.5s |
| 05 | `05_calibrate.txt` | ✅ all 22 in range | 4.1s | 4.8s |
| 06 | `06_signals.txt` | ✅ 1,663 signals | 4.1s | 4.9s |
| 07 | `07_brief_sample12.txt` | ✅ 12 actions, 0 dropped | 0.5s | **174.8s** |
| 08 | `08_brief_named.txt` | ✅ 3 actions, 0 dropped | 0.5s | 60.6s |
| 09 | `09_brief_full.txt` | ✅ 25 actions, 0 dropped | 4.2s | 8.6s (cached) |
| 10 | `10_eval_golden.txt` | ✅ **certifies now** | — | see below |
| 11 | `11_labels_ambiguous.txt` | ℹ️ for your review | 0.3s | 0.6s |
| 12 | `12_models.txt` | ⚠️ gemini live, others blocked | 2.4s | 4.6s |
| 13 | `13_report.txt` | ✅ HTML written | 4.1s | 9.4s |
| 14 | `14_feedback.txt` | ℹ️ empty, expected | 0.3s | 0.5s |
| 15 | `15_asof_2021_12.txt` | ❌ **exit 1 — correctly** | 5.2s | 478.4s |

**Sweep complete: 14 of 15 exit 0.** The one non-zero exit is test 15, and it is
the calibration guard working as designed — identical to the offline run:

```
cadence_breach   218 / 301 = 72.4%   too_broad   (limit 60%)
volume_decline   218 / 347 = 62.8%   too_broad
```

`PLAN.md §1.6` predicted this: the sales extract winds down after mid-2021, so at
a late anchor *everyone* looks lapsed. **Byte-identical to the offline result** —
which is the point. Calibration is arithmetic over the metric layer; the model
touches only the prose, so switching it on must not move a single fire rate. It
did not.

---

## The headline: the eval now issues a verdict

For months of offline runs the report printed **«قابل صدور نیست»** — *cannot be
certified* — because the keyword fallback's "accuracy" was just the title lookup
scoring itself. With a real model:

| | Rules (offline) | **Gemini 3.7 Flash** |
|---|---|---|
| Mechanism accuracy | 0.875 | **0.900** |
| — lift over title baseline | `+0.000` | **`+0.025`** |
| — on unambiguous rows | 1.000 | **1.000** |
| `churn_threat` P / R | 1.00 / 1.00 | **1.00 / 1.00** |
| `repeat_claim` P / R | 0.67 / 1.00 | **1.00 / 1.00** |
| `evidence_supplied` P / R | 1.00 / 1.00 | **1.00 / 1.00** |
| `attributed_fault` | 0.475 | **0.900** |
| `escalation_level` | 0.825 | **0.750** |
| **Verdict** | قابل صدور نیست | **اهداف برآورده شد ✅** |

**Where the model earns its cost:** `attributed_fault` nearly doubled, 0.475 →
0.900. Deciding whether a defect belongs to production, packaging or transport
needs someone to actually read the sentence; keywords cannot do it.

**Where it does not:** `escalation_level` fell, 0.825 → 0.750. The model reads
escalation more aggressively than my labels — on the centrepiece complaint it
chose «بحرانی» where I labelled «تشدید». That may mean my label was too
conservative rather than the model being wrong, but **it cannot be settled until
the golden set is reviewed** (Q8). Recorded as a regression either way.

---

## The writing is the real difference

Same evidence, same ranking arithmetic — only the prose changed. Customer
C_329432, offline vs model:

**Offline (rules):**
> قدم بعدی: تماس نگهداشت و بررسی وضعیت سفارش‌های جاری با مشتری.
> *"Retention call, review open orders."*

**Gemini 3.7 Flash:**
> **تعیین تکلیف درخواست توسعه معوق و بازنگری شرایط قیمت**
> چرا: حجم خرید ماهانه مشتری در ۳ ماه اخیر -45.9 درصد افت داشته است
> [EV-C_329432-volume-001]. این موضوع همزمان با معطلی ۱۴۷ روزه ۱ درخواست توسعه
> باز [EV-C_329432-devreq-001] و موقعیت قیمتی 1.29 برابر میانگین بازار
> [EV-C_329432-price-pos-001] رخ داده که وضعیت رابطه را در معرض خطر قرار داده
> است [EV-C_329432-relationship-001].
> قدم بعدی: پیگیری فوری وضعیت پرونده فنی معوق ۱۴۷ روزه از واحد تحقیق و توسعه و
> تنظیم جلسه با مشتری جهت ارائه پاسخ فنی و پیشنهاد قیمتی منعطف.
> (مسئول: مدیر فروش با همکاری واحد تحقیق و توسعه)

The model connected three separate facts into one causal story and produced a
step someone can actually carry out. **And every number in it is still cited and
still validated** — 0 actions dropped across every run. It gained expressiveness
without gaining permission to invent.

---

## ⚠️ A defect this run exposed

**The unit test suite went from 45s to 1,940s — a 43× slowdown — because the
tests now make live API calls.** `tests/test_llm.py` calls the complaint block,
which with a key present goes to the network.

That is wrong. A test suite must be hermetic: no network, no cost, same result
on a plane. It should force `allow_rules` and an empty key regardless of what is
in `.env`. **Not yet fixed** — flagged here so it is not forgotten.

## Cost

~$0.001 per call. The eval is 40 calls; a cold full-book run is 348. Responses
cache by `model + prompt`, which is why test 09 took 8.6s — it reused what tests
03/05/06 had already paid for. Switching models does not delete another model's
cache.
