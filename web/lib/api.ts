// web/lib/api.ts
export interface RecommendResponse {
  model: string;
  platform: string;
  settings: Record<string, unknown>;
  session_cost_estimate: Record<string, unknown>;
  comparison_table: Record<string, unknown>[];
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
      force_provider: "anthropic-haiku-4-5",
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
