// web/app/api/test/mock-recommend/route.ts
import { NextResponse } from "next/server";

import { isE2eAuthEnabled } from "@/lib/profile";

export async function POST(req: Request): Promise<Response> {
  if (!isE2eAuthEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  let body: { context?: { allowed_jurisdictions?: string[] } } = {};
  try {
    body = (await req.json()) as typeof body;
  } catch {
    body = {};
  }

  const allowed = body.context?.allowed_jurisdictions ?? [];
  const includeKimi = allowed.includes("cn");

  const comparison = [
    {
      model: "Claude 4.5 Haiku",
      platform: "Claude Code",
      total_usd: 0.01,
    },
    {
      model: "Kimi K2.5",
      platform: "Cursor",
      total_usd: 0.005,
    },
  ];

  return NextResponse.json({
    model: includeKimi ? "Kimi K2.5" : "Claude 4.5 Haiku",
    platform: includeKimi ? "Cursor" : "Claude Code",
    settings: {
      rationale: includeKimi
        ? "Candidates include Kimi K2.5."
        : "Default western-market pick.",
    },
    session_cost_estimate: { total_usd: 0.01 },
    comparison_table: comparison,
  });
}
