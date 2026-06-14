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
    };
  } = {};
  try {
    body = (await req.json()) as typeof body;
  } catch {
    body = {};
  }

  const allowed = body.context?.allowed_jurisdictions ?? [];
  const includeKimi = allowed.includes("cn");

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
    model: includeKimi ? "Kimi K2.5" : "Claude 4.5 Haiku",
    platform: includeKimi ? "Cursor" : "Claude Code",
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
