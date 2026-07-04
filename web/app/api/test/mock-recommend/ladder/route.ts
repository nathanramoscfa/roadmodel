// web/app/api/test/mock-recommend/ladder/route.ts
//
// E2E mock for the single-call ladder endpoint (tasks #1/#3). The real edge, in
// ladder mode, POSTs here (recommenderUrl() + "/ladder") and expects a
// LadderResponse: three tier-keyed picks + the deterministic tier-distinctness
// guard. Mirrors the single-pick mock (../route.ts) but returns the whole
// anchored Cost/Balanced/Quality ladder in one body, so a flag-on
// (RECOMMEND_LADDER_ENABLED=1) run exercises the ladder path end-to-end.
import { NextResponse } from "next/server";

import { isE2eAuthEnabled } from "@/lib/profile";

export async function POST(req: Request): Promise<Response> {
  if (!isE2eAuthEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  let body: {
    context?: {
      allowed_jurisdictions?: string[];
      subscriptions?: string[];
      api_providers?: string[];
    };
  } = {};
  try {
    body = (await req.json()) as typeof body;
  } catch {
    body = {};
  }

  const subscriptions = body.context?.subscriptions ?? [];
  const apiProviders = body.context?.api_providers ?? [];
  const fundingEcho =
    subscriptions.length || apiProviders.length
      ? ` Forwarded funding — subscriptions: [${subscriptions.join(
          ", ",
        )}]; api: [${apiProviders.join(", ")}].`
      : "";

  const comparisonFor = (model_id: string, model_name: string, total_usd: number) => [
    {
      model_name,
      model_id,
      platform_name: "Claude Code",
      platform_id: "claude-code",
      total_usd,
    },
  ];

  // Three DISTINCT, decreasing-tier picks — the target end state (Cost=Low,
  // Balanced=High, Quality=Very High). Each pick is the same shape as a
  // single-pick RecommendResponse.
  const pickFor = (
    model: string,
    model_id: string,
    effort: string,
    total_usd: number,
  ) => ({
    model,
    platform: "Claude Code",
    settings: { effort, thinking: "On" },
    rationale:
      `TASK: Coding. PICK: ${model} fits. RUN: Claude Code.` + fundingEcho,
    conversation: "New",
    session_cost_estimate: { total_usd },
    comparison_table: comparisonFor(model_id, model, total_usd),
  });

  return NextResponse.json({
    picks: {
      quality: pickFor("Claude Opus 4.8", "opus-4.8", "Max", 0.02),
      balanced: pickFor("Claude Sonnet 4.6", "sonnet-4.6", "High", 0.01),
      cost: pickFor("Claude 4.5 Haiku", "claude-4.5-haiku", "Low", 0.002),
    },
    guard: {
      duplicate_models: false,
      misordered: false,
      distinct_tiers: true,
      healthy: true,
    },
  });
}
