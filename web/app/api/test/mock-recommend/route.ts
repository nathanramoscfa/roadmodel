// web/app/api/test/mock-recommend/route.ts
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
      budget_priority?: string;
    };
  } = {};
  try {
    body = (await req.json()) as typeof body;
  } catch {
    body = {};
  }

  const allowed = body.context?.allowed_jurisdictions ?? [];
  const includeKimi = allowed.includes("cn");

  // The edge now fans out one call per budget priority (Cost / Balanced /
  // Quality). Vary the mock pick by the forwarded budget_priority so the
  // three-card UI renders three distinct models in E2E (the real engine does
  // this via the per-priority posture, #319). cn-jurisdiction Kimi still takes
  // precedence so the existing jurisdiction-filter spec is unaffected.
  const budget = body.context?.budget_priority ?? "balanced";
  const byBudget: Record<string, { model: string; platform: string }> = {
    cheap: { model: "Claude 4.5 Haiku", platform: "Claude Code" },
    balanced: { model: "GPT-5.4", platform: "Codex" },
    best: { model: "Claude Opus 4.8", platform: "Claude Code" },
  };
  const pick = includeKimi
    ? { model: "Kimi K2.5", platform: "Cursor" }
    : (byBudget[budget] ?? byBudget.balanced);

  // Phase 4.8 T2b: echo the forwarded funding so the edge -> service forwarding
  // contract is observable in E2E (mirrors how allowed_jurisdictions drives the
  // pick above). The real service builds a per-user user-context from these and
  // the recommendation LLM biases its model SELECTION toward funded surfaces.
  const subscriptions = body.context?.subscriptions ?? [];
  const apiProviders = body.context?.api_providers ?? [];
  const fundingEcho =
    subscriptions.length || apiProviders.length
      ? ` Forwarded funding — subscriptions: [${subscriptions.join(
          ", ",
        )}]; api: [${apiProviders.join(", ")}].`
      : "";

  // Realistic SessionCostEstimate shape (model_id/platform_id) so the T3 edge
  // personalization (web/lib/funding.ts personalizeComparison) can resolve each
  // row against the user's funding in E2E.
  const comparison = [
    {
      model_name: "Claude 4.5 Haiku",
      model_id: "claude-4.5-haiku",
      platform_name: "Claude Code",
      platform_id: "claude-code",
      total_usd: 0.01,
    },
    {
      model_name: "Kimi K2.5",
      model_id: "kimi-k2.5",
      platform_name: "Cursor",
      platform_id: "cursor",
      total_usd: 0.005,
    },
  ];

  return NextResponse.json({
    model: pick.model,
    platform: pick.platform,
    settings: {
      rationale:
        (includeKimi
          ? "Candidates include Kimi K2.5."
          : "Default western-market pick.") + fundingEcho,
    },
    session_cost_estimate: { total_usd: 0.01 },
    comparison_table: comparison,
  });
}
