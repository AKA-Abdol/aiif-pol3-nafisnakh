#!/bin/zsh
cd /Users/mehdi/Documents/project/POL-3/aiif-pol3-nafisnakh
NN=.venv/bin/nafisnakh
D=test_runs
run () {  # run <file> <title> <command...>
  local f="$D/$1"; shift; local title="$1"; shift
  {
    echo "════════════════════════════════════════════════════════════════════"
    echo "TEST   : $title"
    echo "COMMAND: $*"
    echo "WHEN   : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "════════════════════════════════════════════════════════════════════"
    echo
  } > "$f"
  local start=$(python3 -c 'import time;print(time.time())')
  "$@" >> "$f" 2>&1
  local rc=$?
  local end=$(python3 -c 'import time;print(time.time())')
  {
    echo
    echo "────────────────────────────────────────────────────────────────────"
    printf 'EXIT CODE: %s   ELAPSED: %.1fs\n' "$rc" "$(python3 -c "print($end-$start)")"
  } >> "$f"
  printf '  %-34s exit=%s  %6.1fs  → %s\n' "$title" "$rc" "$(python3 -c "print($end-$start)")" "$f"
}

echo "Running test sweep…"
run 01_unit_tests.txt        "Unit + regression suite"      .venv/bin/python -m pytest tests -q
run 02_fixture.txt           "Golden fixture (synthetic)"   $NN fixture
run 03_build_full.txt        "Metric layer, full book"      $NN build
run 04_build_sample8.txt     "Metric layer, 8 customers"    $NN build --sample 8
run 05_calibrate.txt         "Detector calibration"         $NN calibrate
run 06_signals.txt           "Signal engine, full book"     $NN signals
run 07_brief_sample12.txt    "Pipeline, 12 real customers"  $NN brief --sample 12 --top 12
run 08_brief_named.txt       "Pipeline, 3 named accounts"   $NN brief --customers C_117580,C_245948,C_299317 --top 3
run 09_brief_full.txt        "Pipeline, full book"          $NN brief --top 25
run 10_eval_golden.txt       "Complaint eval, 40 golden"    $NN eval
run 11_labels_ambiguous.txt  "Golden labels needing review" $NN label --only-ambiguous --show 11
run 12_models.txt            "Model backends, live probe"   $NN models --test
run 13_report.txt            "Sales-manager HTML report"    $NN report --top 25
run 14_feedback.txt          "Feedback loop state"          $NN feedback --show
run 15_asof_2021_12.txt      "Different anchor 2021-12-31"  $NN calibrate --as-of 2021-12-31
