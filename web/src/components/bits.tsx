import type { ReactNode } from "react";
import type { Bucket, Gates, Relationship, SignalCategory } from "../api/types";

export const BUCKET_FA: Record<Bucket, string> = {
  grow: "رشد",
  protect: "حفظ",
  fix: "اصلاح",
  reduce: "کاهش",
};

export const BUCKET_MEANING_FA: Record<Bucket, string> = {
  grow: "سهم ما از سبد خریدش کمتر از ظرفیت اوست",
  protect: "سودده، منظم، کم‌دردسر",
  fix: "حجم بالا، سود صفر یا منفی",
  reduce: "خرید کم، سود کم",
};

export const CATEGORY_FA: Record<SignalCategory, string> = {
  risk: "ریسک",
  opportunity: "فرصت",
  efficiency: "کارایی",
};

/**
 * The three gate chips answer three *different* questions, and the wording keeps
 * them apart on purpose: credit and investigation describe the state right now
 * ("can we act today?"), while stance describes what already happened ("how did
 * past complaints end?"). Every stance label therefore carries the «سابقه»
 * prefix — without it the reader merges it with the investigation chip, since
 * both are about complaints. Second element of each pair is the tooltip.
 */
const CREDIT_FA: Record<string, [string, string]> = {
  open: ["سقف اعتبار باز", "فضای اعتباری باقی مانده؛ پیشنهاد افزایش حجم قابل اجراست."],
  exhausted: ["سقف اعتبار پر", "سقف عملاً پر شده؛ هر پیشنهاد رشد باید مشروط به بازنگری سقف باشد، وگرنه سفارش در واحد مالی متوقف می‌شود."],
  unknown: ["سقف اعتبار نامشخص", "دادهٔ سقف اعتبار برای این مشتری قابل اتکا نیست؛ روی آن حساب نکن."],
};
const INVESTIGATION_FA: Record<string, [string, string]> = {
  clear: ["بدون شکایت باز", "شکایت بازی که مانع جلسه یا پیشنهاد باشد وجود ندارد."],
  pending: ["شکایت باز — منتظر آزمون", "پروندهٔ شکایت هنوز بسته نشده و منتظر نمونه یا آزمون تکمیلی است؛ جلسه یا پیشنهاد باید *بعد از* تعیین تکلیف آن انجام شود."],
};
const STANCE_FA: Record<string, [string, string]> = {
  neutral: ["سابقه: بدون تقصیر محرز", "در شکایات گذشتهٔ این مشتری تقصیر محرزی برای هیچ طرف ثبت نشده؛ لحن خاصی لازم نیست."],
  apologise: ["سابقه: تقصیر با ما", "در شکایات گذشته قصور متوجه نفیس‌نخ بوده؛ گفتگو با پذیرش مسئولیت شروع شود."],
  unsubstantiated: ["سابقه: ادعا وارد نبود", "شکایات گذشته بررسی و رد شده‌اند؛ لازم نیست عذرخواهانه وارد شوی."],
  mixed: ["سابقه: دوگانه", "سابقهٔ شکایات هر دو حالت را دارد؛ پیش از موضع‌گیری پرونده‌به‌پرونده مرور کن."],
};

export function BucketPill({ bucket, title }: { bucket: Bucket; title?: boolean }) {
  return (
    <span className={`pill ${bucket}`} title={title ? BUCKET_MEANING_FA[bucket] : undefined}>
      {BUCKET_FA[bucket] ?? bucket}
    </span>
  );
}

export function RFMCell({ cell, segment }: { cell?: string | null; segment?: string | null }) {
  if (!cell) return <span className="muted">—</span>;
  return (
    <span className="rowsplit" style={{ gap: 6 }}>
      <span className="mono" style={{ fontWeight: 600 }}>{cell}</span>
      {segment && <span className="muted small">{segment}</span>}
    </span>
  );
}

export function SeverityBar({ severity, category }: { severity: number; category: SignalCategory }) {
  return (
    <span className="rowsplit" style={{ gap: 7 }}>
      <span className="sevbar" style={{ width: 62 }}>
        <i className={category} style={{ width: `${Math.min(100, Math.max(3, severity))}%` }} />
      </span>
      <span className="num tiny muted">{Math.round(severity)}</span>
    </span>
  );
}

export function GateBadge({ gates }: { gates: Partial<Gates> }) {
  const out: Array<[string, string, string | undefined]> = [];
  const pick = (map: Record<string, [string, string]>, key: string): [string, string | undefined] =>
    map[key] ? map[key] : [key, undefined];
  if (gates.credit_room) {
    const [label, tip] = pick(CREDIT_FA, gates.credit_room);
    out.push([gates.credit_room === "exhausted" ? "danger" : gates.credit_room === "open" ? "ok" : "neutral", label, tip]);
  }
  if (gates.open_investigation) {
    const [label, tip] = pick(INVESTIGATION_FA, gates.open_investigation);
    out.push([gates.open_investigation === "pending" ? "fix" : "ok", label, tip]);
  }
  if (gates.relationship_stance) {
    const [label, tip] = pick(STANCE_FA, gates.relationship_stance);
    out.push([gates.relationship_stance === "apologise" ? "fix" : "neutral", label, tip]);
  }
  if (!out.length) return null;
  return (
    <span className="rowsplit" style={{ gap: 5 }}>
      {out.map(([cls, label, tip]) => (
        <span key={label} className={`pill ${cls}`} title={tip}>{label}</span>
      ))}
    </span>
  );
}

const HEALTH_CLS: Record<string, string> = {
  "بحرانی": "danger",
  "در معرض خطر": "danger",
  "شکننده": "fix",
  "سالم": "ok",
};

function List({ title, items, cls }: { title: string; items?: unknown; cls?: string }) {
  const arr = Array.isArray(items) ? items.filter((x) => typeof x === "string" && x.trim()) : [];
  if (!arr.length) return null;
  return (
    <div className={cls ? `notice ${cls}` : undefined} style={{ marginTop: 10 }}>
      <div className="small" style={{ fontWeight: 700, marginBottom: 4 }}>{title}</div>
      <ul style={{ margin: 0, paddingInlineStart: 18 }}>
        {arr.map((x, i) => <li key={i} className="small">{x as string}</li>)}
      </ul>
    </div>
  );
}

/**
 * The synthesis the model wrote about this relationship — nine fields, of which
 * the tone and the unmet promises are what a sales manager actually needs in
 * the sixty seconds before dialling. Built only for customers that reached the
 * action queue, so `null` is the normal case and says so honestly.
 */
export function RelationshipPanel({ r }: { r: Relationship | null }) {
  if (!r) {
    return (
      <div className="notice" style={{ marginBottom: 18 }}>
        جمع‌بندی رابطه هنوز برای این مشتری آماده نشده است. با ساخت اقدام برای همین
        مشتری — دکمهٔ بالای همین صفحه — ساخته می‌شود و همین‌جا ظاهر می‌شود.
      </div>
    );
  }
  const conf = typeof r.health_confidence === "number" ? r.health_confidence : 1;
  return (
    <div className="card" style={{ marginBottom: 18 }}>
      <div className="rowsplit">
        <h3 style={{ flex: 1 }}>جمع‌بندی رابطه</h3>
        {r.health && (
          <span className={`pill ${HEALTH_CLS[r.health] ?? "neutral"}`}>{r.health}</span>
        )}
        {conf < 1 && <span className="tag">اطمینان {conf.toFixed(1)}</span>}
        {r.synthesis_source === "rules" && (
          <span className="pill fix">متن قالبی — مدل در دسترس نبود</span>
        )}
      </div>

      {r.summary_fa && <p style={{ margin: "10px 0 0" }}>{r.summary_fa}</p>}

      <div className="rowsplit" style={{ gap: 6, marginTop: 10 }}>
        {r.dominant_theme_fa && <span className="pill neutral">محور: {r.dominant_theme_fa}</span>}
        {r.recommended_tone_fa && <span className="pill protect">لحن پیشنهادی: {r.recommended_tone_fa}</span>}
      </div>

      <List title="معطل‌مانده از سمت ما" items={r.unmet_promises_fa} cls="bad" />
      <List title="آنچه برای خود مشتری مهم است" items={r.customer_priorities_fa} />
      <List title="مواردی که باید زیر نظر بماند" items={r.watch_items_fa} cls="cost" />
    </div>
  );
}

/** A one-line footnote under a button that takes a while.
 *
 *  This used to be a warning box counting model calls. The reader is a sales
 *  manager, and how many times we call a language model is our operational
 *  detail, not their decision — putting it on screen made every useful button
 *  look like a bill. What they do need is how long it takes, so that is all
 *  this says, in the quietest type on the page. */
export function RunHint({ children }: { children: ReactNode }) {
  return <p className="tiny muted" style={{ margin: "8px 0 0" }}>{children}</p>;
}

export function Skeleton({ h = 90, n = 1 }: { h?: number; n?: number }) {
  return (
    <div className="stack">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="skel" style={{ height: h }} />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v.toFixed(0);
}

export function fmtNum(v: unknown, digits = 0): string {
  if (typeof v !== "number" || Number.isNaN(v)) return v === null || v === undefined ? "—" : String(v);
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
