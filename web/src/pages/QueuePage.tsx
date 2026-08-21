import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useApp, useLink } from "../state/app";
import type { Action, Bucket, Decision } from "../api/types";
import { WithEvidence, EvidenceChips } from "../components/Evidence";
import { BUCKET_FA, BucketPill, CostNotice, GateBadge, Skeleton, fmtMoney } from "../components/bits";

const DECISIONS: Array<{ k: Decision; fa: string; needsReason: boolean }> = [
  { k: "done", fa: "انجام شد", needsReason: false },
  { k: "dismissed", fa: "رد شد", needsReason: true },
  { k: "snoozed", fa: "فعلاً نه", needsReason: false },
  { k: "wrong", fa: "اشتباه است", needsReason: true },
];

/** The four bands the aggregator assigns — sent verbatim as `?priority=`. */
const PRIORITIES = ["فوری", "بالا", "متوسط", "پایین"];

export default function QueuePage() {
  const { asOf } = useApp();
  const link = useLink();
  const qc = useQueryClient();
  const [limit, setLimit] = useState(25);
  const [bucket, setBucket] = useState<Bucket | "">("");
  const [priority, setPriority] = useState("");

  // Every knob below is part of the cache key, so changing one means a fresh
  // key — which means a fresh run, which means fresh money.
  const key = ["actions", asOf, limit, bucket, priority] as const;
  const keyStr = JSON.stringify(key);

  // The queue is never fetched on mount — it costs one model call per action.
  // But a queue already in the cache is free, so coming back from a customer
  // page must not put the user in front of the pay button again. Arming is
  // therefore keyed: this exact combination was either paid for already
  // (it is in the cache) or the user just clicked for it.
  const [armedKey, setArmedKey] = useState<string | null>(null);
  const [tuning, setTuning] = useState(false);
  const cached = qc.getQueryData(key) !== undefined;
  const armed = cached || armedKey === keyStr;

  const summary = useQuery({ queryKey: ["summary", asOf], queryFn: () => api.summary(asOf) });
  const actions = useQuery({
    queryKey: key,
    queryFn: () =>
      api.actions(asOf, { limit, bucket: bucket || undefined, priority: priority || undefined }),
    enabled: armed,
    staleTime: Infinity,
  });

  return (
    <div className="wrap">
      <div className="pagehead">
        <div>
          <h1>صف امروز</h1>
          <div className="sub">امروز به کدام مشتری‌ها زنگ بزنم و چه بگویم؟</div>
        </div>
        {actions.data && (
          <div className="btnrow">
            <button className="ghost" onClick={() => setTuning((t) => !t)}>
              {tuning ? "بستن تنظیمات" : "تنظیم صف"}
            </button>
            <a className="btn" href={api.reportUrl(asOf, limit)} target="_blank" rel="noreferrer">
              نسخهٔ چاپی ↗
            </a>
          </div>
        )}
      </div>

      {/* Free and instant — shown before the expensive part (API.md §639). */}
      {summary.isLoading && <Skeleton h={86} />}
      {summary.data && (
        <div className="tiles" style={{ marginBottom: 18 }}>
          {(["grow", "protect", "fix", "reduce"] as const).map((b) => (
            <Link key={b} to={link(`/customers?bucket=${b}`)} className="tile click" style={{ textDecoration: "none" }}>
              <div className="k">{BUCKET_FA[b]}</div>
              <div className="v num">{summary.data.quadrants[b] ?? 0}</div>
              <div className="n">مشتری</div>
            </Link>
          ))}
          <div className="tile">
            <div className="k">سیگنال فعال</div>
            <div className="v num">{summary.data.signals.toLocaleString("en-US")}</div>
            <div className="n">روی {summary.data.triggered_customers} مشتری · {summary.data.detectors} آشکارساز</div>
          </div>
          <div className="tile">
            <div className="k">شواهد قابل ردیابی</div>
            <div className="v num">{summary.data.evidence.toLocaleString("en-US")}</div>
            <div className="n">برای {summary.data.customers} مشتری</div>
          </div>
        </div>
      )}

      {(!armed || tuning) && (
        <div className="card" style={{ marginBottom: 12 }}>
          <h3 style={{ marginBottom: 8 }}>ساخت صف اقدام</h3>
          <p className="dim small">
            صف با نوشتن یک اقدام برای هر مشتری ساخته می‌شود و هر اقدام یک فراخوان مدل دارد.
            به همین دلیل خودکار اجرا نمی‌شود.
          </p>
          <div className="filters" style={{ marginTop: 12, marginBottom: 12 }}>
            <label className="small muted">تعداد اقدام</label>
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <label className="small muted">سطل</label>
            <select value={bucket} onChange={(e) => setBucket(e.target.value as Bucket | "")}>
              <option value="">همه</option>
              {(["grow", "protect", "fix", "reduce"] as Bucket[]).map((b) => (
                <option key={b} value={b}>{BUCKET_FA[b]}</option>
              ))}
            </select>
            <label className="small muted">اولویت</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="">همه</option>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          {cached ? (
            <div className="notice good">این ترکیب قبلاً ساخته شده و در کش مرورگر است — نمایشش رایگان است.</div>
          ) : (
            <CostNotice calls={limit} note="اجرای سرد ممکن است چند دقیقه طول بکشد؛ اجرای دوم از کش می‌آید." />
          )}
          <div className="btnrow" style={{ marginTop: 12 }}>
            <button
              className="primary"
              onClick={() => { setArmedKey(keyStr); setTuning(false); }}
            >
              {cached ? "نمایش این صف" : "ساخت صف"}
            </button>
          </div>
        </div>
      )}

      {armed && actions.isLoading && (
        <>
          <div className="notice info" style={{ marginBottom: 12 }}>
            در حال ساخت صف — <span className="num">{limit}</span> فراخوان مدل. ممکن است چند دقیقه طول بکشد.
          </div>
          <Skeleton h={150} n={4} />
        </>
      )}
      {armed && actions.isError && (
        <div className="notice bad">
          {(actions.error as ApiError).fa}
          <div className="btnrow" style={{ marginTop: 10 }}>
            <button className="sm" onClick={() => actions.refetch()}>تلاش دوباره</button>
          </div>
        </div>
      )}

      {actions.data && (
        <div className="stack">
          {actions.data.map((a) => <ActionCard key={a.customer_id} a={a} />)}
        </div>
      )}
    </div>
  );
}

function ActionCard({ a }: { a: Action }) {
  const { asOf } = useApp();
  const link = useLink();
  const qc = useQueryClient();
  const [why, setWhy] = useState(false);
  const [pending, setPending] = useState<Decision | null>(null);
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState<Decision | null>(null);

  const mut = useMutation({
    mutationFn: (d: Decision) =>
      // detectors always come from the card the user clicked, or the server 400s
      // when this customer is not in the current queue (API.md §602).
      api.postFeedback(
        { customer_id: a.customer_id, decision: d, detectors: a.signals, reason_fa: reason || null, rank: a.rank, bucket: a.bucket },
        asOf,
      ),
    onSuccess: (_r, d) => {
      setSent(d);
      setPending(null);
      // The server dropped its own cache, so the next build will reflect this
      // vote. Ours is marked stale but deliberately NOT removed and NOT
      // refetched: removing it would blank the list the user is still working
      // through, and refetching would spend the money again. Rebuilding stays
      // a decision, behind «تنظیم صف».
      qc.invalidateQueries({ queryKey: ["actions"], refetchType: "none" });
      qc.invalidateQueries({ queryKey: ["feedback"] });
    },
  });

  if (sent) {
    return (
      <div className="card" style={{ opacity: 0.6 }}>
        <div className="rowsplit">
          <span className="pill ok">ثبت شد: {DECISIONS.find((x) => x.k === sent)?.fa}</span>
          <span className="mono small">{a.customer_id}</span>
          <span className="spacer" />
          <span className="tiny muted">صف بعدی با این رأی رتبه‌بندی می‌شود</span>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="rowsplit">
        <span className="pill danger">{a.priority}</span>
        <BucketPill bucket={a.bucket} title />
        <Link className="mono small" to={link(`/customers/${a.customer_id}`)}>{a.customer_id}</Link>
        <GateBadge gates={a.detail} />
        <span className="spacer" />
        <span className="small muted">در معرض خطر <b className="num">{fmtMoney(a.value_at_stake)}</b></span>
        <span className="tag">#{a.rank}</span>
      </div>

      <h3 style={{ margin: "12px 0 10px" }}>{a.title_fa}</h3>

      <div className="notice good" style={{ marginBottom: 10 }}>
        <strong>قدم بعدی:</strong> {a.recommended_step_fa}
        <div className="tiny" style={{ marginTop: 6, opacity: 0.85 }}>مسئول: {a.owner}</div>
      </div>

      <div className="rowsplit" style={{ gap: 5, marginBottom: 8 }}>
        {a.signals.map((s) => <span key={s} className="tag">{s}</span>)}
        {a.source === "rules" && <span className="pill fix">متن قالبی — مدل در دسترس نبود</span>}
      </div>

      <details className="sect" open={why} onToggle={(e) => setWhy((e.target as HTMLDetailsElement).open)}>
        <summary>چرا؟</summary>
        <p style={{ lineHeight: 2 }}><WithEvidence text={a.rationale_fa} /></p>
        <EvidenceChips ids={a.evidence_ids} />
      </details>

      <div className="btnrow" style={{ marginTop: 12, borderTop: "1px solid var(--rule)", paddingTop: 12 }}>
        {DECISIONS.map((d) => (
          <button
            key={d.k}
            className="sm"
            disabled={mut.isPending}
            onClick={() => (d.needsReason ? setPending(d.k) : mut.mutate(d.k))}
          >
            {d.fa}
          </button>
        ))}
      </div>

      {pending && (
        <div style={{ marginTop: 10 }}>
          <textarea
            autoFocus
            placeholder="چرا؟ این توضیح به تیم داده کمک می‌کند."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="btnrow" style={{ marginTop: 8 }}>
            <button className="primary sm" disabled={mut.isPending} onClick={() => mut.mutate(pending)}>ثبت</button>
            <button className="ghost sm" onClick={() => { setPending(null); setReason(""); }}>انصراف</button>
          </div>
        </div>
      )}

      {mut.isError && <div className="notice bad" style={{ marginTop: 10 }}>{(mut.error as ApiError).fa}</div>}
    </div>
  );
}
