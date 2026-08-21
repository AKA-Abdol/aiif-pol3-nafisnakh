import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useApp, useLink } from "../state/app";
import type { CustomerDossier, Signal, ToolResult } from "../api/types";
import { EvidenceChips } from "../components/Evidence";
import {
  BUCKET_MEANING_FA, BucketPill, CATEGORY_FA, Empty, GateBadge, RelationshipPanel,
  SeverityBar, Skeleton, fmtMoney, fmtNum,
} from "../components/bits";

type Tab = "signals" | "loops" | "tools" | "evidence";

const LOOP_LABELS: Array<{ count: string; days: string; ids: string; fa: string }> = [
  { count: "dev_approved_open", days: "dev_approved_open_days", ids: "dev_approved_open_ids", fa: "نمونهٔ تأییدشده که هرگز قیمت نخورد" },
  { count: "dev_rejected_unspoken", days: "dev_rejected_unspoken_days", ids: "dev_rejected_unspoken_ids", fa: "رد فنی که به مشتری اعلام نشد" },
  { count: "offers_abandoned", days: "offers_abandoned_days", ids: "offers_abandoned_ids", fa: "آفر بی‌پاسخ گذشته از مهلت اعتبار" },
];

function num(d: Record<string, unknown>, k: string): number | null {
  const v = d[k];
  return typeof v === "number" ? v : null;
}

export default function DossierPage() {
  const { id = "" } = useParams();
  const { asOf, indexEvidence } = useApp();
  const link = useLink();
  const [tab, setTab] = useState<Tab>("signals");

  const q = useQuery({
    queryKey: ["customer", asOf, id],
    queryFn: () => api.customer(id, asOf),
  });

  // Lazily — only once the tab is actually opened (API.md §657).
  const toolsQ = useQuery({
    queryKey: ["customer-tools", asOf, id],
    queryFn: () => api.customerTools(id, asOf),
    enabled: tab === "tools",
  });

  useEffect(() => {
    if (q.data?.evidence) indexEvidence(q.data.evidence);
  }, [q.data, indexEvidence]);

  if (q.isLoading) return <div className="wrap"><Skeleton h={120} n={4} /></div>;
  if (q.isError) return <div className="wrap"><div className="notice bad">{(q.error as ApiError).fa}</div></div>;
  const d = q.data as CustomerDossier;

  const loops = LOOP_LABELS.map((l) => ({ ...l, n: num(d.open_loops, l.count) ?? 0, age: num(d.open_loops, l.days) }));
  const openLoopKinds = loops.filter((l) => l.n > 0).length + (d.open_loops.next_action_open === true ? 1 : 0);
  const revenue = num(d.payment, "billed");
  const margin = num(d.payment, "net_finance_effect");

  return (
    <div className="wrap">
      <div className="pagehead">
        <div>
          <div className="rowsplit">
            <h1 className="mono">{d.customer_id}</h1>
            <BucketPill bucket={d.bucket} title />
            <GateBadge
              gates={{
                credit_room: (d.payment.credit_room_state as never) ?? undefined,
                open_investigation: (num(d.quality, "complaints_open") ?? 0) > 0 ? "pending" : "clear",
              }}
            />
          </div>
          <div className="sub" style={{ maxWidth: "72ch" }}>{d.bucket_reason_fa || BUCKET_MEANING_FA[d.bucket]}</div>
        </div>
        <div className="btnrow">
          <Link className="btn" to={link(`/customers/${id}/meeting`)}>آماده‌سازی جلسه</Link>
          <a className="btn" href={api.pageUrl(id, asOf)} target="_blank" rel="noreferrer">نسخهٔ قابل ارسال ↗</a>
        </div>
      </div>

      {/* ------------------------------------------------ seven glance tiles */}
      <div className="tiles" style={{ marginBottom: 18 }}>
        <div className="tile">
          <div className="k">سطل راهبردی</div>
          <div className="v" style={{ fontSize: 19 }}><BucketPill bucket={d.bucket} /></div>
          <div className="n">{BUCKET_MEANING_FA[d.bucket]}</div>
        </div>
        <div className="tile">
          <div className="k">جایگاه در دفتر (RFM)</div>
          <div className="v mono">{String(d.rfm.rfm_cell ?? "—")}</div>
          <div className="n">{String(d.rfm.rfm_segment_fa ?? "")}</div>
        </div>
        <div className="tile">
          <div className="k">آخرین خرید</div>
          <div className="v num">{fmtNum(d.rfm.recency_days)}</div>
          <div className="n">روز پیش · {String(d.rfm.last_purchase ?? "—")}</div>
        </div>
        <div className="tile">
          <div className="k">درآمد / اثر خالص مالی</div>
          <div className="v num">{fmtMoney(revenue)}</div>
          <div className="n" style={{ color: (margin ?? 0) < 0 ? "var(--crit)" : undefined }}>
            {fmtMoney(margin)} ریال اثر خالص
          </div>
        </div>
        <div className="tile">
          <div className="k">سقف اعتبار</div>
          <div className="v" style={{ fontSize: 19, color: d.payment.credit_room_state === "exhausted" ? "var(--crit)" : undefined }}>
            {d.payment.credit_room_state === "exhausted" ? "پر شده" : d.payment.credit_room_state === "open" ? "باز" : "نامشخص"}
          </div>
          <div className="n">اشغال {fmtNum((num(d.payment, "exposure_ratio") ?? 0) * 100)}٪ · مانده {fmtMoney(num(d.payment, "open_exposure"))}</div>
        </div>
        <div className="tile">
          <div className="k">حلقهٔ باز از سمت ما</div>
          <div className="v num" style={{ color: openLoopKinds > 0 ? "var(--warn)" : "var(--accent)" }}>{openLoopKinds}</div>
          <div className="n">{openLoopKinds === 0 ? "الان چیزی بدهکار نیستیم" : `${fmtNum(d.open_loops.open_loop_count)} مورد در ${openLoopKinds} نوع`}</div>
        </div>
        <div className="tile">
          <div className="k">شکایت باز</div>
          <div className="v num" style={{ color: (num(d.quality, "complaints_open") ?? 0) > 0 ? "var(--warn)" : "var(--accent)" }}>
            {fmtNum(d.quality.complaints_open)}
          </div>
          <div className="n">از {fmtNum(d.quality.complaints_total)} شکایت · قدیمی‌ترین {fmtNum(d.quality.oldest_open_age_days)} روز</div>
        </div>
      </div>

      <RelationshipPanel r={d.relationship} />

      {/* ------------------------------------------------------------- tabs */}
      <div className="filters" style={{ borderBottom: "1px solid var(--rule)", paddingBottom: 10 }}>
        {([
          ["signals", `سیگنال‌ها (${d.signals.length})`],
          ["loops", "حلقه‌های باز"],
          ["tools", "آنچه سیستم دیده"],
          ["evidence", `همهٔ شواهد (${d.evidence.length})`],
        ] as Array<[Tab, string]>).map(([k, label]) => (
          <button key={k} className={tab === k ? "primary sm" : "ghost sm"} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "signals" && <SignalList signals={d.signals} />}
      {tab === "loops" && <Loops d={d} loops={loops} />}
      {tab === "evidence" && <EvidenceList d={d} />}
      {tab === "tools" && (
        toolsQ.isLoading ? <Skeleton h={110} n={4} />
        : toolsQ.isError ? <div className="notice bad">{(toolsQ.error as ApiError).fa}</div>
        : <ToolCards results={toolsQ.data?.results ?? []} />
      )}
    </div>
  );
}

function SignalList({ signals }: { signals: Signal[] }) {
  if (!signals.length) return <Empty>هیچ آشکارسازی روی این مشتری فعال نشده است.</Empty>;
  const sorted = [...signals].sort((a, b) => b.severity - a.severity);
  return (
    <div className="stack">
      {sorted.map((s) => (
        <div key={s.id} className="card">
          <div className="rowsplit">
            <span className={`pill ${s.category}`}>{CATEGORY_FA[s.category]}</span>
            <span className="tag">{s.detector}</span>
            <span className="spacer" />
            <SeverityBar severity={s.severity} category={s.category} />
            <span className="small muted">در معرض خطر: <b className="num">{fmtMoney(s.value_at_stake)}</b></span>
          </div>
          <p style={{ margin: "10px 0 8px", fontWeight: 500 }}>{s.headline_fa}</p>
          <EvidenceChips ids={s.evidence_ids} />
        </div>
      ))}
    </div>
  );
}

function Loops({ d, loops }: { d: CustomerDossier; loops: Array<{ fa: string; n: number; age: number | null; ids: string }> }) {
  const nextOpen = d.open_loops.next_action_open === true;
  const active = loops.filter((l) => l.n > 0);
  if (!active.length && !nextOpen) {
    return <div className="notice good">الان به این مشتری چیزی بدهکار نیستیم — هیچ حلقهٔ بازی از سمت ما نمانده است.</div>;
  }
  return (
    <div className="stack">
      {active.map((l) => (
        <div key={l.fa} className="card">
          <div className="rowsplit">
            <span className="pill fix">{fmtNum(l.n)} مورد</span>
            <h3 style={{ flex: 1 }}>{l.fa}</h3>
            {l.age !== null && <span className="small muted">قدیمی‌ترین <b className="num">{fmtNum(l.age)}</b> روز</span>}
          </div>
          {Array.isArray(d.open_loops[l.ids]) && (
            <div className="rowsplit" style={{ marginTop: 8, gap: 5 }}>
              {(d.open_loops[l.ids] as unknown as string[]).map((x) => <span key={x} className="tag">{x}</span>)}
            </div>
          )}
        </div>
      ))}
      {nextOpen && (
        <div className="card">
          <div className="rowsplit">
            <span className="pill fix">اقدام بعدی</span>
            <h3 style={{ flex: 1 }}>{String(d.open_loops.next_action_type ?? "اقدام ثبت‌شده")} — انجام نشده</h3>
            <span className="small muted"><b className="num">{fmtNum(d.open_loops.next_action_age_days)}</b> روز</span>
          </div>
          <p className="small muted" style={{ margin: "8px 0 0" }}>
            ثبت‌شده در {String(d.open_loops.next_action_at ?? "—")} · شناسه{" "}
            <span className="tag">{String(d.open_loops.next_action_id ?? "—")}</span>
            {d.open_loops.next_action_trace_exists === false && " · سابقه‌ای از پیگیری در داده نیست (ادعای ضعیف‌تر و صادقانه‌تر)"}
          </p>
        </div>
      )}
    </div>
  );
}

function ToolCards({ results }: { results: ToolResult[] }) {
  if (!results.length) return <Empty>ابزاری اجرا نشد.</Empty>;
  return (
    <div className="grid2">
      {results.map((r) => (
        <div key={r.tool} className="card">
          <div className="rowsplit"><span className="tag">{r.tool}</span></div>
          {r.claims.length ? (
            <ul style={{ margin: "10px 0 0", paddingInlineStart: 18 }}>
              {r.claims.map((c, i) => (
                <li key={i} style={{ marginBottom: 7 }}>
                  {c}{" "}
                  {r.evidence_ids[i] && <EvidenceChips ids={[r.evidence_ids[i]]} />}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small" style={{ marginTop: 10 }}>{r.empty_reason_fa || "چیزی پیدا نشد."}</p>
          )}
          {r.note_fa && <p className="tiny muted" style={{ marginTop: 10, borderTop: "1px solid var(--rule)", paddingTop: 8 }}>{r.note_fa}</p>}
        </div>
      ))}
    </div>
  );
}

function EvidenceList({ d }: { d: CustomerDossier }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr><th>شناسه</th><th>نوع</th><th className="wrap">ادعا</th><th>مقدار</th><th></th></tr>
        </thead>
        <tbody>
          {d.evidence.map((e) => (
            <tr key={e.id}>
              <td><EvidenceChips ids={[e.id]} /></td>
              <td className="muted small">{e.kind}</td>
              <td className="wrap" style={{ maxWidth: 520 }}>{e.claim_fa}</td>
              <td className="num">{typeof e.value === "number" ? fmtNum(e.value, 2) : String(e.value ?? "—")} {e.unit ?? ""}</td>
              <td>
                {e.confidence < 1 && <span className="pill danger">اطمینان {e.confidence.toFixed(1)}</span>}
                {e.provenance?.assumption === true && <span className="pill fix">فرض</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
