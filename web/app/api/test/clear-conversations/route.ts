// web/app/api/test/clear-conversations/route.ts
//
// E2E-only helper for history.spec.ts — clears the conversations
// in-memory store scoped to a specific uid so a parallel
// Playwright worker testing a different feature doesn't wipe
// seeds belonging to history.spec's distinct uid.

import { NextResponse } from "next/server";
import { z } from "zod";

import { e2eClearConversations } from "@/lib/conversations";
import { isE2eAuthEnabled } from "@/lib/profile";

const payloadSchema = z.object({
  user_id: z.string().uuid(),
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
  e2eClearConversations(parsed.data.user_id);
  return NextResponse.json({ ok: true });
}
