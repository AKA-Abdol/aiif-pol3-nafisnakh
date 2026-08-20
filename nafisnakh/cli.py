"""Command line: ``build · signals · brief · eval · label · fixture · calibrate``.

Q2 fixed the deliverable shape: a modular Python service with a CLI, JSON output,
no UI, convertible to an API later. Every command is a thin wrapper over the same
library functions the tests call, so nothing is reachable only through the CLI.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

import typer

from .config import Settings, get_settings

app = typer.Typer(add_completion=False, help="دستیار هوشمند CRM — نفیس نخ")
log = logging.getLogger(__name__)


def _settings(as_of: Optional[str], dataset: Optional[Path]) -> Settings:
    overrides: dict = {}
    if as_of:
        overrides["as_of"] = date.fromisoformat(as_of)
    if dataset:
        overrides["dataset_path"] = dataset
    st = get_settings(**overrides) if overrides else get_settings()
    st.ensure_dirs()
    return st


def _echo(text: str) -> None:
    typer.echo(text)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def build(
    as_of: Optional[str] = typer.Option(None, help="تاریخ مبنا، مثلاً 2021-06-30"),
    dataset: Optional[Path] = typer.Option(None),
    refresh: bool = typer.Option(False, help="نادیده گرفتن کش parquet"),
):
    """Load the workbook, build the metric layer, report what came out."""
    from .io.loader import load_dataset
    from .metrics.base import build_metrics, make_context

    st = _settings(as_of, dataset)
    ds = load_dataset(st, refresh=refresh)
    ctx = build_metrics(make_context(ds, as_of=st.as_of, settings=st))

    _echo(f"تاریخ مبنا: {st.as_of.isoformat()}")
    _echo(f"مشتریان با سابقه فروش: {len(ctx.population)}")
    _echo(f"ردیف‌های فروش قابل‌مشاهده: {len(ctx.spine.lines)}")
    _echo(f"پوشش بهای تمام‌شده: {ctx.spine.cost_coverage()}")
    _echo(f"جدول‌های سنجه: {', '.join(ctx.tables)}")
    _echo(f"شواهد تولیدشده: {len(ctx.evidence)}")
    path = Path(st.out_dir) / f"evidence_{st.as_of.isoformat()}.json"
    ctx.evidence.dump_json(path)
    _echo(f"شواهد نوشته شد: {path}")


@app.command()
def signals(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    skip_llm: bool = typer.Option(False, help="بلوک شکایات اجرا نشود"),
):
    """Run the 22 detectors and write the ranked signal file."""
    from .llm.graph import run_pipeline

    st = _settings(as_of, dataset)
    state = run_pipeline(settings=st, as_of=st.as_of, skip_llm=skip_llm, use_graph=False)
    run, report = state["signals"], state["calibration"]

    path = Path(st.out_dir) / f"signals_{st.as_of.isoformat()}.json"
    run.dump_json(path)
    _echo(f"سیگنال‌ها: {len(run.signals)} روی {len(run.triggered_customers())} مشتری")
    _echo(f"نوشته شد: {path}")
    if run.errors:
        _echo(f"⚠️ آشکارسازهای خطادار: {run.errors}")
    failures = report.failures
    if len(failures):
        _echo("⚠️ آشکارسازهای خارج از محدوده کالیبراسیون:")
        _echo(failures.to_string(index=False))


@app.command()
def calibrate(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
):
    """Report every detector's fire rate against its eligible population."""
    from .llm.graph import run_pipeline

    st = _settings(as_of, dataset)
    state = run_pipeline(settings=st, as_of=st.as_of, use_graph=False)
    report = state["calibration"]
    path = Path(st.out_dir) / f"calibration_{st.as_of.isoformat()}.csv"
    path.write_text(report.rows.to_csv(index=False), encoding="utf-8")
    _echo(str(report))
    _echo(f"\nنوشته شد: {path}")
    raise typer.Exit(code=1 if len(report.failures) else 0)


@app.command()
def brief(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    top: int = typer.Option(25, help="چند اقدام در خروجی"),
    skip_llm: bool = typer.Option(False),
):
    """End-to-end run: ranked action queue as JSON plus a readable Persian brief."""
    from .llm.graph import run_pipeline

    st = _settings(as_of, dataset)
    state = run_pipeline(
        settings=st, as_of=st.as_of, top_n=top, skip_llm=skip_llm, use_graph=False
    )
    queue = state["queue"]

    json_path = Path(st.out_dir) / f"actions_{st.as_of.isoformat()}.json"
    text_path = Path(st.out_dir) / f"brief_{st.as_of.isoformat()}.txt"
    queue.dump_json(json_path)
    text = queue.to_brief_fa(st, top_n=top)
    text_path.write_text(text, encoding="utf-8")

    _echo(text)
    _echo(f"\nنوشته شد: {json_path}")
    _echo(f"نوشته شد: {text_path}")
    if queue.dropped:
        _echo(f"⚠️ {len(queue.dropped)} اقدام در اعتبارسنجی شواهد رد شد.")


@app.command()
def report(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    top: int = typer.Option(25),
):
    """Render the sales-manager artifact: one self-contained RTL HTML file."""
    from .llm.graph import run_pipeline
    from .report import write_report

    st = _settings(as_of, dataset)
    state = run_pipeline(settings=st, as_of=st.as_of, top_n=top, use_graph=False)
    path = write_report(
        state["queue"], state["ctx"], state["quadrants"],
        settings=st, calibration=state["calibration"], top_n=top,
    )
    _echo(f"گزارش نوشته شد: {path}")
    _echo(f"اقدام‌ها: {len(state['queue'].actions)} · "
          f"دسته‌بندی: {state['quadrants'].counts()}")


@app.command()
def feedback(
    customer: Optional[str] = typer.Option(None, help="شناسه مشتری"),
    decision: Optional[str] = typer.Option(
        None, help="done | dismissed | snoozed | wrong"),
    reason: Optional[str] = typer.Option(None, help="دلیل، اختیاری"),
    actor: Optional[str] = typer.Option(None, help="ثبت‌کننده"),
    detectors: Optional[str] = typer.Option(
        None, help="فهرست آشکارسازها با کاما؛ خالی یعنی از صف فعلی برداشته شود"),
    as_of: Optional[str] = typer.Option(None),
    show: bool = typer.Option(False, "--show", help="فقط گزارش وضعیت بازخورد"),
):
    """Record what the sales manager did with an action, or show the effect so far."""
    from .feedback import FeedbackStore, recalibration_report

    st = _settings(as_of, None)
    store = FeedbackStore(settings=st)

    if show or not (customer and decision):
        _echo(recalibration_report(store))
        return

    names = [d.strip() for d in detectors.split(",")] if detectors else []
    if not names:
        from .llm.graph import run_pipeline

        state = run_pipeline(settings=st, as_of=st.as_of, use_graph=False)
        action = next(
            (a for a in state["queue"].actions if a.customer_id == customer), None
        )
        if action is None:
            _echo(
                f"مشتری {customer} در صف فعلی اقدامی ندارد. "
                "آشکارسازها را با --detectors مشخص کنید."
            )
            raise typer.Exit(code=1)
        names = action.signals

    event = store.record(
        customer, decision, names, as_of=st.as_of, reason_fa=reason, actor=actor
    )
    _echo(f"ثبت شد: {customer} · {decision} · {', '.join(event.detectors)}")
    _echo("")
    _echo(recalibration_report(store))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False),
):
    """Serve the HTTP API (Q2: convertible to an API later)."""
    import uvicorn

    _echo(f"http://{host}:{port}/docs")
    uvicorn.run("nafisnakh.api:app", host=host, port=port, reload=reload)


@app.command("eval")
def eval_cmd(
    dataset: Optional[Path] = typer.Option(None),
    labels: Optional[Path] = typer.Option(None, help="مسیر فایل برچسب‌های طلایی"),
):
    """Score the complaint block against the 40 real complaints."""
    from .eval.golden import run_eval

    st = _settings(None, dataset)
    report = run_eval(st, path=labels)
    text = report.to_text()
    if len(report.confusions):
        text += "\n\nخطاهای مکانیزم:\n" + report.confusions.to_string()
    path = Path(st.out_dir) / "eval_complaints_golden.txt"
    path.write_text(text, encoding="utf-8")
    _echo(text)
    _echo(f"\nنوشته شد: {path}")


@app.command()
def label(
    dataset: Optional[Path] = typer.Option(None),
    show: int = typer.Option(5, help="چند ردیف نمایش داده شود"),
    only_unreviewed: bool = typer.Option(True),
    only_ambiguous: bool = typer.Option(False),
):
    """Print golden rows for human review (Q8: I propose, the user corrects)."""
    from .eval.golden import load_golden

    _settings(None, dataset)
    g = load_golden()
    rows = g.rows
    if only_unreviewed:
        rows = [r for r in rows if not r.get("reviewed")]
    if only_ambiguous:
        rows = [r for r in rows if r.get("ambiguous")]

    _echo(f"بازبینی‌نشده: {len(rows)} از {len(g.rows)} — مبهم: {g.ambiguous_count}")
    for r in rows[:show]:
        _echo("-" * 70)
        _echo(f"{r['complaint_id']} · {r['customer_id']} · {r['title']} · {r['severity']}")
        _echo(f"متن: {r['text']}")
        _echo(f"برچسب پیشنهادی: {json.dumps(r['labels'], ensure_ascii=False)}")
        if r.get("labeller_note_fa"):
            _echo(f"یادداشت: {r['labeller_note_fa']}")
    _echo("-" * 70)
    _echo(
        "برای تأیید، در nafisnakh/eval/golden_labels.yaml مقدار reviewed را true کنید."
    )


@app.command()
def fixture(
    write_snapshot: bool = typer.Option(False, help="بازنویسی اسنپ‌شات رگرسیون"),
):
    """Run the golden-sample fixture end to end (PLAN §6)."""
    from .eval.fixture import run_fixture, snapshot
    from .signals.base import all_detectors

    state = run_fixture()
    snap = snapshot(state)
    fired = set(snap["detectors_fired"])
    expected = {d.name for d in all_detectors()}

    _echo(f"مشتریان نمونه: {len(snap['customers'])}")
    _echo(f"آشکارسازهای فعال‌شده: {len(fired)} از {len(expected)}")
    if expected - fired:
        _echo(f"⚠️ فعال نشد: {sorted(expected - fired)}")
    _echo(f"دسته‌بندی‌ها: {snap['buckets']}")
    _echo(f"اقدام‌ها: {len(snap['actions'])} · رد شده: {snap['dropped']}")

    if write_snapshot:
        path = Path(__file__).parent / "eval" / "fixture_snapshot.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        _echo(f"اسنپ‌شات نوشته شد: {path}")


if __name__ == "__main__":
    app()
