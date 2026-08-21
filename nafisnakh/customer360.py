"""The 360° customer page — one account, everything, every claim openable.

The user's requirement, in their words: *«اگر به evidence ای اشاره میکنیم، باید
بتونیم با یه سری کد پایتون اون evidence رو هم بعدا نمایش بدیم … حتی در خروجی برای
یک مشتری به صورت یک صفحه ۳۶۰»*. This module is where that stops being a property
of the data model and becomes something a person can look at.

The whole page rests on one mechanic: **every number on it is a link to the rows
it came from.** Section 5 lists every Evidence this customer has, each one a
``<details>`` that expands into a table of the actual workbook records, resolved
through :func:`nafisnakh.core.evidence.resolve` and therefore gated at ``as_of``
by rule #4. Every evidence id mentioned anywhere else on the page — in a signal,
in the recommended action, in a tile — is an anchor into that section. Nothing is
asserted that cannot be opened.

Two consequences worth stating, because they shaped the code:

* **The page must be computed on the whole book, then narrowed.** The bucket
  threshold is the book's median revenue, RFM scores are quintiles of the book,
  and the peer cohorts are the book. Running the pipeline on a one-customer
  subset would produce a page full of numbers that are individually true and
  collectively meaningless. :func:`build_state` therefore never subsets.
* **The rows are embedded, not fetched.** The file has to survive being emailed,
  opened from a phone, or shown across a table with no network, so it carries its
  own evidence — no CDN, no font download, no API call.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .aggregate.quadrant import BUCKET_LABEL_FA, BUCKET_MEANING_FA
from .config import Settings
from .core.evidence import Evidence, resolve
from .metrics.base import money, num, pct
from .metrics.rfm import SEGMENT_MEANING_FA
from .report import BUCKET_CLASS, CSS, HEALTH_CLASS, _e

# Columns that are ours, not the workbook's. A customer looking at their own
# records should see the records, not our intermediate arithmetic.
INTERNAL_COLUMNS = ("_universe", "is_fixture")

CATEGORY_FA = {"risk": "ریسک", "opportunity": "فرصت", "efficiency": "کارایی"}
CREDIT_STATE_FA = {
    "open": "باز", "exhausted": "پر شده", "unknown": "نامشخص",
}
# Short labels for the chip; the full guidance lives in RELATIONSHIP_STANCE_FA
# and is shown underneath, because "unsubstantiated" on its own is an internal
# key, not something to put in front of a sales manager.
STANCE_LABEL_FA = {
    "apologise": "قصور از ما بوده — با پذیرش شروع کن",
    "unsubstantiated": "شکایت‌ها وارد نبوده — عذرخواهی لازم نیست",
    "mixed": "سابقه شکایات دوگانه — پرونده‌به‌پرونده مرور کن",
    "neutral": "خنثی",
}

EXTRA_CSS = """
.sect{margin:26px 0 10px;font-size:17px;font-weight:700}
.sect .hint{font-weight:400;font-size:12.5px;color:var(--muted);margin-inline-start:8px}
.tile .s{font-size:12.5px;color:var(--muted);margin-top:2px}
.sig{display:flex;gap:10px;align-items:flex-start;padding:10px 0;
  border-top:1px dashed var(--line)}
.sig:first-child{border-top:none}
.sev{font-variant-numeric:tabular-nums;font-weight:700;min-width:2.6em;text-align:center;
  border-radius:8px;padding:2px 6px;font-size:13px;background:var(--line)}
.sev-hi{background:var(--urgent);color:#fff}
.sev-mid{background:var(--high);color:#fff}
.sig-body{flex:1}
.sig-meta{color:var(--muted);font-size:12.5px;margin-top:3px}
a.evref{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
  direction:ltr;display:inline-block;color:var(--accent);text-decoration:none;
  border:1px solid var(--line);border-radius:6px;padding:0 5px;margin-inline-end:4px}
a.evref:hover{border-color:var(--accent)}
details.evd{margin:0 0 8px;padding:10px 14px}
details.evd[open]{border-color:var(--accent)}
details.evd summary{font-weight:500;font-size:14px}
details.evd summary::marker{color:var(--muted)}
.formula{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
  direction:ltr;text-align:left;color:var(--muted);margin:6px 0}
.rowcount{color:var(--muted);font-size:12.5px;margin:8px 0 4px}
.empty{color:var(--urgent);font-size:13px}
table td{white-space:nowrap;font-variant-numeric:tabular-nums}
.loop{border-inline-start:3px solid var(--high);padding-inline-start:10px;margin:10px 0}
.loop.clear{border-inline-start-color:var(--grow)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 14px;font-size:13.5px}
.kv dt{color:var(--muted)}
.kv dd{margin:0}
"""

# `<details>` does not open itself when you jump to it by anchor. Without this,
# clicking an evidence id scrolls to a closed row and the page looks broken.
OPEN_ON_ANCHOR_JS = """
function openTarget(){
  var el = document.getElementById(location.hash.slice(1));
  if (el && el.tagName === 'DETAILS') { el.open = true; el.scrollIntoView({block:'center'}); }
}
addEventListener('hashchange', openTarget); addEventListener('load', openTarget);
"""


# --------------------------------------------------------------------- helpers
def _val(row: pd.Series | None, key: str, default=None):
    if row is None or key not in row:
        return default
    v = row[key]
    return default if (v is None or (not isinstance(v, str) and pd.isna(v))) else v


def _evrefs(ids: list[str]) -> str:
    """Evidence ids as anchors into section 5 — the page's whole mechanic."""
    return "".join(f'<a class="evref" href="#{_e(i)}">{_e(i)}</a>' for i in ids)


def _rows_table(frame: pd.DataFrame, limit: int) -> str:
    shown = frame.head(limit)
    cols = [c for c in shown.columns if c not in INTERNAL_COLUMNS]
    head = "".join(f"<th>{_e(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(_cell(r[c]))}</td>" for c in cols) + "</tr>"
        for _, r in shown.iterrows()
    )
    more = (f'<div class="rowcount">… و {len(frame) - limit} ردیف دیگر</div>'
            if len(frame) > limit else "")
    return (f'<div class="rowcount">{len(frame)} ردیف منبع</div>'
            f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>{more}')


def _cell(v: Any) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "—"
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def _open_loop_kinds(loops: pd.Series) -> int:
    """How many of the four loop *kinds* are open.

    The raw item count is the honest total but a bad headline: fifteen abandoned
    offers on one account reads as fifteen separate failures when it is one.
    """
    # int() around each term, not around the sum: `np.bool_ + np.bool_` is
    # logical OR, so the naive version saturates at 1 and an account with all
    # four loops open reports "1 of 4".
    return sum(int(bool(x)) for x in (
        loops["dev_approved_open"] > 0,
        loops["dev_rejected_unspoken"] > 0,
        loops["next_action_open"],
        loops["offers_abandoned"] > 0,
    ))


def _tile(number: str, label: str, sub: str = "", cls: str = "") -> str:
    return (f'<div class="tile {cls}"><div class="n">{_e(number)}</div>'
            f'<div class="l">{_e(label)}</div>'
            + (f'<div class="s">{_e(sub)}</div>' if sub else "") + "</div>")


# ------------------------------------------------------------------- the page
def render_customer(
    customer_id: str,
    state: dict,
    *,
    settings: Settings,
    max_rows: int = 25,
) -> str:
    """One customer's whole file as a self-contained RTL HTML page."""
    ctx = state["ctx"]
    ds = ctx.ds
    if customer_id not in set(ctx.population):
        raise KeyError(
            f"{customer_id} has no visible sales line at {ctx.as_of.isoformat()}"
        )

    signals = sorted(
        [s for s in state["signals"].signals if s.customer_id == customer_id],
        key=lambda s: -s.severity,
    )
    quad = state["quadrants"].table.loc[customer_id]
    action = next(
        (a for a in state.get("queue").actions if a.customer_id == customer_id),
        None,
    ) if state.get("queue") is not None else None

    sections = [
        _section_glance(ctx, customer_id, quad, settings),
        _section_action(ctx, customer_id, action, quad, signals),
        _section_signals(signals, settings),
        _section_loops(ctx, customer_id),
        _section_tools(ctx, customer_id),
        _section_evidence(ctx, ds, customer_id, max_rows),
    ]
    segment = _val(ctx.table("economics").loc[customer_id], "segment", "—")

    return f"""<title>پرونده ۳۶۰ — {_e(customer_id)}</title>
<style>{CSS}{EXTRA_CSS}</style>
<header>
  <h1>پرونده ۳۶۰ مشتری — {_e(customer_id)}</h1>
  <div class="sub">تاریخ مبنا {_e(ctx.as_of.isoformat())} · بخش {_e(segment)} ·
    {len(signals)} سیگنال · {len(ctx.evidence.for_customer(customer_id))} شاهد ·
    <strong>هر ادعا با کلیک روی شناسه‌اش باز می‌شود روی ردیف‌های واقعی همان ادعا</strong></div>
</header>
<main>{"".join(sections)}</main>
<footer>
  ردیف‌های نمایش‌داده‌شده همان ردیف‌هایی هستند که عدد از آنها محاسبه شده و در تاریخ
  {_e(ctx.as_of.isoformat())} قابل‌مشاهده بوده‌اند (قاعده ۴ — گیت روی Available_At).
  ترتیب سیگنال‌ها در پایتون محاسبه می‌شود، نه توسط مدل زبانی؛ مدل هیچ عددی نمی‌نویسد.
</footer>
<script>{OPEN_ON_ANCHOR_JS}</script>"""


def _section_glance(ctx, cid, quad, st) -> str:
    econ = ctx.table("economics").loc[cid]
    rfm = ctx.table("rfm").loc[cid]
    pay = ctx.table("payment").loc[cid] if cid in ctx.table("payment").index else None
    qual = ctx.table("quality").loc[cid] if cid in ctx.table("quality").index else None
    cad = ctx.table("cadence").loc[cid] if cid in ctx.table("cadence").index else None
    loops = ctx.table("open_loops").loc[cid]

    bucket = quad["bucket"]
    credit_state = _val(pay, "credit_room_state", "unknown")
    exposure_ratio = _val(pay, "exposure_ratio")
    ratio_txt = f"{pct(exposure_ratio, 0)}٪ سقف اعتبار" if exposure_ratio is not None else "سقف نامعتبر"

    tiles = [
        _tile(BUCKET_LABEL_FA[bucket], "دسته‌بندی", BUCKET_MEANING_FA[bucket],
              BUCKET_CLASS[bucket]),
        _tile(str(rfm["rfm_cell"]), f"RFM — {rfm['rfm_segment_fa']}",
              SEGMENT_MEANING_FA[rfm["rfm_segment"]]),
        _tile(money(econ["revenue_total"], st), "درآمد کل",
              f"حاشیه ریسک‌تعدیل‌شده {pct(econ['risk_adj_margin_rate'])}٪"),
        _tile(CREDIT_STATE_FA.get(credit_state, credit_state), "اعتبار", ratio_txt),
        _tile(f"{_open_loop_kinds(loops)} از 4", "حلقه باز از سمت ما",
              f"{num(loops['open_loop_count'])} مورد — کارهایی که ما تمام نکرده‌ایم"),
        _tile(num(_val(cad, "days_since_last", 0)), "روز از آخرین خرید",
              (f"ریتم خودش {num(_val(cad, 'effective_gap'))} روز"
               if _val(cad, "effective_gap") is not None else "")),
        _tile(num(_val(qual, "complaints_open", 0)), "شکایت باز",
              f"{num(_val(qual, 'complaints_total', 0))} شکایت در کل · "
              f"{num(_val(qual, 'complaints_rejected', 0))} ردشده"),
    ]
    return ('<div class="sect">یک نگاه</div>'
            f'<div class="grid">{"".join(tiles)}</div>')


def _section_action(ctx, cid, action, quad, signals) -> str:
    """The recommendation, if the aggregator ran. Without it the page still
    stands — the signals and the evidence are the substance; the action is the
    sentence written on top of them."""
    if action is None:
        return (
            '<div class="sect">تصمیم پیشنهادی</div>'
            '<div class="note">این صفحه بدون مرحله تجمیع ساخته شده است. برای دیدن '
            'اقدام پیشنهادی و متن آن، دستور را با <code>--actions</code> اجرا کنید. '
            'سیگنال‌ها و شواهد زیر مستقل از مدل زبانی محاسبه شده‌اند.</div>'
            f'<article class="card"><h3>دسته‌بندی: {_e(BUCKET_LABEL_FA[quad["bucket"]])}</h3>'
            f'<div>{_e(quad["bucket_reason_fa"])}</div></article>'
        )
    d = action.detail or {}
    chips = []
    if d.get("credit_room"):
        chips.append(f'<span class="tag">اعتبار: {_e(CREDIT_STATE_FA.get(d["credit_room"], d["credit_room"]))}</span>')
    if d.get("open_investigation"):
        from .aggregate.aggregator import gate_label_fa

        pending = d["open_investigation"] == "pending"
        # Shown in both states, unlike the stance chip below: "no open complaint"
        # is itself the answer to the question the reader is asking — may I take
        # this step today? Silence would read as "not checked".
        chips.append(
            f'<span class="tag{" p-high" if pending else ""}">'
            f'{_e(gate_label_fa("open_investigation", d["open_investigation"]))}</span>'
        )
    stance = d.get("relationship_stance")
    stance_note = ""
    if stance and stance != "neutral":
        from .llm.blocks.resolution import RELATIONSHIP_STANCE_FA

        chips.append(
            f'<span class="tag">سابقه: {_e(STANCE_LABEL_FA.get(stance, stance))}</span>'
        )
        if RELATIONSHIP_STANCE_FA.get(stance):
            stance_note = (f'<div class="sig-meta">{_e(RELATIONSHIP_STANCE_FA[stance])}'
                           "</div>")
    return f"""
<div class="sect">تصمیم پیشنهادی</div>
<article class="card">
  <div class="row">
    <span class="tag p-{"urgent" if action.priority == "فوری" else "high"}">{_e(action.priority)}</span>
    <span class="tag {BUCKET_CLASS.get(action.bucket, "")}">{_e(BUCKET_LABEL_FA.get(action.bucket, action.bucket))}</span>
    <span class="tag">مسئول: {_e(action.owner)}</span>
    {"".join(chips)}
  </div>
  <h3>{_e(action.title_fa)}</h3>
  <div>{_e(action.rationale_fa)}</div>
  <div class="step">قدم بعدی: {_e(action.recommended_step_fa)}</div>
  {stance_note}
  <div class="sig-meta">شواهد این اقدام: {_evrefs(action.evidence_ids)}</div>
</article>"""


def _section_signals(signals, st) -> str:
    if not signals:
        return ('<div class="sect">چه چیزی فعال شده</div>'
                '<article class="card">هیچ آشکارسازی روی این مشتری فعال نشده است.</article>')
    rows = []
    for s in signals:
        cls = "sev-hi" if s.severity >= 70 else ("sev-mid" if s.severity >= 40 else "")
        meta = [f"{CATEGORY_FA.get(s.category, s.category)} · {s.detector}",
                f"ارزش در معرض: {money(s.value_at_stake, st)} ریال"]
        if s.detail.get("stake_basis"):
            meta.append(f"مبنای مبلغ: {s.detail['stake_basis']}")
        if s.detail.get("falsifiable") is False:
            meta.append("این ادعا در داده رد قابل بررسی ندارد — «سابقه‌ای ثبت نشده»")
        if s.detail.get("caveat"):
            meta.append(str(s.detail["caveat"]))
        rows.append(f"""
<div class="sig">
  <div class="sev {cls}">{s.severity:.0f}</div>
  <div class="sig-body">
    <div>{_e(s.headline_fa)}</div>
    <div class="sig-meta">{_e(" · ".join(meta))}</div>
    <div class="sig-meta">{_evrefs(s.evidence_ids)}</div>
  </div>
</div>""")
    return ('<div class="sect">چه چیزی فعال شده'
            '<span class="hint">به ترتیب شدت — ترتیب صف کل دفتر جداگانه محاسبه می‌شود</span>'
            f'</div><article class="card">{"".join(rows)}</article>')


def _section_loops(ctx, cid) -> str:
    """The four open loops, said plainly — including the ones that are closed,
    because "we owe this customer nothing right now" is also an answer the sales
    manager needs before a meeting."""
    r = ctx.table("open_loops").loc[cid]
    items = []

    def loop(open_: bool, title: str, detail: str) -> None:
        items.append(f'<div class="loop{"" if open_ else " clear"}">'
                     f'<strong>{_e(title)}</strong><br>{_e(detail)}</div>')

    loop(r["dev_approved_open"] > 0, "نمونه تأییدشده بدون آفر",
         (f"{num(r['dev_approved_open'])} درخواست، قدیمی‌ترین "
          f"{num(r['dev_approved_open_days'])} روز — {', '.join(r['dev_approved_open_ids'])}")
         if r["dev_approved_open"] > 0 else "موردی باز نیست.")
    loop(r["dev_rejected_unspoken"] > 0, "رد فنی اعلام‌نشده",
         (f"{num(r['dev_rejected_unspoken'])} درخواست، قدیمی‌ترین "
          f"{num(r['dev_rejected_unspoken_days'])} روز — {', '.join(r['dev_rejected_unspoken_ids'])}")
         if r["dev_rejected_unspoken"] > 0 else "موردی باز نیست.")
    if r["next_action_open"]:
        proof = ("هیچ ردی از انجام آن در آفرها یا درخواست‌های توسعه نیست"
                 if r["next_action_trace_exists"]
                 else "این نوع اقدام در داده رد قابل بررسی ندارد")
        loop(True, "اقدام بعدی معلق در CRM",
             f"«{r['next_action_type']}» · {num(r['next_action_age_days'])} روز · "
             f"{r['next_action_id']} — {proof}")
    elif not isinstance(r["next_action_type"], str):
        loop(False, "اقدام بعدی معلق در CRM", "تعامل CRM ثبت‌شده‌ای برای این مشتری نیست.")
    elif r["next_action_type"] == "بدون اقدام":
        loop(False, "اقدام بعدی معلق در CRM",
             "آخرین تعامل CRM اقدام بعدی ثبت نکرده است — چیزی معلق نیست.")
    else:
        loop(False, "اقدام بعدی معلق در CRM",
             f"«{r['next_action_type']}» ثبت شده بود و پس از آن آفر یا درخواست توسعه "
             "ثبت شده — حلقه بسته است.")
    loop(r["offers_abandoned"] > 0, "آفر رهاشده پس از مهلت اعتبار",
         (f"{num(r['offers_abandoned'])} آفر، قدیمی‌ترین {num(r['offers_abandoned_days'])} "
          f"روز — {', '.join(r['offers_abandoned_ids'][:8])}")
         if r["offers_abandoned"] > 0 else "موردی باز نیست.")

    return ('<div class="sect">حلقه‌های باز از سمت ما'
            '<span class="hint">کارهایی که برای انجامشان به هیچ اطلاعات تازه‌ای '
            'از مشتری نیاز نیست</span></div>'
            f'<article class="card">{"".join(items)}</article>')


def _section_tools(ctx, cid: str) -> str:
    """What each tool answered, if the tools were run.

    Nothing here is new evidence — the tools minted it into the same registry,
    so it is already expandable in the section below. This section only groups it
    by the question that was asked, which is how a person reads a file: "what do
    we know about their complaints" rather than "evidence 14 through 22".
    """
    results = [
        r for (_tool, customer, _args), r in ctx.cache.get("tools", {}).items()
        if customer == cid
    ]
    if not results:
        return ""
    blocks = []
    for r in sorted(results, key=lambda r: r.tool):
        if r.empty:
            body = f'<div class="sig-meta">{_e(r.empty_reason_fa)}</div>'
        else:
            items = "".join(
                f'<li>{_e(claim)} <a class="evref" href="#{_e(eid)}">{_e(eid)}</a></li>'
                for eid, claim in zip(r.evidence_ids, r.claims)
            )
            body = f'<ul class="ev">{items}</ul>'
        note = f'<div class="sig-meta">{_e(r.note_fa)}</div>' if r.note_fa else ""
        blocks.append(f'<article class="card"><h3>{_e(r.tool)}</h3>{note}{body}</article>')
    return ('<div class="sect">پاسخ ابزارها'
            '<span class="hint">همان شواهد، این بار گروه‌بندی‌شده بر اساس سوالی که '
            'پرسیده شده</span></div>' + "".join(blocks))


def _section_evidence(ctx, ds, cid, max_rows: int) -> str:
    """Every claim, each expandable to the rows it rests on. This is the section
    the whole page exists for."""
    blocks = []
    for ev in ctx.evidence.for_customer(cid):
        blocks.append(_evidence_details(ev, ds, max_rows))
    return ('<div class="sect">شواهد — هر ادعا و ردیف‌های پشت آن'
            f'<span class="hint">{len(blocks)} شاهد · حداکثر {max_rows} ردیف از هرکدام '
            'نمایش داده می‌شود</span></div>' + "".join(blocks))


def _evidence_details(ev: Evidence, ds, max_rows: int) -> str:
    marks = []
    if ev.provenance.get("assumption"):
        marks.append('<span class="assume">⚠ مبتنی بر فرض</span>')
    if ev.confidence < 1.0:
        marks.append(f'<span class="assume">اطمینان {ev.confidence:.2f}</span>')

    try:
        frame = resolve(ev, ds)
        body = (_rows_table(frame, max_rows) if len(frame)
                else '<div class="empty">این شاهد به هیچ ردیفی نمی‌رسد — '
                     'باید بررسی شود.</div>')
    except Exception as exc:                      # noqa: BLE001 — show, don't hide
        body = f'<div class="empty">ردیف‌ها بازیابی نشد: {_e(type(exc).__name__)} {_e(exc)}</div>'

    window = (f"{ev.window[0].isoformat()} تا {ev.window[1].isoformat()}"
              if ev.window else "—")
    caveat = ev.provenance.get("caveat") or ev.provenance.get("caveat_fa") or ""
    return f"""
<details class="evd" id="{_e(ev.id)}">
  <summary>{_e(ev.claim_fa)} {" ".join(marks)}</summary>
  <dl class="kv">
    <dt>شناسه</dt><dd><code>{_e(ev.id)}</code></dd>
    <dt>مقدار</dt><dd>{_e(_cell(ev.value))} {_e(ev.unit or "")}</dd>
    <dt>بازه</dt><dd>{_e(window)}</dd>
    <dt>ارجاع</dt><dd>{_e(ev.source_rows)}</dd>
  </dl>
  <div class="formula">{_e(ev.provenance.get("formula", ""))}</div>
  {f'<div class="sig-meta">{_e(caveat)}</div>' if caveat else ""}
  {body}
</details>"""


# ------------------------------------------------------------------- entry point
def build_state(
    settings: Settings, *, with_actions: bool, customer_id: str | None = None,
    with_tools: bool = False, **options
) -> dict:
    """Run the pipeline **on the whole book**, far enough for the page.

    Never subset: the bucket threshold is the book's median revenue, the RFM
    scores are quintiles of the book, and the peer cohorts are the book. A
    one-customer run would produce numbers that are individually true and
    collectively meaningless.

    ``with_actions`` extends the run to the aggregator, bounded by ``only`` to
    this one account. Without that bound the account would usually get no action
    at all — the queue stops at the book's top 25 and most customers are not in
    it — while lifting the bound would mean 500-odd drafting calls to print one.
    The rank on the action is still the book-wide rank; only the drafting is
    narrowed.
    """
    from .llm.graph import run_pipeline

    if with_actions and customer_id:
        options["only"] = [customer_id]
    state = run_pipeline(
        settings=settings,
        as_of=settings.as_of,
        stop_after=None if with_actions else "quadrant",
        **options,
    )
    if with_tools and customer_id:
        run_all_tools(state["ctx"], customer_id)
    return state


def run_all_tools(ctx, customer_id: str) -> list:
    """Every tool, once, for one customer — memoised on the context.

    Ordered by name so the page and the CLI list them the same way, and so a
    second call cannot produce a different set of evidence ids.
    """
    from .tools import all_tools, run_tool

    return [run_tool(ctx, spec.name, customer_id)
            for spec in sorted(all_tools(), key=lambda s: s.name)]


def write_customer_page(
    customer_id: str, state: dict, *, settings: Settings,
    max_rows: int = 25, path: Path | None = None,
) -> Path:
    path = path or Path(settings.out_dir) / (
        f"customer_{customer_id}_{settings.as_of.isoformat()}.html"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_customer(customer_id, state, settings=settings, max_rows=max_rows),
        encoding="utf-8",
    )
    return path
