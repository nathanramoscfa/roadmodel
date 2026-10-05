// web/app/api/test/mock-recommend/visitor/route.ts
//
// E2E mock for the visitor lane's service endpoint (POST
// /v1/visitor/recommend/ladder, service/app/visitor.py). The edge, on the
// visitor lane, POSTs here with the visitor's key in X-Roadmodel-Visitor-Key.
// It answers like the service: a ladder for a working key, a code for a
// declined one. It never echoes the key: it reports, as booleans, whether the
// key arrived in its header and whether it leaked into the body, so a spec can
// prove the transport without the key ever crossing back.
//
// Test keys choose the answer: one containing "declined" is refused (401
// visitor_key_rejected), one containing "quota" is out of quota (429).
import { NextResponse } from "next/server";

import { isE2eAuthEnabled } from "@/lib/profile";

export async function POST(req: Request): Promise<Response> {
  if (!isE2eAuthEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  const key = req.headers.get("x-roadmodel-visitor-key") ?? "";
  const provider = req.headers.get("x-roadmodel-visitor-provider");
  const text = await req.text();
  if (!key || !provider) {
    return NextResponse.json({ error: "visitor_key_missing", provider }, { status: 400 });
  }
  if (key.includes("declined")) {
    return NextResponse.json({ error: "visitor_key_rejected", provider }, { status: 401 });
  }
  if (key.includes("quota")) {
    return NextResponse.json({ error: "visitor_quota", provider }, { status: 429 });
  }

  let body: { context?: Record<string, unknown> } = {};
  try {
    body = JSON.parse(text) as typeof body;
  } catch {
    body = {};
  }
  const context = body.context ?? {};
  const echo = {
    received_context_keys: Object.keys(context).sort(),
    visitor_key_header: true,
    visitor_key_in_body: text.includes(key),
    visitor_provider: provider,
  };
  const pick = (model: string, model_id: string, effort: string, total_usd: number) => ({
    model,
    platform: "Claude Code",
    settings: { effort, thinking: "On" },
    rationale: `TASK: Coding. PICK: ${model} fits. RUN: Claude Code.`,
    conversation: "New",
    session_cost_estimate: { total_usd },
    comparison_table: [
      { model_name: model, model_id, platform_name: "Claude Code", platform_id: "claude-code", total_usd },
    ],
    ...echo,
  });

  return NextResponse.json({
    picks: {
      quality: pick("Claude Opus 4.8", "opus-4.8", "Max", 0.02),
      balanced: pick("Claude Sonnet 4.6", "sonnet-4.6", "High", 0.01),
      cost: pick("Claude 4.5 Haiku", "claude-4.5-haiku", "Low", 0.002),
    },
    guard: { healthy: true },
    engine: typeof context.force_provider === "string" ? context.force_provider : undefined,
    usage: {
      input_tokens: 61000,
      cached_input_tokens: 56000,
      cache_write_tokens: 0,
      output_tokens: 900,
      reasoning_tokens: 0,
    },
  });
}
