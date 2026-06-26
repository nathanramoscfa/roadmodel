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
  // Fallback model (Step 7 of the selector) — rendered as the "Backup" line so
  // the user has an alternative if the primary is unavailable to them. Optional:
  // absent/null when the recommender emitted no backup.
  backup?: string | null;
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
