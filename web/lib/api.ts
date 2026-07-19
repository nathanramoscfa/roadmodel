// web/lib/api.ts
import { env } from "./env";

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

export interface RecommendResponse {
  model: string;
  platform: string;
  settings: Record<string, unknown>;
  session_cost_estimate: Record<string, unknown>;
  comparison_table: Record<string, unknown>[];
  // Which engine tier served this recommendation (T3b): "free" (Gemini 2.5
  // Flash, anon) or "frontier" (Gemini 2.5 Pro, signed-in quality tier). Drives
  // the tier label so signed-in users aren't told to "upgrade for frontier
  // models" when they are already on it. `engine` is the resolved engine id.
  tier?: "free" | "frontier";
  engine?: string;
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
}

const DEFAULT_SERVICE_URL =
  "https://roadmodel-api.vercel.app/v1/recommend";

/** Server-side recommend helper (Step 5 contract). */
export async function recommendOnServer(
  taskDescription: string,
  context?: Record<string, unknown>,
): Promise<RecommendResponse> {
  const url = process.env.ROADMODEL_SERVICE_URL ?? DEFAULT_SERVICE_URL;
  const payload = {
    task_description: taskDescription,
    context: {
      ...(context ?? {}),
      force_provider: "google-gemini-2.5-flash",
    },
  };
  const res = await fetch(url, {
    method: "POST",
    headers: recommenderRequestHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`recommend upstream ${res.status}`);
  }
  return (await res.json()) as RecommendResponse;
}
