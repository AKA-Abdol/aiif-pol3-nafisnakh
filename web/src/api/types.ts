/** Shapes mirrored from docs/API.md — all verified against live responses. */

export type Bucket = "grow" | "protect" | "fix" | "reduce";
export type SignalCategory = "risk" | "opportunity" | "efficiency";
export type Direction = "deteriorating" | "improving" | "static";
export type EvidenceKind = "metric" | "event" | "text" | "comparison";
export type Decision = "done" | "dismissed" | "snoozed" | "wrong";
export type Source = "live" | "cached" | "rules";

export type CreditRoom = "open" | "exhausted" | "unknown";
export type OpenInvestigation = "clear" | "pending";
export type RelationshipStance = "neutral" | "apologise" | "unsubstantiated" | "mixed";

export interface Health {
  status: string;
  as_of: string;
  llm_available: boolean;
  llm_model: string;
  llm_provider: string[];
  cached_runs: string[];
}

export interface Summary {
  as_of: string;
  customers: number;
  signals: number;
  triggered_customers: number;
  detectors: number;
  quadrants: Record<Bucket, number>;
  evidence: number;
  metric_tables: string[];
  feedback_weights: Record<string, number>;
}

export interface CustomerRow {
  customer_id: string;
  bucket: Bucket;
  segment: string | null;
  rfm_cell: string | null;
  rfm_segment_fa: string | null;
  open_loops: number | null;
  signals: number;
}

export interface CustomerList {
  as_of: string;
  total: number;
  customers: CustomerRow[];
}

export interface Locator {
  kind: string;
  sheet: string;
  key: string;
  values: string[];
}

export interface Evidence {
  id: string;
  customer_id: string;
  kind: EvidenceKind;
  claim_fa: string;
  value: number | string | null;
  unit: string | null;
  as_of: string;
  window: [string, string] | null;
  source_rows: string;
  provenance: Record<string, unknown> & { formula?: string; assumption?: boolean };
  confidence: number;
  locator?: Locator | null;
}

export interface EvidenceRows {
  evidence_id: string;
  claim_fa: string;
  as_of: string;
  locator: Locator;
  n_rows: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface Signal {
  id: string;
  customer_id: string;
  detector: string;
  category: SignalCategory;
  severity: number;
  direction: Direction;
  headline_fa: string;
  evidence_ids: string[];
  first_detected_at: string;
  value_at_stake: number;
  suggested_bucket: Bucket | null;
  detail: Record<string, unknown>;
}

/** Nine fields from `nafisnakh/llm/blocks/relationship.py`. Built only for
 *  customers that reached the action queue — `null` for everyone else. */
export interface Relationship {
  health?: string;
  health_confidence?: number;
  dominant_theme_fa?: string;
  unmet_promises_fa?: string[];
  customer_priorities_fa?: string[];
  recommended_tone_fa?: string;
  watch_items_fa?: string[];
  summary_fa?: string;
  synthesis_source?: Source;
  [k: string]: unknown;
}

export interface CustomerDossier {
  customer_id: string;
  as_of: string;
  bucket: Bucket;
  bucket_reason_fa: string;
  // These four carry numbers, strings, booleans and id arrays side by side —
  // `next_action_open` is a bool, `dev_approved_open_ids` is a string[].
  rfm: Record<string, unknown>;
  open_loops: Record<string, unknown>;
  payment: Record<string, unknown>;
  quality: Record<string, unknown>;
  signals: Signal[];
  evidence: Evidence[];
  relationship: Relationship | null;
}

export interface ToolResult {
  tool: string;
  claims: string[];
  evidence_ids: string[];
  payload: Record<string, unknown>;
  note_fa: string;
  empty_reason_fa: string;
  model_text: string;
}

export interface CustomerTools {
  customer_id: string;
  as_of: string;
  results: ToolResult[];
}

export interface ToolSpec {
  name: string;
  description_fa: string;
  params: Record<string, string>;
  schema: Record<string, unknown>;
}

export interface AgentSpec {
  name: string;
  question_fa: string;
  role_fa: string;
  tools: string[];
  forbidden_fa: string;
}

export interface Gates {
  credit_room: CreditRoom;
  open_investigation: OpenInvestigation;
  relationship_stance: RelationshipStance;
}

export interface RoutedAgent {
  agent: string;
  reason_fa: string;
  weight: number;
  blocking: boolean;
  detail: Record<string, unknown>;
}

export interface SkippedAgent {
  agent: string;
  reason_fa: string;
}

export interface MeetingPlan {
  customer_id: string;
  routed: RoutedAgent[];
  skipped: SkippedAgent[];
  constraints: string[];
  gates: Gates;
  n_llm_calls: number;
}

export interface Finding {
  agent: string;
  question_fa: string;
  trigger_fa: string;
  headline_fa: string;
  reasoning_fa: string;
  recommended_step_fa: string;
  evidence_ids: string[];
  tools_used: string[];
  tools_reason_fa: string;
  blocking: boolean;
  weight: number;
  source: Source;
  dropped: unknown[];
}

export interface MeetingResult {
  customer_id: string;
  as_of: string;
  routing: MeetingPlan;
  findings: Finding[];
  errors: Record<string, string>;
  brief_fa: string;
}

export interface Action {
  customer_id: string;
  rank: number;
  priority: string;
  bucket: Bucket;
  title_fa: string;
  rationale_fa: string;
  recommended_step_fa: string;
  owner: string;
  evidence_ids: string[];
  signals: string[];
  value_at_stake: number;
  source: Source;
  detail: Partial<Gates> & Record<string, unknown>;
}

export interface CalibrationRow {
  detector: string;
  category: SignalCategory;
  fired: number;
  eligible: number;
  fire_rate: number;
  rare_by_design: boolean;
  status: "ok" | "too_broad" | "too_narrow" | "insufficient";
  note: string;
}

export interface Calibration {
  as_of: string;
  population: number;
  rows: CalibrationRow[];
  failures: string[];
  insufficient: string[];
}

export interface FeedbackIn {
  customer_id: string;
  decision: Decision;
  detectors: string[];
  reason_fa?: string | null;
  actor?: string | null;
  rank?: number | null;
  bucket?: Bucket | null;
}

export interface DetectorStat {
  detector: string;
  events: number;
  done: number;
  dismissed: number;
  snoozed: number;
  wrong: number;
  weight: number;
  [k: string]: unknown;
}

export interface FeedbackStats {
  events: number;
  detector_stats: DetectorStat[];
  weights: Record<string, number>;
}
