import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useApp, useLink } from "../state/app";
import type { AgentSpec, Finding, MeetingPlan, MeetingResult } from "../api/types";
import { EvidenceChips, WithEvidence } from "../components/Evidence";
import { Empty, GateBadge, RunHint, Skeleton } from "../components/bits";

const SECONDS_PER_AGENT = 12;

/** `as_of + id + agents`, exactly the key API.md §722 asks for. */
const meetingKey = (asOf: string, id: string, agents: string[]) =>
  ["meeting", asOf, id, [...agents].sort().join(",")] as const;

export default function MeetingPage() {
  const { id = "" } = useParams();
  const { asOf, indexEvidence } = useApp();
  const link = useLink();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<Set<string> | null>(null);

  const plan = useQuery({
    queryKey: ["meeting-plan", asOf, id],
    queryFn: () => api.meetingPlan(id, asOf),
  });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents, staleTime: Infinity });

  // Pull the dossier so evidence chips inside findings can show their claim.
  const dossier = useQuery({ queryKey: ["customer", asOf, id], queryFn: () => api.customer(id, asOf) });
  useEffect(() => {
    if (dossier.data?.evidence) indexEvidence(dossier.data.evidence);
  }, [dossier.data, indexEvidence]);

  // The run stays a mutation — it must never fire on its own — but its result
  // is written into the query cache so that leaving the page and coming back
  // does not charge for the same briefing twice.
  const run = useMutation({
    mutationFn: (names: string[]) => api.runMeeting(id, names, asOf),
    onSuccess: (data, names) => qc.setQueryData(meetingKey(asOf, id, names), data),
  });

  const agentMap = useMemo(() => {
    const m = new Map<string, AgentSpec>();
    agents.data?.agents.forEach((a) => m.set(a.name, a));
    return m;
  }, [agents.data]);

  const selected = useMemo(() => {
    if (!plan.data) return [] as string[];
    const all = plan.data.routed.map((r) => r.agent);
    return picked ? all.filter((a) => picked.has(a)) : all;
  }, [plan.data, picked]);

  // A briefing already paid for, for this exact set of analysts.
  const cachedRun = qc.getQueryData<MeetingResult>(meetingKey(asOf, id, selected));
  const result = run.data ?? cachedRun;

  const toggle = (name: string) => {
    const base = new Set(picked ?? plan.data?.routed.map((r) => r.agent) ?? []);
    if (base.has(name)) base.delete(name);
    else base.add(name);
    setPicked(base);
  };

  if (plan.isLoading) return <div className="wrap"><Skeleton h={110} n={3} /></div>;
  if (plan.isError) return <div className="wrap"><div className="notice bad">{(plan.error as ApiError).fa}</div></div>;
  const p = plan.data as MeetingPlan;

  const eta = Math.round(selected.length * SECONDS_PER_AGENT);

  return (
    <div className="wrap">
      <div className="pagehead">
        <div>
          <h1>آماده‌سازی جلسه</h1>
          <div className="sub">
            مشتری <Link className="mono" to={link(`/customers/${id}`)}>{id}</Link> · تاریخ مبنا{" "}
            <span className="mono">{asOf}</span>
          </div>
        </div>
        <GateBadge gates={p.gates} />
      </div>

      {p.constraints.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h3 style={{ marginBottom: 8 }}>قیدهایی که به همهٔ تحلیل‌گرها داده می‌شود</h3>
          {p.constraints.map((c, i) => (
            <div key={i} className="notice" style={{ marginBottom: 8 }}>{c}</div>
          ))}
        </div>
      )}

      {/* ------------------------------------------- step 1 — the free plan */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="rowsplit" style={{ marginBottom: 10 }}>
          <h3 style={{ flex: 1 }}>مرحلهٔ ۱ — تصمیم روتر</h3>
        </div>

        <div className="stack">
          {p.routed.map((r) => {
            const on = selected.includes(r.agent);
            return (
              <label
                key={r.agent}
                className="card"
                style={{
                  cursor: "pointer", margin: 0,
                  borderInlineStartWidth: 3,
                  borderInlineStartColor: r.blocking ? "var(--crit)" : "var(--accent)",
                  background: on ? "var(--surface)" : "var(--surface-2)",
                }}
              >
                <div className="rowsplit">
                  <input type="checkbox" checked={on} onChange={() => toggle(r.agent)} />
                  <strong style={{ flex: 1 }}>{agentMap.get(r.agent)?.question_fa ?? r.agent}</strong>
                  {r.blocking && <span className="pill danger">بازدارنده</span>}
                  <span className="tag">وزن {r.weight}</span>
                </div>
                <p className="small dim" style={{ margin: "8px 0 0", paddingInlineStart: 26 }}>{r.reason_fa}</p>
              </label>
            );
          })}
        </div>

        {p.skipped.length > 0 && (
          <details className="sect" style={{ marginTop: 12 }}>
            <summary>{p.skipped.length} تحلیل‌گر اجرا نمی‌شود — چرا</summary>
            <div className="stack" style={{ marginTop: 8 }}>
              {p.skipped.map((s) => (
                <div key={s.agent} className="notice">
                  <strong>{agentMap.get(s.agent)?.question_fa ?? s.agent}</strong>
                  <div className="small" style={{ marginTop: 4 }}>{s.reason_fa}</div>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      {/* ------------------------------------------------ step 2 — the run */}
      {!result && (
        <div className="card">
          <div className="rowsplit" style={{ marginBottom: 10 }}>
            <h3 style={{ flex: 1 }}>مرحلهٔ ۲ — اجرای تحلیل‌گرها</h3>
          </div>
          <RunHint>
            {selected.length} تحلیل‌گر انتخاب شده · حدود {eta} ثانیه طول می‌کشد.
          </RunHint>
          <div className="btnrow" style={{ marginTop: 12 }}>
            <button
              className="primary"
              disabled={run.isPending || selected.length === 0}
              onClick={() => run.mutate(selected)}
            >
              {run.isPending ? "در حال اجرا…" : "ساخت دستور جلسه"}
            </button>
            {picked && (
              <button className="ghost" onClick={() => setPicked(null)}>بازگشت به انتخاب روتر</button>
            )}
          </div>
          {run.isPending && (
            <>
              <div className="notice info" style={{ marginTop: 12 }}>
                <span className="num">{selected.length}</span> تحلیل‌گر در حال اجرا — تخمین{" "}
                <span className="num">{eta}</span> ثانیه. صفحه را نبندید.
              </div>
              <div style={{ marginTop: 12 }}><Skeleton h={120} n={2} /></div>
            </>
          )}
          {run.isError && <div className="notice bad" style={{ marginTop: 12 }}>{(run.error as ApiError).fa}</div>}
        </div>
      )}

      {result && (
        <>
          <div className="rowsplit" style={{ margin: "18px 0 12px" }}>
            <h2 style={{ flex: 1 }}>دستور جلسه</h2>
            <button className="sm" onClick={() => navigator.clipboard.writeText(result.brief_fa)}>کپی متن</button>
            <button className="sm" onClick={() => window.print()}>چاپ</button>
            <button
              className="ghost sm"
              onClick={() => {
                // Rebuilding costs again, so the paid copy is discarded only on
                // an explicit click.
                qc.removeQueries({ queryKey: meetingKey(asOf, id, selected) });
                run.reset();
              }}
            >
              اجرای دوباره
            </button>
          </div>

          {Object.keys(result.errors).length > 0 && (
            <div className="notice bad" style={{ marginBottom: 12 }}>
              {Object.entries(result.errors).map(([k, v]) => <div key={k}>{k}: {v}</div>)}
            </div>
          )}

          {result.findings.length === 0 ? (
            <Empty>هیچ تحلیل‌گری یافته‌ای تولید نکرد.</Empty>
          ) : (
            <div className="stack">
              {[...result.findings]
                .sort((a, b) => Number(b.blocking) - Number(a.blocking) || b.weight - a.weight)
                .map((f) => <FindingCard key={f.agent} f={f} />)}
            </div>
          )}

          <details className="sect" style={{ marginTop: 18 }}>
            <summary>متن کامل دستور جلسه</summary>
            <pre className="brief">{result.brief_fa}</pre>
          </details>
        </>
      )}
    </div>
  );
}

function FindingCard({ f }: { f: Finding }) {
  const dropped = f.dropped?.length > 0;
  return (
    <div
      className="card"
      style={{ borderInlineStartWidth: 3, borderInlineStartColor: f.blocking ? "var(--crit)" : "var(--rule)" }}
    >
      <div className="rowsplit">
        {f.blocking && <span className="pill danger">بازدارنده</span>}
        <h3 style={{ flex: 1 }}>{f.question_fa}</h3>
        {f.source === "rules" && <span className="pill fix">متن قالبی — مدل در دسترس نبود</span>}
      </div>

      <p className="tiny muted" style={{ margin: "6px 0 0" }}>چرا ارجاع شد: {f.trigger_fa}</p>

      {dropped ? (
        <div className="notice bad" style={{ marginTop: 10 }}>{f.headline_fa}</div>
      ) : (
        <>
          <p style={{ margin: "12px 0 8px", fontWeight: 600 }}>{f.headline_fa}</p>
          <p style={{ lineHeight: 2 }}><WithEvidence text={f.reasoning_fa} /></p>
          <div className="notice good" style={{ marginTop: 10 }}>
            <strong>قدم بعدی:</strong> {f.recommended_step_fa}
          </div>
        </>
      )}

      <details className="sect" style={{ marginTop: 8 }}>
        <summary>چه دید</summary>
        <div className="rowsplit" style={{ gap: 5, marginBottom: 8 }}>
          {f.tools_used.map((t) => <span key={t} className="tag">{t}</span>)}
        </div>
        {f.tools_reason_fa && <p className="small dim">{f.tools_reason_fa}</p>}
        <EvidenceChips ids={f.evidence_ids} />
      </details>
    </div>
  );
}
