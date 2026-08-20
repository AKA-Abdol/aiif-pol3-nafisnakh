"""Command line: ``build · signals · brief · customer · tools · evidence · eval · label · fixture · calibrate``.

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


def _settings(
    as_of: Optional[str], dataset: Optional[Path], profile: Optional[str] = None
) -> Settings:
    overrides: dict = {}
    if as_of:
        try:
            overrides["as_of"] = date.fromisoformat(as_of)
        except ValueError as exc:
            raise typer.BadParameter(
                f"تاریخ نامعتبر {as_of!r} — قالب درست YYYY-MM-DD است ({exc})",
                param_hint="--as-of",
            ) from None
    if dataset:
        overrides["dataset_path"] = dataset
    if profile:
        overrides["llm_profile"] = profile
    st = get_settings(**overrides) if overrides else get_settings()
    st.ensure_dirs()
    return st


def _echo(text: str) -> None:
    typer.echo(text)


def _subset(ds, customers: Optional[str], sample: int):
    """Apply ``--customers`` / ``--sample``, and name what came out.

    Returns the dataset and a filename suffix. Without the suffix an
    8-customer run would overwrite the full book's artifact at the same
    ``as_of`` — same path, 60× less content, no warning.
    """
    from .io.loader import subset_dataset

    ids = [c.strip() for c in customers.split(",")] if customers else None
    if not ids and not sample:
        return ds, ""
    try:
        ds = subset_dataset(ds, ids, sample=sample)
    except KeyError as exc:
        raise typer.BadParameter(str(exc).strip('"'), param_hint="--customers") from None
    _echo(f"زیرمجموعه: {len(ds.customers)} مشتری، {len(ds.sales)} ردیف فروش\n")
    return ds, f"__{len(ds.customers)}c"


def _fmt_coverage(coverage: dict) -> str:
    """``{'realized': 0.3}`` → ``واقعی 30.2٪ · برآوردی 69.8٪``."""
    label = {"realized": "واقعی", "estimated": "برآوردی", "none": "بدون بها"}
    if not coverage:
        return "—"
    return " · ".join(
        f"{label.get(k, k)} {v * 100:.1f}٪"
        for k, v in sorted(coverage.items(), key=lambda kv: -kv[1])
    )


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
    sample: int = typer.Option(0, help="فقط روی N مشتری تصادفی اجرا کن"),
    customers: Optional[str] = typer.Option(None, help="شناسه مشتریان با کاما"),
):
    """Load the workbook, build the metric layer, report what came out."""
    from .io.loader import load_dataset
    from .metrics.base import build_metrics, make_context

    st = _settings(as_of, dataset)
    ds = load_dataset(st, refresh=refresh)
    ds, suffix = _subset(ds, customers, sample)
    ctx = build_metrics(make_context(ds, as_of=st.as_of, settings=st))

    _echo(f"تاریخ مبنا: {st.as_of.isoformat()}")
    _echo(f"مشتریان با سابقه فروش: {len(ctx.population)}")
    _echo(f"ردیف‌های فروش قابل‌مشاهده: {len(ctx.spine.lines)}")
    _echo(f"پوشش بهای تمام‌شده: {_fmt_coverage(ctx.spine.cost_coverage())}")
    _echo(f"جدول‌های سنجه: {', '.join(ctx.tables)}")
    _echo(f"شواهد تولیدشده: {len(ctx.evidence)}")
    path = Path(st.out_dir) / f"evidence_{st.as_of.isoformat()}{suffix}.json"
    ctx.evidence.dump_json(path)
    _echo(f"شواهد نوشته شد: {path}")


@app.command()
def signals(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    skip_llm: bool = typer.Option(False, help="بلوک شکایات اجرا نشود"),
    sample: int = typer.Option(0, help="فقط روی N مشتری تصادفی اجرا کن"),
    customers: Optional[str] = typer.Option(None, help="شناسه مشتریان با کاما"),
):
    """Run the 27 detectors and write the ranked signal file."""
    from .io.loader import load_dataset
    from .llm.graph import run_pipeline

    st = _settings(as_of, dataset)
    ds, suffix = _subset(load_dataset(st), customers, sample)
    # `detect` is the last node this command needs; everything after it is
    # LLM work whose output would be thrown away here.
    state = run_pipeline(settings=st, as_of=st.as_of, dataset=ds, skip_llm=skip_llm,
                         use_graph=False, stop_after="detect")
    run, report = state["signals"], state["calibration"]

    path = Path(st.out_dir) / f"signals_{st.as_of.isoformat()}{suffix}.json"
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
    state = run_pipeline(settings=st, as_of=st.as_of, use_graph=False,
                         stop_after="detect")
    report = state["calibration"]
    path = Path(st.out_dir) / f"calibration_{st.as_of.isoformat()}.csv"
    path.write_text(report.rows.to_csv(index=False), encoding="utf-8")
    _echo(str(report))
    if len(report.insufficient):
        # a table with no failures is not a clean bill if half of it was never judged
        _echo(
            f"\nℹ️ {len(report.insufficient)} آشکارساز به دلیل کوچک بودن جمعیت واجد "
            f"شرایط (کمتر از {st.calib_min_eligible}) داوری نشدند."
        )
    _echo(f"\nنوشته شد: {path}")
    raise typer.Exit(code=1 if len(report.failures) else 0)


@app.command()
def brief(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    top: int = typer.Option(25, help="چند اقدام در خروجی"),
    skip_llm: bool = typer.Option(False),
    profile: Optional[str] = typer.Option(None, help="پروفایل مدل (فعلاً فقط gemini — OpenRouter)"),
    sample: int = typer.Option(0, help="فقط روی N مشتری تصادفی اجرا کن — برای تست سریع"),
    customers: Optional[str] = typer.Option(None, help="شناسه مشتریان با کاما"),
):
    """End-to-end run: ranked action queue as JSON plus a readable Persian brief."""
    from .io.loader import load_dataset
    from .llm.graph import run_pipeline

    st = _settings(as_of, dataset, profile)
    ds, suffix = _subset(load_dataset(st), customers, sample)
    if suffix:
        _echo("⚠️ اجرای نمونه‌ای: آشکارسازهای مبتنی بر همتایان روی نمونه کوچک "
              "خاموش می‌مانند (نیازمند ۵ تا ۸ همتا).\n")
    state = run_pipeline(
        settings=st, as_of=st.as_of, dataset=ds, top_n=top, skip_llm=skip_llm,
        use_graph=False,
    )
    queue = state["queue"]

    json_path = Path(st.out_dir) / f"actions_{st.as_of.isoformat()}{suffix}.json"
    text_path = Path(st.out_dir) / f"brief_{st.as_of.isoformat()}{suffix}.txt"
    queue.dump_json(json_path)
    text = queue.to_brief_fa(st, top_n=top)
    text_path.write_text(text, encoding="utf-8")

    _echo(text)
    _echo(f"\nنوشته شد: {json_path}")
    _echo(f"نوشته شد: {text_path}")
    if queue.dropped:
        _echo(f"⚠️ {len(queue.dropped)} اقدام در اعتبارسنجی شواهد رد شد.")


@app.command()
def models(
    test: bool = typer.Option(False, "--test", help="یک درخواست واقعی به هر پروفایل بزن"),
):
    """List the generation profiles and, with --test, check which ones answer."""
    import httpx

    from .config import LLM_PROFILES

    st = get_settings()
    _echo(f"پروفایل فعال: {st.llm_profile}\n")
    for name, profile in LLM_PROFILES.items():
        s = get_settings(llm_profile=name)
        mark = "◀ فعال" if name == st.llm_profile else ""
        _echo(f"{name:14s} {profile.model:28s} {profile.base_url}")
        _echo(f"{'':14s} provider: {', '.join(s.active_provider_only) or 'خودکار'}")
        _echo(f"{'':14s} کلید {profile.api_key_env}: "
              f"{'موجود' if s.llm_available else 'خالی'} {mark}")
        if profile.note:
            _echo(f"{'':14s} {profile.note}")
        if test and s.llm_available:
            try:
                r = httpx.post(
                    f"{s.active_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {s.active_api_key}"},
                    json={"model": s.active_model,
                          "provider": s.provider_routing,
                          "messages": [{"role": "user", "content": "ping"}],
                          "max_tokens": 5},
                    timeout=40,
                )
                ok = "✅" if r.status_code == 200 else "❌"
                _echo(f"{'':14s} {ok} HTTP {r.status_code} {r.text[:110]}")
            except Exception as exc:
                _echo(f"{'':14s} ❌ {type(exc).__name__}: {str(exc)[:90]}")
        _echo("")


@app.command()
def report(
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    top: int = typer.Option(25),
    profile: Optional[str] = typer.Option(None, help="پروفایل مدل (فعلاً فقط gemini — OpenRouter)"),
):
    """Render the sales-manager artifact: one self-contained RTL HTML file."""
    from .llm.graph import run_pipeline
    from .report import write_report

    st = _settings(as_of, dataset, profile)
    state = run_pipeline(settings=st, as_of=st.as_of, top_n=top, use_graph=False)
    path = write_report(
        state["queue"], state["ctx"], state["quadrants"],
        settings=st, calibration=state["calibration"], top_n=top,
    )
    _echo(f"گزارش نوشته شد: {path}")
    _echo(f"اقدام‌ها: {len(state['queue'].actions)} · "
          f"دسته‌بندی: {state['quadrants'].counts()}")


@app.command()
def customer(
    customer_id: str = typer.Argument(..., help="شناسه مشتری، مثلاً C_245948"),
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    profile: Optional[str] = typer.Option(None, help="پروفایل مدل"),
    actions: bool = typer.Option(
        False, help="مرحله تجمیع هم اجرا شود تا اقدام پیشنهادی نوشته شود (هزینه مدل دارد)"
    ),
    tools: bool = typer.Option(
        True, help="هشت ابزار مشتری هم اجرا شوند و شواهد ردیف‌به‌ردیفشان در صفحه بیاید"
    ),
    rows: int = typer.Option(25, help="حداکثر ردیف نمایش‌داده‌شده از هر شاهد"),
    output: Optional[Path] = typer.Option(None, help="مسیر فایل خروجی"),
):
    """The 360° page for one customer — every claim expandable to its rows.

    Deliberately no ``--customers``/``--sample``: the bucket threshold is the
    book's median revenue, RFM scores are quintiles of the book and the peer
    cohorts are the book, so the pipeline runs on the whole thing and the page
    narrows afterwards. A one-customer run would render numbers that are
    individually true and collectively meaningless.
    """
    from .customer360 import build_state, write_customer_page

    st = _settings(as_of, dataset, profile)
    state = build_state(st, with_actions=actions, customer_id=customer_id,
                        with_tools=tools)
    try:
        path = write_customer_page(
            customer_id, state, settings=st, max_rows=rows, path=output
        )
    except KeyError as exc:
        raise typer.BadParameter(str(exc).strip('"'), param_hint="customer_id") from None

    ctx = state["ctx"]
    sigs = [s for s in state["signals"].signals if s.customer_id == customer_id]
    _echo(f"مشتری: {customer_id} · تاریخ مبنا {st.as_of.isoformat()}")
    _echo(f"سیگنال‌ها: {len(sigs)} · شواهد: {len(ctx.evidence.for_customer(customer_id))}")
    if not actions:
        _echo("(بدون --actions اقدام پیشنهادی نوشته نمی‌شود)")
    _echo(f"صفحه نوشته شد: {path}")


@app.command("tools")
def tools_cmd(
    customer_id: str = typer.Argument(..., help="شناسه مشتری، مثلاً C_126481"),
    tool: Optional[str] = typer.Option(None, help="فقط همین ابزار اجرا شود"),
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    payload: bool = typer.Option(False, help="داده ساختاریافته هم چاپ شود"),
):
    """Run the customer tools and print exactly what an agent would be given.

    The printed text *is* the prompt payload: Persian claims and evidence ids,
    never a bare number. ``--payload`` shows the Python-side structure, which no
    prompt ever receives.
    """
    from .customer360 import build_state, run_all_tools
    from .tools import get_tool, run_tool

    st = _settings(as_of, dataset)
    state = build_state(st, with_actions=False)
    ctx = state["ctx"]
    if customer_id not in set(ctx.population):
        raise typer.BadParameter(
            f"{customer_id} در تاریخ {st.as_of.isoformat()} ردیف فروش قابل‌مشاهده ندارد",
            param_hint="customer_id",
        )
    if tool:
        try:
            results = [run_tool(ctx, get_tool(tool).name, customer_id)]
        except KeyError as exc:
            raise typer.BadParameter(str(exc).strip('"'), param_hint="--tool") from None
    else:
        results = run_all_tools(ctx, customer_id)

    for r in results:
        _echo(r.to_model_text())
        if payload:
            _echo("payload: " + json.dumps(r.payload, ensure_ascii=False, default=str))
        _echo("")
    minted = sum(len(r.evidence_ids) for r in results)
    _echo(f"{len(results)} ابزار · {minted} شاهد قابل نمایش با «nafisnakh evidence <ID>»")


@app.command()
def evidence(
    evidence_id: str = typer.Argument(..., help="شناسه شاهد، مثلاً EV-C_245948-exposure-001"),
    as_of: Optional[str] = typer.Option(None),
    dataset: Optional[Path] = typer.Option(None),
    rows: int = typer.Option(20, help="حداکثر ردیف نمایش داده‌شده"),
):
    """Show the actual source rows behind one evidence id.

    This is what makes a recommendation defensible in front of a customer: the
    claim, then the records it rests on, from the workbook.
    """
    import json

    from .core.evidence import EvidenceRegistry, resolve
    from .io.loader import load_dataset

    st = _settings(as_of, dataset)
    ds = load_dataset(st)

    # prefer the artifact `build` already wrote; fall back to recomputing
    dumped = Path(st.out_dir) / f"evidence_{st.as_of.isoformat()}.json"
    if dumped.exists():
        registry = EvidenceRegistry.from_records(
            json.loads(dumped.read_text(encoding="utf-8"))
        )
    else:
        from .metrics.base import build_metrics, make_context

        _echo("(فایل شواهد یافت نشد؛ لایه سنجه بازساخته می‌شود)\n")
        registry = build_metrics(
            make_context(ds, as_of=st.as_of, settings=st)
        ).evidence

    ev = registry.get(evidence_id)
    if ev is None:
        _echo(f"شاهدی با شناسه {evidence_id} یافت نشد.")
        raise typer.Exit(code=1)

    _echo(f"شناسه      : {ev.id}")
    _echo(f"مشتری      : {ev.customer_id}")
    _echo(f"ادعا       : {ev.claim_fa}")
    _echo(f"مقدار      : {ev.value} {ev.unit or ''}")
    _echo(f"اطمینان    : {ev.confidence}")
    _echo(f"فرمول      : {ev.provenance.get('formula', '—')}")
    if ev.provenance.get("assumption"):
        _echo(f"⚠️ فرض     : {ev.provenance.get('caveat_fa', '')}")
    _echo(f"ارجاع      : {ev.source_rows}")
    if not ev.is_resolvable:
        _echo("\n⚠️ این شاهد locator ندارد و قابل بازیابی نیست.")
        raise typer.Exit(code=1)
    _echo(f"locator    : {json.dumps(ev.locator, ensure_ascii=False)}")

    found = resolve(ev, ds)
    _echo(f"\nردیف‌های منبع ({len(found)} ردیف):")
    shown = found.head(rows)
    cols = [c for c in shown.columns if not str(c).startswith("_")]
    _echo(shown[cols].to_string(index=False))
    if len(found) > rows:
        _echo(f"… و {len(found) - rows} ردیف دیگر")


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
    profile: Optional[str] = typer.Option(None, help="پروفایل مدل (فعلاً فقط gemini — OpenRouter)"),
):
    """Score the complaint block against the 40 real complaints."""
    from .eval.golden import run_eval

    st = _settings(None, dataset, profile)
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
