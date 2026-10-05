// web/app/api/test/mock-recommend/score/route.ts
//
// E2E mock for the keyless picks endpoint (POST /v1/score,
// service/app/score.py). The edge's /api/recommend/keyless POSTs here in E2E
// mock mode. It answers in the service's shape: three rungs, Quality first,
// each with its terms and one sentence per term. It reports the body keys it
// received, so a spec can prove the edge forwards only the allowlisted fields.
import { NextResponse } from "next/server";

import { isE2eAuthEnabled } from "@/lib/profile";

const RUNGS = [
  { priority: "quality", model_id: "claude-opus-5-5", model_name: "Opus 5.5", platform_id: "claude-code", platform_name: "Claude Code", effort: "High" },
  { priority: "balanced", model_id: "gemini-3-8-flash", model_name: "Gemini 3.8 Flash", platform_id: "gemini-api", platform_name: "Gemini API", effort: "Medium" },
  { priority: "cost", model_id: "gpt-6-luna", model_name: "GPT-6 Luna", platform_id: "openai-api", platform_name: "OpenAI API", effort: "Low" },
];

export async function POST(req: Request): Promise<Response> {
  if (!isE2eAuthEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  let body: Record<string, unknown> = {};
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    body = {};
  }
  const category = typeof body.category === "string" ? body.category : "coding";
  const complexity = typeof body.complexity === "string" ? body.complexity : "medium";
  return NextResponse.json({
    rungs: RUNGS.map((r, i) => ({
      ...r,
      specialist: false,
      backup: null,
      terms: { quality: 80 - i * 10, requirement_shortfall: 0, cost: i * 2 },
      why: {
        quality: `${r.model_name} rates ${80 - i * 10} of 100 for ${category} work.`,
        requirement_shortfall: `It clears the bar a ${complexity}-complexity task sets.`,
        cost: `It runs on ${r.platform_name}.`,
      },
    })),
    task: { category, complexity, novel: body.novel === true, budget_priority: body.budget_priority ?? "balanced" },
    backup_warning: null,
    engine: "scoring-core",
    cost_usd: 0,
    received_keys: Object.keys(body).sort(),
  });
}
