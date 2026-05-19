// web/lib/api.ts
import { env } from "./env";

export interface RecommendResponse {
  model: string;
  platform: string;
  settings: Record<string, unknown>;
  session_cost_estimate: Record<string, unknown>;
  comparison_table: Record<string, unknown>[];
  free_tier_label?: string | null;
}

export async function recommendOnServer(
  taskDescription: string,
  context?: Record<string, unknown>,
): Promise<RecommendResponse> {
  const res = await fetch(`${env.ROADMODEL_SERVICE_URL}/v1/recommend`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.ROADMODEL_INTERNAL_TOKEN}`,
    },
    body: JSON.stringify({
      task_description: taskDescription,
      context,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`recommender ${res.status}`);
  }
  return res.json() as Promise<RecommendResponse>;
}
