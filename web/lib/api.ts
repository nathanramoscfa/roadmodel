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
  // ROADMODEL_SERVICE_URL / ROADMODEL_INTERNAL_TOKEN are unset on the
  // production env until Phase 3 Step 7 provisions the production Railway
  // service. Fail at request time so the /api/recommend handler returns 502
  // instead of crashing the build during Next.js page-data collection.
  if (!env.ROADMODEL_SERVICE_URL || !env.ROADMODEL_INTERNAL_TOKEN) {
    throw new Error("recommender_not_configured");
  }
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
