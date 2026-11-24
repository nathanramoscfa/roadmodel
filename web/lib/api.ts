// web/lib/api.ts
import { env } from "./env";
import { VISITOR_KEY_HEADER, VISITOR_PROVIDER_HEADER, type VisitorLane } from "./funding-lane";

// Headers for a server->service /v1/recommend call. Always JSON; attaches
// the shared edge<->service bearer when ROADMODEL_INTERNAL_TOKEN is set.
// Fail-closed: when the token is unset the Authorization header is omitted,
// so the authenticated service rejects with 401 rather than serving a free
// (paid-upstream) call. The E2E mock recommender ignores the header.
export function recommenderRequestHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = env.ROADMODEL_INTERNAL_TOKEN;
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

// Headers for the visitor lane's service call: the ones above, plus the
// visitor's key and provider, copied from the browser's request into the same
// two headers. This is the only place the key is read for forwarding, and a
// header is the only place it travels: never the body, the context, a log or
// the audit row. The lane has already checked its shape (lib/funding-lane.ts).
export function visitorRequestHeaders(req: Request, lane: VisitorLane): Record<string, string> {
  return {
    ...recommenderRequestHeaders(),
    [VISITOR_KEY_HEADER]: (req.headers.get(VISITOR_KEY_HEADER) ?? "").trim(),
    [VISITOR_PROVIDER_HEADER]: lane.provider,
  };
}

// One ranked option of a pick's column, as the service reads it off the
// frontier (service/app/ranks.py): a model on a platform at a level, with its
// AA Intelligence Index and price there, the figures a roadmap's Settings
// print for it.
export interface RankedOption {
  model: string;
  model_id: string;
  platform: string;
  platform_id: string;
  // The scorer's level (low / medium / high / xhigh / max), or "fixed".
  effort: string;
  // The level as the ladder words it ("XHigh"); "—" where the surface has no
  // reasoning dial.
  level: string;
  aa_index: number | null;
  // The index at that level is roadmodel's estimate from the levels
  // Artificial Analysis measured.
  aa_estimated: boolean;
  // USD per 1M blended tokens at that level's token use.
  price_usd_per_1m: number | null;
  // Whether that token use was measured (false: derived).
  price_measured: boolean | null;
  // The Pick's own model one or two levels lower, where no other maker's
  // model fills the rank.
  stepped_down: boolean;
  ultracode: boolean;
}

// A pick ranked three deep, each rank from another maker: the Pick, the
// Runner-up with the Pick's maker left out, the Backup with both left out.
export interface Ranks {
  pick: RankedOption;
  runner_up: RankedOption | null;
  backup: RankedOption | null;
}

// One setting an answer's ladder weighed (service/app/models.py LadderPoint):
// a model the viewer can run at an effort the task may run, with its AA
// Intelligence Index and price there. The frontier the picks were read from
// is drawn over these (lib/frontier-points.ts).
export interface LadderPoint {
  model_id: string;
  platform_id: string;
  // The scorer's level; null for a model AA names no effort for.
  effort: string | null;
  // The index as a ladder prints it, and how far below it the recommender
  // counts it (an estimate's uncertainty; 0 for a measurement): the frontier
  // stands on aa_index - margin.
  aa_index: number;
  margin: number;
  price_usd_per_1m: number;
  // Meets the task's bar.
  adequate: boolean;
  // The index is roadmodel's estimate: AA has not measured the model.
  estimated: boolean;
}

// What a task was read as: the category and complexity its picks were ranked
// for, and whether it is a new kind of problem.
export interface LadderTask {
  category: string;
  complexity: string;
  novel: boolean;
}

export interface RecommendResponse {
  model: string;
  platform: string;
  settings: Record<string, unknown>;
  session_cost_estimate: Record<string, unknown>;
  comparison_table: Record<string, unknown>[];
  // Structured rationale sections (task / pick / run), emitted best-effort by
  // the service when the model followed the labelled RATIONALE format. The
  // "Why this model?" panel renders these as sub-headings; absent/null -> it
  // falls back to splitting the single `rationale` string. Carried verbatim by
  // the edge (no budget/funding notes appended, unlike settings.rationale).
  rationale_sections?: Record<string, string> | null;
  // Fallback model (Step 7) — a structured BackupPick so the "Backup" line shows
  // the model, its own funded platform, and its per-surface settings (same
  // reasoning posture as the pick), i.e. it adheres to the user's settings like
  // the primary. Absent/null when the recommender emitted no backup; within it,
  // platform is null / settings is {} when unresolved (anon / no funding).
  backup?: {
    model: string;
    platform: string | null;
    settings: Record<string, string>;
  } | null;
  // A category specialist: a model off the viewer's cost/quality frontier
  // whose rating for the task's category (`specialist_category`) is above
  // every frontier model's, which the frontier ladder puts on Quality. Absent
  // on a payload from before the field, or false.
  specialist?: boolean;
  specialist_category?: string | null;
  // The pick with its Runner-up and Backup, as a roadmap's Settings rank it.
  // Absent or null on a payload from before the field, on a pick the frontier
  // table did not place, and whenever the service could not read them.
  ranks?: Ranks | null;
}

// One recommendation computed at a specific budget priority. The /recommend
// surface now returns all three (Cost / Balanced / Quality) from a single user
// request — the edge fans out three parallel /v1/recommend calls, one per
// priority — so the user sees the cost-vs-quality trade-off for THEIR prompt
// instead of pre-committing to one with a toggle. Reuses RecommendResponse so
// the existing card internals (header / settings / cost / why) render unchanged.
export interface PriorityRecommendation extends RecommendResponse {
  // The historical stored id: "cheap" (Cost) | "balanced" (Balanced) | "best"
  // (Quality). Mirrors BudgetPriority in @/lib/profile.
  priority: "cheap" | "balanced" | "best";
}

// The /api/recommend response shape (replaces the single RecommendResponse on
// the wire). `primary` is the priority to highlight / lead with — seeded from
// the user's saved profile preference (or Balanced by default). `recommendations`
// is always ordered Cost → Balanced → Quality.
export interface MultiRecommendResponse {
  recommendations: PriorityRecommendation[];
  primary: "cheap" | "balanced" | "best";
  // The engine run that produced the picks (absent on a payload from before
  // the engine menu).
  engine?: EngineRun;
  // What the engine read the task as (absent on a payload from before the
  // field; null when the answer matched no row of the frontier table).
  task?: LadderTask | null;
  // The settings the answer's ladder weighed, for the chart (absent or null
  // like `task`).
  points?: LadderPoint[] | null;
}

// The engine that wrote the picks: the user's menu choice, or the service's
// fallback when that engine failed (`fell_back`), with what the call cost and
// who paid it (`funded_by`: roadmodel's account, or the visitor's own key).
// `cost_source` says whether the cost came from the provider's reported usage
// or the cold estimate.
export interface EngineRun {
  hint: string;
  name: string;
  maker: string;
  requested: string;
  requested_name: string;
  fell_back: boolean;
  latency_ms: number | null;
  cost_usd: number;
  cost_source: "measured" | "estimated";
  // The share of the prompt the provider served from its cache, when measured.
  cached_share: number | null;
  // Absent on a payload from before the visitor lane, which was the operator's.
  funded_by?: "operator" | "visitor";
}
