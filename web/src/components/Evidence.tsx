import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import { useApp } from "../state/app";

/** Matches `[EV-...]` and bare `EV-...` inside model prose (API.md §708). */
const EV_RE = /\[?(EV-[A-Za-z0-9_-]+)\]?/g;

/** Turns evidence ids embedded in Persian prose into clickable chips. */
export function WithEvidence({ text }: { text: string }) {
  if (!text) return null;
  const parts = text.split(EV_RE);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? <EvidenceChip key={`${part}-${i}`} id={part} /> : <span key={i}>{part}</span>,
      )}
    </>
  );
}

export function EvidenceChip({ id, label }: { id: string; label?: ReactNode }) {
  const { evidenceIndex, showEvidence } = useApp();
  const known = evidenceIndex.get(id);
  const assumption = known?.provenance?.assumption === true;
  return (
    <button
      type="button"
      className={`evchip${assumption ? " assume" : ""}`}
      title={known ? known.claim_fa : id}
      onClick={(e) => {
        e.stopPropagation();
        showEvidence(id);
      }}
    >
      {label ?? id}
    </button>
  );
}

/** A row of chips for a signal / finding / action. */
export function EvidenceChips({ ids }: { ids: string[] }) {
  if (!ids?.length) return null;
  return (
    <div className="rowsplit" style={{ gap: 5 }}>
      {ids.map((id) => (
        <EvidenceChip key={id} id={id} />
      ))}
    </div>
  );
}

function toCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.join(","), ...rows.map((r) => columns.map((c) => esc(r[c])).join(","))].join("\n");
}

/** One global drawer for the whole app (API.md §696). */
export function EvidenceDrawer() {
  const { openEvidence, showEvidence, asOf, evidenceIndex } = useApp();

  useEffect(() => {
    if (!openEvidence) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && showEvidence(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openEvidence, showEvidence]);

  const rowsQ = useQuery({
    queryKey: ["evidence-rows", asOf, openEvidence],
    queryFn: () => api.evidenceRows(openEvidence!, asOf, 200),
    enabled: !!openEvidence,
    retry: false,
  });

  if (!openEvidence) return null;
  const cached = evidenceIndex.get(openEvidence);
  const data = rowsQ.data;
  const err = rowsQ.error as ApiError | undefined;

  const download = () => {
    if (!data) return;
    const blob = new Blob(["﻿" + toCsv(data.columns, data.rows)], {
      type: "text/csv;charset=utf-8",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${data.evidence_id}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <>
      <div className="drawer-back" onClick={() => showEvidence(null)} />
      <aside className="drawer" role="dialog" aria-label="شواهد">
        <div className="drawer-head">
          <div style={{ flex: 1 }}>
            <div className="mono tiny muted">{openEvidence}</div>
            <div style={{ fontWeight: 700, marginTop: 4 }}>
              {data?.claim_fa ?? cached?.claim_fa ?? "…"}
            </div>
            {cached?.provenance?.formula && (
              <div className="mono tiny muted" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
                {String(cached.provenance.formula)}
              </div>
            )}
            <div className="rowsplit" style={{ marginTop: 8, gap: 6 }}>
              {cached && <span className="tag">{cached.kind}</span>}
              {cached?.window && (
                <span className="tag">
                  {cached.window[0]} → {cached.window[1]}
                </span>
              )}
              {cached && cached.confidence < 1 && (
                <span className="pill danger">اطمینان {cached.confidence.toFixed(1)}</span>
              )}
              {cached?.provenance?.assumption === true && (
                <span className="pill fix">مبتنی بر فرض پیکربندی</span>
              )}
            </div>
          </div>
          <button className="ghost" onClick={() => showEvidence(null)} aria-label="بستن">
            ✕
          </button>
        </div>

        <div className="drawer-body">
          {rowsQ.isLoading && <div className="skel" style={{ height: 180 }} />}
          {err && <div className="notice bad">{err.fa}</div>}
          {data && (
            <>
              <div className="rowsplit small muted" style={{ marginBottom: 10 }}>
                <span>
                  شیت <b>{data.locator.sheet}</b> · کلید <span className="mono">{data.locator.key}</span>
                </span>
                <span className="spacer" />
                <span>
                  <b className="num">{data.rows.length}</b> از <b className="num">{data.n_rows}</b> ردیف
                </span>
              </div>
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      {data.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r, i) => (
                      <tr key={i}>
                        {data.columns.map((c) => (
                          <td key={c}>{r[c] === null || r[c] === undefined ? "—" : String(r[c])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data.n_rows > data.rows.length && (
                <p className="tiny muted" style={{ marginTop: 8 }}>
                  فقط {data.rows.length} ردیف اول نمایش داده شده است.
                </p>
              )}
            </>
          )}
        </div>

        <div className="drawer-foot">
          <button onClick={download} disabled={!data}>
            خروجی CSV
          </button>
          <span className="spacer" />
          <span className="tiny muted" style={{ alignSelf: "center" }}>
            گیت‌شده با تاریخ مبنا <span className="mono">{asOf}</span>
          </span>
        </div>
      </aside>
    </>
  );
}
