import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useApp, useLink } from "../state/app";
import type { CustomerAction, CustomerDossier, Signal, ToolResult } from "../api/types";
import { EvidenceChips, WithEvidence } from "../components/Evidence";
import {
  BUCKET_MEANING_FA, BucketPill, CATEGORY_FA, Empty, GateBadge,
  RelationshipPanel, RunHint, SeverityBar, Skeleton, fmtMoney, fmtNum,
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

      <ActionPanel id={id} />

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

/** The one account's action, built on demand.
 *
 *  The daily queue stops at `top_n`, so most accounts reach this page with every
 *  input computed and no action written. The free GET says whether one is
 *  already on disk; only the button spends anything, and what it spends is
 *  printed on it before it is pressed. The result is cached server-side, so the
 *  second visit renders from `status: "ready"` without a mutation at all. */
function ActionPanel({ id }: { id: string }) {
  const { asOf } = useApp();
  const qc = useQueryClient();
  const [confirmRefresh, setConfirmRefresh] = useState(false);

  const key = ["customer-action", asOf, id] as const;
  const q = useQuery({ queryKey: key, queryFn: () => api.customerAction(id, asOf) });

  // A mutation, never a query: this must not fire on mount, on refocus, or on a
  // retry. Its result is written straight into the query cache so navigating
  // away and back shows the action without asking the server again.
  const build = useMutation({
    mutationFn: (refresh: boolean) => api.buildCustomerAction(id, asOf, refresh),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      setConfirmRefresh(false);
      // The synthesis it just paid for belongs on the dossier's own panel too.
      qc.invalidateQueries({ queryKey: ["customer", asOf, id] });
    },
  });

  if (q.isLoading) return <Skeleton h={120} />;
  if (q.isError) return <div className="notice bad">{(q.error as ApiError).fa}</div>;

  const data = q.data as CustomerAction;
  const res = data.result;
  const a = res?.action ?? null;

  if (!a) {
    const failed = data.status === "dropped" || (res?.dropped?.length ?? 0) > 0;
    return (
      <div className="card" style={{ marginBottom: 18 }}>
        <div className="rowsplit">
          <h3 style={{ flex: 1 }}>اقدام پیشنهادی برای این مشتری</h3>
          {build.isPending && <span className="tag">در حال ساخت…</span>}
        </div>

        {failed ? (
          <div className="notice bad" style={{ marginTop: 10 }}>
            متنی ساخته شد ولی از اعتبارسنجی شواهد رد نشد و منتشر نشده است — عددی در آن
            بود که در هیچ شاهدی نیامده بود. سیستم ترجیح داده چیزی نگوید تا چیز
            بی‌پشتوانه بگوید.
            {res?.dropped?.map((x, i) => (
              <div key={i} className="tiny" style={{ marginTop: 6, opacity: 0.85 }}>
                {x.issues?.map((y) => y.detail).join(" · ") || x.reason}
              </div>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ margin: "10px 0 0" }}>
            صف روزانه فقط برای بالای دفتر ساخته می‌شود و این حساب در آن نبوده است. با
            دکمهٔ زیر، اقدام پیشنهادی همین حالا برای همین یک مشتری ساخته می‌شود.
          </p>
        )}

        {build.isError && (
          <div className="notice bad" style={{ marginTop: 10 }}>{(build.error as ApiError).fa}</div>
        )}

        <div className="btnrow" style={{ marginTop: 12 }}>
          <button className="primary" disabled={build.isPending} onClick={() => build.mutate(false)}>
            {build.isPending ? "در حال ساخت…" : failed ? "دوباره بساز" : "ساخت اقدام برای این مشتری"}
          </button>
        </div>
        <RunHint>چند ثانیه طول می‌کشد. نتیجه ذخیره می‌شود و دفعهٔ بعد بی‌درنگ باز می‌شود.</RunHint>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 18 }}>
      <div className="rowsplit">
        <span className="pill danger">{a.priority}</span>
        <BucketPill bucket={a.bucket} title />
        <h3 style={{ flex: 1, margin: 0 }}>{a.title_fa}</h3>
        <span className="small muted">در معرض خطر <b className="num">{fmtMoney(a.value_at_stake)}</b></span>
        <span className="tag">رتبه در دفتر #{a.rank}</span>
      </div>

      <div className="notice good" style={{ marginTop: 12 }}>
        <strong>قدم بعدی:</strong> {a.recommended_step_fa}
        <div className="tiny" style={{ marginTop: 6, opacity: 0.85 }}>مسئول: {a.owner}</div>
      </div>

      <div className="rowsplit" style={{ gap: 5, marginTop: 10 }}>
        {a.signals.map((x) => <span key={x} className="tag">{x}</span>)}
        {a.source === "rules" && <span className="pill fix">متن قالبی — مدل در دسترس نبود</span>}
      </div>

      <details className="sect" style={{ marginTop: 10 }}>
        <summary>چرا؟</summary>
        <p style={{ lineHeight: 2 }}><WithEvidence text={a.rationale_fa} /></p>
        <EvidenceChips ids={a.evidence_ids} />
      </details>

      <div className="rowsplit" style={{ marginTop: 12, borderTop: "1px solid var(--rule)", paddingTop: 10 }}>
        {/* When it was written is a fact about the advice; how it was produced
            is our bookkeeping and stays off the page. */}
        <span className="tiny muted">
          {res?.computed_at ? `ساخته‌شده در ${res.computed_at.slice(0, 10)}` : ""}
        </span>
        <span className="spacer" />
        {confirmRefresh ? (
          <>
            <span className="tiny muted">متن از نو نوشته می‌شود.</span>
            <button className="sm" disabled={build.isPending} onClick={() => build.mutate(true)}>
              {build.isPending ? "…" : "تأیید"}
            </button>
            <button className="ghost sm" onClick={() => setConfirmRefresh(false)}>انصراف</button>
          </>
        ) : (
          <button className="ghost sm" onClick={() => setConfirmRefresh(true)}>ساخت دوباره</button>
        )}
      </div>
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
