# Test Run — 2026-08-20

15 scenarios, each captured to its own file in this folder. Every command ran
**offline**; no API key was used and no model was called.

| # | File | What it tests | Result |
|---|---|---|---|
| 01 | `01_unit_tests.txt` | Unit + regression suite | ✅ **117 passed** in 45s |
| 02 | `02_fixture.txt` | Golden fixture, 16 synthetic customers | ✅ **22/22 detectors**, 0 dropped |
| 03 | `03_build_full.txt` | Metric layer, full book | ✅ 526 customers, **7,424 evidence** |
| 04 | `04_build_sample8.txt` | Metric layer, 8 customers | ✅ 433 lines, 130 evidence |
| 05 | `05_calibrate.txt` | Detector calibration @ 2021-06-30 | ✅ **all 22 in range** |
| 06 | `06_signals.txt` | Signal engine, full book | ✅ **1,663 signals**, 518 customers |
| 07 | `07_brief_sample12.txt` | Full pipeline, 12 real customers | ✅ 12 actions, 0 dropped |
| 08 | `08_brief_named.txt` | Full pipeline, 3 named accounts | ✅ 3 actions, 0 dropped |
| 09 | `09_brief_full.txt` | Full pipeline, full book | ✅ **25 actions, 0 dropped** |
| 10 | `10_eval_golden.txt` | Complaint block vs 40 golden | ⚠️ runs, **refuses to certify** (no model) |
| 11 | `11_labels_ambiguous.txt` | The 11 labels needing your review | ℹ️ output for you |
| 12 | `12_models.txt` | Live probe of all 4 model backends | ❌ **none answer** — provider-side |
| 13 | `13_report.txt` | Sales-manager HTML artifact | ✅ written, 64 KB |
| 14 | `14_feedback.txt` | Feedback loop state | ℹ️ empty, as expected |
| 15 | `15_asof_2021_12.txt` | Calibration at a **different anchor** | ❌ **exit 1 — correctly** |

---

## The three results worth reading

### 15 — the only non-zero exit, and it is the tool working

At `as_of = 2021-12-31` two detectors break their ceiling:

```
cadence_breach   218 / 301 fired = 72.4%   too_broad   (limit 60%)
volume_decline   218 / 347 fired = 62.8%   too_broad
```

This is **not a regression.** `PLAN.md §1.6` predicted it: the sales extract winds
down after mid-2021, so at a late anchor *everyone* looks lapsed. The plan's own
table says 224/301 = 74% at this date; we measured 72.4%. Consistent.

The calibration command is designed to exit non-zero when a detector leaves its
band, so this is the guard-rail firing on purpose. **It also confirms 2021-06-30 is
the right anchor** — at that date all 22 detectors sit in range (see `05`).

### 12 — no model backend answers

```
gemini              no key supplied
agentrouter         401 unauthorized_client_error   (provider blocks all clients)
agentrouter-claude  401 unauthorized_client_error   (same)
avalai              429 insufficient_quota          (needs credit; key works)
```

AvalAI is the closest: it authenticates and lists 385 models. It needs account
credit and an unrestricted key. See `PLAN.md §8 Q18`.

### 10 — the eval deliberately certifies nothing

Mechanism accuracy is **0.875 — identical to the title-lookup baseline**, lift
`+0.000`, because with no model the block runs a keyword fallback that *is* the
title lookup. The report prints the baseline beside the accuracy and refuses to
mark the run as a pass. That is the honest reading, not a failure.

---

## What passed that matters most

- **117/117 unit tests**, including the Phase 0 regressions that reproduce the
  plan's own baselines exactly (52,987 sales lines, 4,422.7M revenue, 10.09%
  blended margin, 10,405 loss-making lines, 93 bounced cheques).
- **All 22 detectors fire** in the golden fixture and **all 22 stay in range** on
  the real book at the demo anchor.
- **0 actions dropped in validation** across every pipeline run — full book,
  12-customer sample, and 3 named accounts. Every recommendation's numbers are
  present in the evidence it cites.
- The pipeline runs identically on **8 customers, 12 customers, or 526**.

## Reproduce this sweep

Each row's `COMMAND:` line is at the top of its file. To re-run everything:

```bash
zsh scripts/run_tests.sh      # writes into test_runs/
```
