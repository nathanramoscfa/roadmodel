// web/lib/api.ts
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`recommend upstream ${res.status}`);
  }
  return (await res.json()) as RecommendResponse;
}
