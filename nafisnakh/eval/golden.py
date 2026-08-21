"""Scoring the complaint block against the 40 real complaints (PLAN §4, Q8).

Why only 40? Universe A has 480 complaints, but 67% of their bodies are verbatim
duplicates of one of 166 templated strings. Fitting or evaluating on those
measures how well the model reproduces a generator. The 40 universe-B complaints
are 100% unique, human-written Persian with typos, mixed Arabic/Persian
orthography, real Jalali dates and real corrective actions. **All NLP evaluation
uses the 40** (PLAN §1.4).

Targets from the plan: ≥0.80 mechanism accuracy, ≥0.90 recall on ``churn_threat``.

The report is honest about what this set *cannot* measure. With 40 rows some
labels have very few positives — a field with zero positives has no recall to
report, and the scorer says so instead of printing 0.0 or 1.0 and looking
authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..io import schema as S
from ..llm.taxonomy import MECHANISM_IDS, UNKNOWN

LABELS_PATH = Path(__file__).with_name("golden_labels.yaml")
BOOLEAN_FIELDS = [
    "churn_threat", "repeat_claim", "financial_demand", "evidence_supplied",
]
CATEGORICAL_FIELDS = ["escalation_level", "attributed_fault"]

TARGET_MECHANISM_ACCURACY = 0.80
TARGET_CHURN_RECALL = 0.90


@dataclass
class GoldenSet:
    rows: list[dict[str, Any]]

    @property
    def reviewed_count(self) -> int:
        return sum(1 for r in self.rows if r.get("reviewed"))

    @property
    def ambiguous_count(self) -> int:
        return sum(1 for r in self.rows if r.get("ambiguous"))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"complaint_id": r["complaint_id"], "customer_id": r["customer_id"],
             "reviewed": r.get("reviewed", False), "ambiguous": r.get("ambiguous", False),
             **{k: v for k, v in r["labels"].items()}}
            for r in self.rows
        ]).set_index("complaint_id")


def load_golden(path: Path | None = None) -> GoldenSet:
    doc = yaml.safe_load((path or LABELS_PATH).read_text(encoding="utf-8"))
    return GoldenSet(rows=doc["rows"])


# ------------------------------------------------------------------- metrics
def _binary_scores(truth: pd.Series, pred: pd.Series) -> dict[str, Any]:
    t = truth.fillna(False).astype(bool)
    p = pred.reindex(truth.index).fillna(False).astype(bool)
    tp = int((t & p).sum())
    fp = int((~t & p).sum())
    fn = int((t & ~p).sum())
    tn = int((~t & ~p).sum())
    n_pos = tp + fn
    return {
        "positives_in_gold": n_pos,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": (tp / (tp + fp)) if (tp + fp) else None,
        "recall": (tp / n_pos) if n_pos else None,
        "accuracy": (tp + tn) / max(len(t), 1),
        "note": ("no positive examples in the golden set — this field cannot be "
                 "scored on 40 rows") if n_pos == 0 else "",
    }


@dataclass
class EvalReport:
    n_rows: int
    extraction_source: str
    mechanism: dict[str, Any]
    booleans: dict[str, dict[str, Any]]
    categoricals: dict[str, dict[str, Any]]
    reviewed_count: int
    ambiguous_count: int
    confusions: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def is_model_run(self) -> bool:
        """True only when a real model produced the extractions.

        A rules run scores the *title lookup*, not a model. Reporting it as a
        pass would certify something that was never tested.
        """
        return any(s in self.extraction_source for s in ("live", "cached"))

    @property
    def passes_targets(self) -> bool:
        churn_recall = self.booleans.get("churn_threat", {}).get("recall")
        return (
            self.is_model_run
            and self.mechanism["accuracy"] >= TARGET_MECHANISM_ACCURACY
            and (churn_recall is None or churn_recall >= TARGET_CHURN_RECALL)
        )

    def to_text(self) -> str:
        lines = [
            "ارزیابی بلوک LLM شکایات — مجموعه طلایی ۴۰ شکایت واقعی",
            "=" * 62,
            f"منبع استخراج          : {self.extraction_source}",
            f"تعداد ردیف            : {self.n_rows}",
            f"بازبینی‌شده توسط کاربر : {self.reviewed_count}/{self.n_rows}"
            + ("  ⚠️ برچسب‌ها هنوز تأیید نشده‌اند" if self.reviewed_count == 0 else ""),
            f"ردیف‌های مبهم          : {self.ambiguous_count}",
            "",
            f"دقت مکانیزم           : {self.mechanism['accuracy']:.3f}"
            f"  (هدف ≥ {TARGET_MECHANISM_ACCURACY:.2f})",
            f"  بدون ردیف‌های مبهم   : {self.mechanism['accuracy_unambiguous']:.3f}",
            f"  خط پایه نگاشت عنوان : {self.mechanism['title_baseline_accuracy']:.3f}",
            f"  بهبود نسبت به خط پایه: {self.mechanism['lift_over_title_baseline']:+.3f}",
            "",
            "فیلدهای دودویی:",
        ]
        for name, s in self.booleans.items():
            if s["note"]:
                lines.append(f"  {name:20s} — {s['note']}")
                continue
            prec = "—" if s["precision"] is None else f"{s['precision']:.2f}"
            rec = "—" if s["recall"] is None else f"{s['recall']:.2f}"
            lines.append(
                f"  {name:20s} P={prec} R={rec} "
                f"(tp={s['tp']} fp={s['fp']} fn={s['fn']}, مثبت در طلایی={s['positives_in_gold']})"
            )
        lines.append("")
        lines.append("فیلدهای دسته‌ای:")
        for name, s in self.categoricals.items():
            lines.append(f"  {name:20s} accuracy={s['accuracy']:.3f}")
        lines.append("")
        if not self.is_model_run:
            lines += [
                "⚠️ این اجرا با مسیر قاعده‌محور (rules) انجام شده، نه با مدل.",
                "   مکانیزم در این مسیر مستقیماً از نگاشت ۴۵→۱۰ عنوان می‌آید، بنابراین دقت"
                f" {self.mechanism['accuracy']:.3f} دقیقاً همان خط پایه است و",
                "   هیچ چیزی درباره کیفیت مدل نمی‌گوید. ارزش واقعی مدل روی همان ردیف‌هایی"
                " است که متن با عنوان نمی‌خواند.",
                "   برای ارزیابی واقعی، OPENROUTER_API_KEY لازم است (سؤال Q14).",
                "",
                "نتیجه: قابل صدور نیست — هیچ مدلی اجرا نشده است.",
            ]
        else:
            lines.append(
                "نتیجه: "
                + ("اهداف برآورده شد ✅" if self.passes_targets else "اهداف برآورده نشد ❌")
            )
        return "\n".join(lines)


def score(extractions: pd.DataFrame, golden: GoldenSet | None = None) -> EvalReport:
    """Score an ``llm_complaints`` table against the golden labels."""
    golden = golden or load_golden()
    gold = golden.frame()

    pred = extractions.reset_index().set_index("complaint_id")
    common = gold.index.intersection(pred.index)
    gold = gold.loc[common]
    pred = pred.loc[common]

    mech_ok = pred["mechanism"] == gold["mechanism"]
    unambiguous = ~gold["ambiguous"].astype(bool)
    title_ok = pred["title_mechanism"] == gold["mechanism"]

    confusions = pd.DataFrame({
        "gold": gold["mechanism"],
        "pred": pred["mechanism"],
        "ambiguous": gold["ambiguous"],
    }).loc[~mech_ok]

    booleans = {f: _binary_scores(gold[f], pred[f]) for f in BOOLEAN_FIELDS}
    categoricals = {
        f: {"accuracy": float((pred[f] == gold[f]).mean())} for f in CATEGORICAL_FIELDS
    }

    sources = sorted(set(pred["extraction_source"])) if "extraction_source" in pred else []
    return EvalReport(
        n_rows=len(common),
        extraction_source="+".join(sources) or "unknown",
        mechanism={
            "accuracy": float(mech_ok.mean()),
            "accuracy_unambiguous": float(mech_ok[unambiguous].mean()),
            "title_baseline_accuracy": float(title_ok.mean()),
            "lift_over_title_baseline": float(mech_ok.mean() - title_ok.mean()),
            "n_unknown_predicted": int((pred["mechanism"] == UNKNOWN).sum()),
        },
        booleans=booleans,
        categoricals=categoricals,
        reviewed_count=golden.reviewed_count,
        ambiguous_count=int(gold["ambiguous"].sum()),
        confusions=confusions,
    )


def run_eval(
    settings=None, *, allow_rules: bool = True, path: Path | None = None
) -> EvalReport:
    """Load the 40, run the block over them, score."""
    from ..config import get_settings
    from ..io.loader import load_dataset
    from ..llm.blocks.complaint import extract_complaints

    st = settings or get_settings()
    ds = load_dataset(st)
    comp = ds.complaints
    universe_b = comp.loc[comp["_universe"] == "B"].sort_values(S.K_ID)
    extractions = extract_complaints(universe_b, settings=st, allow_rules=allow_rules)
    return score(extractions, load_golden(path))
