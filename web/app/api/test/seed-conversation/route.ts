// web/app/api/test/seed-conversation/route.ts
//
// E2E-only seed helper for Phase 4 Step 5 Playwright tests.
// Inserts a conversation + its messages + optional roadmap draft
// directly into the in-memory store, bypassing the streaming
// /api/roadmap flow. Mirrors the /api/test/e2e-reset and
// /api/test/mock-recommend patterns: the route returns 404 when
// the E2E gate is off so production routes never expose this
// shape.

import { NextResponse } from "next/server";
import { z } from "zod";

import { e2eSeedConversation } from "@/lib/conversations";
import { isE2eAuthEnabled } from "@/lib/profile";

const messageSchema = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string().min(1),
});

const draftSchema = z.object({
  title: z.string().optional(),
  project_overview: z.string(),
  phases: z
    .array(
      z.object({
        title: z.string(),
        goal: z.string(),
        sub_sections: z.array(z.string()),
        acceptance_criteria: z.array(z.string()),
      }),
    )
    .default([]),
  glossary: z
    .array(z.object({ term: z.string(), definition: z.string() }))
    .default([]),
  generated_at: z.string().default(() => new Date().toISOString()),
});

const payloadSchema = z.object({
  user_id: z.string().uuid(),
  title: z.string().optional(),
  updated_at: z.string().optional(),
  messages: z.array(messageSchema).default([]),
  draft: draftSchema.optional(),
});

export async function POST(req: Request): Promise<Response> {
  if (!isE2eAuthEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  const body = await req.json();
  const parsed = payloadSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "bad_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const row = e2eSeedConversation({
    userId: parsed.data.user_id,
    title: parsed.data.title,
    updatedAt: parsed.data.updated_at,
    messages: parsed.data.messages,
    draft: parsed.data.draft,
  });
  return NextResponse.json({ id: row.id });
}
