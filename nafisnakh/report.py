"""The presentation artifact for the sales manager (PLAN §4, Phase 2).

A JSON action queue is the right *interface*; it is the wrong *artifact* for the
person who has to make the calls. This module renders the same queue as a
single self-contained RTL HTML file — no external stylesheet, no CDN, no font
download — so it opens from a shared drive, an email attachment, or a phone.

Three design decisions worth stating:

* **Evidence is visible, not hidden behind a tooltip.** Every claim in a card
  carries the id that backs it. The point of the whole system is that a
  recommendation can be interrogated; hiding the interrogation defeats it.
* **Assumptions are marked in the artifact itself.** Anything resting on Q7,
  Q11 or Q12 gets a visible marker. The sales manager should never learn from a
  meeting that a number was a config default.
* **The four buckets lead.** The strategy is fewer customers at higher, steadier
  margin, so the first thing on the page is how the book splits — not a total.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .aggregate.quadrant import BUCKET_LABEL_FA, BUCKET_MEANING_FA
from .config import Settings

PRIORITY_ORDER = ["فوری", "بالا", "متوسط", "پایین"]
PRIORITY_CLASS = {"فوری": "p-urgent", "بالا": "p-high",
                  "متوسط": "p-mid", "پایین": "p-low"}
BUCKET_CLASS = {"grow": "b-grow", "protect": "b-protect",
                "fix": "b-fix", "reduce": "b-reduce"}
HEALTH_CLASS = {"بحرانی": "h-crit", "در معرض خطر": "h-risk",
                "شکننده": "h-fragile", "سالم": "h-ok"}

CSS = """
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#16191d; --muted:#5b6472; --line:#e2e5ea;
  --accent:#1f5f8b; --urgent:#b3261e; --high:#b26a00; --mid:#1f5f8b; --low:#5b6472;
  --grow:#1e7a4b; --protect:#1f5f8b; --fix:#b26a00; --reduce:#6b7280;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#14171b; --card:#1c2026; --ink:#e8eaed; --muted:#9aa4b2; --line:#2a2f37;
         --accent:#7fb2d6; --urgent:#f2837a; --high:#e0a55a; --mid:#7fb2d6; --low:#9aa4b2;
         --grow:#5fc48c; --protect:#7fb2d6; --fix:#e0a55a; --reduce:#9aa4b2; }
}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--ink);direction:rtl;
  font-family:Vazirmatn,"IRANSans",Tahoma,"Segoe UI",system-ui,sans-serif;
  font-size:15px;line-height:1.75}
header{max-width:1080px;margin:0 auto 20px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px}
main{max-width:1080px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.tile .n{font-size:26px;font-weight:700;line-height:1.2}
.tile .l{color:var(--muted);font-size:12px}
.b-grow .n{color:var(--grow)} .b-protect .n{color:var(--protect)}
.b-fix .n{color:var(--fix)} .b-reduce .n{color:var(--reduce)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:16px 18px;margin-bottom:12px}
.card h3{margin:0 0 2px;font-size:16px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}
.tag{font-size:12px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);
  color:var(--muted);white-space:nowrap}
.p-urgent{color:#fff;background:var(--urgent);border-color:transparent}
.p-high{color:#fff;background:var(--high);border-color:transparent}
.p-mid{color:#fff;background:var(--mid);border-color:transparent}
.p-low{background:transparent}
.rank{font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px;min-width:2.2em}
.step{border-inline-start:3px solid var(--accent);padding-inline-start:10px;margin:10px 0 6px}
.ev{margin:8px 0 0;padding:0;list-style:none;font-size:13.5px}
.ev li{padding:5px 0;border-top:1px dashed var(--line);color:var(--muted)}
.ev code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
  direction:ltr;display:inline-block;color:var(--accent)}
.assume{color:var(--high);font-size:12px}
.health{font-size:13px;margin-top:8px;color:var(--muted)}
.h-crit{color:var(--urgent);font-weight:600} .h-risk{color:var(--high);font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}
th{color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:12px 16px;margin:16px 0}
summary{cursor:pointer;font-weight:600}
.note{background:var(--card);border:1px solid var(--line);border-inline-start:4px solid var(--high);
  border-radius:10px;padding:12px 16px;margin:16px 0;font-size:13.5px}
footer{max-width:1080px;margin:26px auto 0;color:var(--muted);font-size:12px}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _evidence_items(evidence_ids: list[str], registry) -> str:
    items = []
    for ev in registry.many(evidence_ids):
        marks = []
        if ev.provenance.get("assumption"):
            marks.append('<span class="assume">⚠ مبتنی بر فرض</span>')
        if ev.confidence < 1.0:
            marks.append(f'<span class="assume">اطمینان {ev.confidence:.1f}</span>')
        items.append(
            f"<li>{_e(ev.claim_fa)} <code>{_e(ev.id)}</code> {' '.join(marks)}</li>"
        )
    return "".join(items)


def render_html(
    queue,
    ctx,
    quadrants,
    *,
    settings: Settings,
    calibration=None,
    top_n: int | None = None,
) -> str:
    top_n = top_n or settings.top_n_actions
    counts = quadrants.counts()
    relationship = ctx.tables.get("relationship")

    tiles = "".join(
        f'<div class="tile {BUCKET_CLASS[b]}"><div class="n">{counts.get(b, 0)}</div>'
        f'<div class="l">{BUCKET_LABEL_FA[b]} — {_e(BUCKET_MEANING_FA[b])}</div></div>'
        for b in ("grow", "protect", "fix", "reduce")
    )

    cards = []
    for a in queue.actions[:top_n]:
        health_html = ""
        if relationship is not None and len(relationship) and a.customer_id in relationship.index:
            r = relationship.loc[a.customer_id]
            cls = HEALTH_CLASS.get(r["health"], "")
            promises = r["unmet_promises_fa"] or []
            health_html = (
                f'<div class="health">وضعیت رابطه: '
                f'<span class="{cls}">{_e(r["health"])}</span> · '
                f'محور: {_e(r["dominant_theme_fa"])} · لحن پیشنهادی: '
                f'{_e(r["recommended_tone_fa"])}'
                + (f'<br>معطل‌مانده از سمت ما: {_e("، ".join(promises))}' if promises else "")
                + "</div>"
            )
        cards.append(f"""
<article class="card">
  <div class="row">
    <span class="rank">{a.rank}.</span>
    <span class="tag {PRIORITY_CLASS.get(a.priority, '')}">{_e(a.priority)}</span>
    <span class="tag {BUCKET_CLASS.get(a.bucket, '')}">{_e(BUCKET_LABEL_FA.get(a.bucket, a.bucket))}</span>
    <strong>{_e(a.customer_id)}</strong>
    <span class="tag">مسئول: {_e(a.owner)}</span>
  </div>
  <h3>{_e(a.title_fa)}</h3>
  <div class="step">قدم بعدی: {_e(a.recommended_step_fa)}</div>
  {health_html}
  <div class="row" style="margin-top:8px">
    {"".join(f'<span class="tag">{_e(s)}</span>' for s in a.signals)}
  </div>
  <ul class="ev">{_evidence_items(a.evidence_ids, ctx.evidence)}</ul>
</article>""")

    calib_html = ""
    if calibration is not None and len(calibration.rows):
        rows = "".join(
            "<tr>" + "".join(f"<td>{_e(v)}</td>" for v in row) + "</tr>"
            for row in calibration.rows[
                ["detector", "fired", "eligible", "fire_rate", "status"]
            ].itertuples(index=False)
        )
        calib_html = f"""
<details>
  <summary>نرخ فعال‌شدن آشکارسازها (کالیبراسیون)</summary>
  <div class="scroll"><table>
    <tr><th>آشکارساز</th><th>فعال‌شده</th><th>جامعه واجد شرایط</th><th>نرخ</th><th>وضعیت</th></tr>
    {rows}
  </table></div>
</details>"""

    dropped_html = ""
    if queue.dropped:
        dropped_html = (
            f'<div class="note"><strong>{len(queue.dropped)}</strong> اقدام در '
            "اعتبارسنجی شواهد رد شد و در این گزارش نیامده است. "
            "این یعنی سامانه ترجیح داده چیزی نگوید تا اینکه ادعای بدون پشتوانه بگوید.</div>"
        )

    return f"""<title>صف اقدام فروش — نفیس نخ</title>
<style>{CSS}</style>
<header>
  <h1>صف اقدام فروش — نفیس نخ</h1>
  <div class="sub">تاریخ مبنا {_e(settings.as_of.isoformat())} ·
    {len(queue.actions)} اقدام از {len(quadrants.table)} مشتری ·
    هر ادعا با شناسه شاهد قابل ردیابی است</div>
</header>
<main>
  <div class="grid">{tiles}</div>
  {dropped_html}
  <div class="note">
    نشانه ⚠ یعنی آن عدد به پارامتری وابسته است که هنوز از نفیس نخ نگرفته‌ایم —
    هزینه سرمایه ماهانه (Q11)، نرخ هزینه خدمت‌رسانی (Q12) و بهای تمام‌شده واقعی (Q7).
    پیش از تصمیم قراردادی، این پارامترها باید نهایی شوند.
  </div>
  {''.join(cards)}
  {calib_html}
</main>
<footer>
  ترتیب صف در پایتون محاسبه می‌شود (شدت × لگاریتم ارزش در معرض خطر × وزن دسته)،
  نه توسط مدل زبانی. مدل فقط استدلال و قدم پیشنهادی را می‌نویسد و هیچ عددی نمی‌نویسد؛
  هر اقدامی که عددی خارج از شواهدش داشته باشد، پیش از انتشار حذف می‌شود.
</footer>"""


def write_report(
    queue, ctx, quadrants, *, settings: Settings, calibration=None,
    top_n: int | None = None, path: Path | None = None,
) -> Path:
    path = path or Path(settings.out_dir) / f"report_{settings.as_of.isoformat()}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_html(queue, ctx, quadrants, settings=settings,
                    calibration=calibration, top_n=top_n),
        encoding="utf-8",
    )
    return path
