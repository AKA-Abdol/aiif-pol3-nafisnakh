import type {
  Action, Calibration, CustomerAction, CustomerDossier, CustomerList, CustomerTools,
  Evidence, EvidenceRows, FeedbackIn, FeedbackStats, Health, MeetingPlan,
  MeetingResult, Summary, ToolSpec, AgentSpec, Bucket,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly path: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** Persian sentence a component can render directly. */
  get fa(): string {
    if (this.status === 404) return "این مورد یافت نشد — شاید تاریخ مبنا عوض شده است.";
    if (this.status === 409) return "این شاهد ردیف قابل نمایشی ندارد. لطفاً به تیم بک‌اند گزارش دهید.";
    if (this.status === 400) return this.detail || "درخواست نامعتبر بود.";
    if (this.status === 0) return "سرور در دسترس نیست. مطمئن شوید بک‌اند روی پورت ۸۰۰۰ بالاست.";
    return this.detail || `خطای ${this.status}`;
  }
}

/** Every API path lives under this prefix so none of them can collide with an
 *  SPA route. `/customers` used to be both a page and an endpoint — Vite runs
 *  its proxy before the history fallback, so reloading `/customers/C_117580`
 *  served raw JSON instead of the app. In production either mount the backend
 *  under `/api` or point `VITE_API_BASE` at it. */
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

function qs(params: Record<string, string | number | undefined | null>): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  }
  const out = s.toString();
  return out ? `?${out}` : "";
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "network", path);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* body was not JSON — keep statusText */
    }
    throw new ApiError(res.status, detail, path);
  }
  return (await res.json()) as T;
}

/** Every read takes as_of. Paid calls are marked; nothing here fires on its own. */
export const api = {
  health: () => req<Health>("/health"),

  summary: (asOf?: string) => req<Summary>(`/summary${qs({ as_of: asOf })}`),

  customers: (asOf?: string, opts: { bucket?: Bucket; segment?: string; limit?: number } = {}) =>
    req<CustomerList>(`/customers${qs({ as_of: asOf, limit: opts.limit ?? 1000, bucket: opts.bucket, segment: opts.segment })}`),

  customer: (id: string, asOf?: string) =>
    req<CustomerDossier>(`/customers/${encodeURIComponent(id)}${qs({ as_of: asOf })}`),

  customerTools: (id: string, asOf?: string, tool?: string) =>
    req<CustomerTools>(`/customers/${encodeURIComponent(id)}/tools${qs({ as_of: asOf, tool })}`),

  evidence: (id: string, asOf?: string) =>
    req<Evidence>(`/evidence/${encodeURIComponent(id)}${qs({ as_of: asOf })}`),

  evidenceRows: (id: string, asOf?: string, limit = 50) =>
    req<EvidenceRows>(`/evidence/${encodeURIComponent(id)}/rows${qs({ as_of: asOf, limit })}`),

  tools: () => req<{ tools: ToolSpec[] }>("/tools"),

  agents: () => req<{ agents: AgentSpec[] }>("/agents"),

  meetingPlan: (id: string, asOf?: string) =>
    req<MeetingPlan>(`/customers/${encodeURIComponent(id)}/meeting/plan${qs({ as_of: asOf })}`),

  /** PAID — ~12s per routed agent. Only ever call from an explicit click. */
  runMeeting: (id: string, agents: string[] | null, asOf?: string) =>
    req<MeetingResult>(`/customers/${encodeURIComponent(id)}/meeting${qs({ as_of: asOf })}`, {
      method: "POST",
      body: JSON.stringify(agents && agents.length ? { agents } : {}),
    }),

  /** FREE — reads the on-disk cache only. Says whether a build would cost anything. */
  customerAction: (id: string, asOf?: string) =>
    req<CustomerAction>(`/customers/${encodeURIComponent(id)}/action${qs({ as_of: asOf })}`),

  /** PAID — 1-2 model calls for this one account, then cached to disk forever.
   *  `refresh` pays again on purpose; only ever from a second, explicit click. */
  buildCustomerAction: (id: string, asOf?: string, refresh = false) =>
    req<CustomerAction>(
      `/customers/${encodeURIComponent(id)}/action${qs({ as_of: asOf, refresh: refresh ? "true" : undefined })}`,
      { method: "POST" },
    ),

  /** PAID — one model call per action on a cold run. */
  actions: (asOf?: string, opts: { bucket?: Bucket; priority?: string; limit?: number } = {}) =>
    req<Action[]>(`/actions${qs({ as_of: asOf, limit: opts.limit ?? 25, bucket: opts.bucket, priority: opts.priority })}`),

  calibration: (asOf?: string) => req<Calibration>(`/calibration${qs({ as_of: asOf })}`),

  feedbackStats: () => req<FeedbackStats>("/feedback"),

  postFeedback: (payload: FeedbackIn, asOf?: string) =>
    req<{ recorded: Record<string, unknown>; weights: Record<string, number> }>(
      `/feedback${qs({ as_of: asOf })}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  /** Plain URLs — opened in a new tab, never rendered inside the app. */
  pageUrl: (id: string, asOf?: string, rows = 25) =>
    `${BASE}/customers/${encodeURIComponent(id)}/page${qs({ as_of: asOf, rows })}`,
  reportUrl: (asOf?: string, top = 25) => `${BASE}/report${qs({ as_of: asOf, top })}`,
};
