// web/app/api/roadmap/route.ts
//
// Phase 4 Step 4 streaming roadmap builder. The /recommend route
// (Phase 3) is a JSON proxy to the FastAPI service; this route
// streams Server-Sent Events directly from the Next.js tier
// because the roadmap conversation is multi-turn and the Gemini
// SDK exposes streaming natively. Auth + rate-limit layering
// mirrors /recommend, with one extension: a per-user 3-per-30-day
// monthly cap on top of the existing IP-pool burst+daily limits.

import { NextResponse } from "next/server";
import { z } from "zod";

import { writeAudit } from "@/lib/audit";
import { AuthError, requireSession } from "@/lib/auth";
import { getProfile } from "@/lib/profile";
import { checkRoadmapMonthlyLimit } from "@/lib/ratelimit";
import {
  createRoadmapStream,
  DEFAULT_ROADMAP_MODEL,
  type RoadmapModel,
} from "@/lib/roadmap-engine";
import { identifyRequest, withRateLimit } from "@/lib/withRateLimit";

const messageSchema = z.object({
  id: z.string().min(1),
  role: z.enum(["user", "assistant"]),
  content: z.string().min(1).max(20_000),
  created_at: z.string().min(1),
});

const payloadSchema = z.object({
  messages: z.array(messageSchema).min(1).max(50),
  conversation_id: z.string().uuid().optional(),
});

const ENCODER = new TextEncoder();

function sseLine(payload: unknown): Uint8Array {
  return ENCODER.encode(`data: ${JSON.stringify(payload)}\n\n`);
}

const handler = async (req: Request): Promise<Response> => {
  const id = identifyRequest(req);

  let userId: string;
  try {
    const session = await requireSession();
    userId = session.id;
  } catch (err) {
    const status = err instanceof AuthError ? err.status : 401;
    void writeAudit({
      ip_hash: id.ipHash,
      ua_hash: id.uaHash,
      route: id.route,
      outcome: "unauthorized",
    });
    return NextResponse.json({ error: "unauthorized" }, { status });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    void writeAudit({
      ip_hash: id.ipHash,
      ua_hash: id.uaHash,
      route: id.route,
      outcome: "bad_input",
      error_class: "invalid_json",
      user_id: userId,
    });
    return NextResponse.json({ error: "bad_input" }, { status: 400 });
  }

  const parsed = payloadSchema.safeParse(body);
  if (!parsed.success) {
    void writeAudit({
      ip_hash: id.ipHash,
      ua_hash: id.uaHash,
      route: id.route,
      outcome: "bad_input",
      error_class: "zod_invalid",
      user_id: userId,
    });
    return NextResponse.json(
      { error: "bad_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }

  // Per-user monthly cap. Runs AFTER the IP-pool burst+daily limit
  // (enforced by withRateLimit wrapper) so a single user can't
  // burn through the monthly allowance via burst traffic from a
  // shared IP, and a shared IP can't be DoS'd into a 429 by a
  // single rogue user-id.
  let monthly;
  try {
    monthly = await checkRoadmapMonthlyLimit(userId);
  } catch (err) {
    void writeAudit({
      ip_hash: id.ipHash,
      ua_hash: id.uaHash,
      route: id.route,
      outcome: "roadmap_error",
      error_class: err instanceof Error ? err.name : "ratelimit_failed",
      user_id: userId,
    });
    return NextResponse.json(
      { error: "roadmap_unavailable" },
      { status: 503 },
    );
  }
  if (!monthly.allowed) {
    void writeAudit({
      ip_hash: id.ipHash,
      ua_hash: id.uaHash,
      route: id.route,
      outcome: "roadmap_monthly_cap",
      user_id: userId,
    });
    return NextResponse.json(
      { error: "roadmap_monthly_cap", retry_after: monthly.retryAfter },
      {
        status: 429,
        headers: { "Retry-After": String(monthly.retryAfter ?? 86_400) },
      },
    );
  }

  const profile = await getProfile(userId);
  const model: RoadmapModel = DEFAULT_ROADMAP_MODEL;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        const events = createRoadmapStream({
          messages: parsed.data.messages,
          profile,
          model,
        });
        let inputTokens: number | undefined;
        let outputTokens: number | undefined;
        for await (const event of events) {
          controller.enqueue(sseLine(event));
          if (event.type === "message_complete") {
            inputTokens = event.input_tokens;
            outputTokens = event.output_tokens;
          }
        }
        controller.close();
        void writeAudit({
          ip_hash: id.ipHash,
          ua_hash: id.uaHash,
          route: id.route,
          outcome: "ok",
          provider: "google",
          model,
          input_tokens: inputTokens,
          output_tokens: outputTokens,
          user_id: userId,
        });
      } catch (err) {
        controller.enqueue(
          sseLine({
            type: "error",
            error: "roadmap_error",
            message: err instanceof Error ? err.message : "unknown",
          }),
        );
        controller.close();
        void writeAudit({
          ip_hash: id.ipHash,
          ua_hash: id.uaHash,
          route: id.route,
          outcome: "roadmap_error",
          provider: "google",
          model,
          error_class: err instanceof Error ? err.name : "stream_failed",
          user_id: userId,
        });
      }
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
};

// IP-pool burst+daily limit wraps the inner handler; per-user
// monthly cap is enforced inside the handler. Both layers share
// the same withRateLimit + Upstash backend, so a single Upstash
// outage policy controls all three knobs.
export const POST = withRateLimit(handler, async () => {
  try {
    const session = await requireSession();
    return session.id;
  } catch {
    return undefined;
  }
});
