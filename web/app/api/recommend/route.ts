// web/app/api/recommend/route.ts
import { NextResponse } from "next/server";
import { recommendOnServer } from "@/lib/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RecommendBody {
  task_description: string;
  context?: Record<string, unknown>;
}

export async function POST(req: Request) {
  const body = (await req.json()) as RecommendBody;
  if (!body.task_description?.trim()) {
    return NextResponse.json(
      { error: "task_description required" },
      { status: 400 },
    );
  }
  const ctx = {
    ...(body.context ?? {}),
    // Cheap-model default for anonymous web tier; the Phase 2 provider
    // chain falls back to Gemini Flash on Anthropic rejection.
    force_provider: "anthropic-haiku-4-5",
  };
  try {
    const rec = await recommendOnServer(body.task_description, ctx);
    rec.free_tier_label =
      "Free tier (Haiku 4.5) — upgrade for frontier models";
    return NextResponse.json(rec);
  } catch (err) {
    console.error("recommend error", err);
    return NextResponse.json(
      { error: "recommender_unavailable" },
      { status: 502 },
    );
  }
}
