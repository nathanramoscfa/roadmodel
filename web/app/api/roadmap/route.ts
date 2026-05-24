// web/app/api/roadmap/route.ts
//
// Phase 4 Step 4 streaming roadmap builder. The /recommend route
// (Phase 3) is a JSON proxy to the FastAPI service; this route
// streams Server-Sent Events directly from the Next.js tier
// because the roadmap conversation is multi-turn and the Gemini
// SDK exposes streaming natively. Auth + rate-limit layering
// mirrors /recommend, with one extension: a per-user 3-per-30-day
// monthly cap on top of the existing IP-pool burst+daily limits.
//
// Phase 4 Step 5 extends the handler to persist conversations,
// messages, and the latest RoadmapDraft to Supabase. The first
// SSE event in a new conversation now carries the conversation_id
// so the client can include it on subsequent POSTs. On stream
// completion the route inserts the assistant message and upserts
// the roadmap row (when a draft surfaced); a roadmap_persisted
// SSE event delivers the roadmaps.id back to the client so the
// export panel can link to /api/roadmaps/[id]/export.

import { NextResponse } from "next/server";
import { z } from "zod";

import { writeAudit } from "@/lib/audit";
import { AuthError, requireSession } from "@/lib/auth";
import {
  createConversation,
  insertMessage,
  updateConversationTitle,
  upsertRoadmap,
} from "@/lib/conversations";
import { env } from "@/lib/env";
import type { CacheStats } from "@/lib/llm-cache";
import { resolveRoadmapEngine } from "@/lib/model-routing";
import { getProfile } from "@/lib/profile";
import { checkRoadmapMonthlyLimit } from "@/lib/ratelimit";
import { createRoadmapStream } from "@/lib/roadmap-engine";
import type { RoadmapDraft } from "@/lib/roadmap-types";
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
  // Step 6 — engine is resolved server-side at request time so the
  // resolver's frontier-branch gate sees both the env-var default
  // and the per-user override before the stream opens. The Phase 5
  // defensive throw inside createRoadmapStream catches any
  // accidental routing to the Anthropic branch during Phase 4.
  const envFrontierEnabled = env.FRONTIER_ROADMAP_ENABLED;
  const engine = resolveRoadmapEngine({ profile, envFrontierEnabled });

  // Resolve the conversation row up front. On a brand-new
  // conversation the client omits conversation_id; we mint one
  // here and surface it on the first SSE event. On subsequent
  // turns the client echoes the id back so the persistence side
  // appends to the existing thread instead of forking a new one.
  let conversationId = parsed.data.conversation_id ?? null;
  let conversationCreated = false;
  if (!conversationId) {
    try {
      const created = await createConversation({ userId });
      conversationId = created.id;
      conversationCreated = true;
    } catch (err) {
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "roadmap_error",
        error_class: err instanceof Error ? err.name : "conversation_create_failed",
        user_id: userId,
      });
      return NextResponse.json(
        { error: "roadmap_unavailable" },
        { status: 503 },
      );
    }
  }

  // Persist the new user message (the most recent payload entry
  // with role === "user"). Earlier messages were persisted on
  // prior POSTs; re-inserting them would create duplicate rows.
  const incoming = parsed.data.messages;
  const newestUser = [...incoming]
    .reverse()
    .find((m) => m.role === "user");
  if (newestUser) {
    await insertMessage({
      conversationId,
      userId,
      role: "user",
      content: newestUser.content,
    });
  }

  const conversationIdFinal = conversationId;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      // Echo the conversation_id first so the client can pin it
      // to its in-memory state before any tokens stream in.
      controller.enqueue(
        sseLine({
          type: "conversation",
          conversation_id: conversationIdFinal,
          created: conversationCreated,
        }),
      );

      let assistantContent = "";
      let latestDraft: RoadmapDraft | null = null;

      try {
        const events = createRoadmapStream({
          messages: parsed.data.messages,
          profile,
          envFrontierEnabled,
          engine,
        });
        let inputTokens: number | undefined;
        let outputTokens: number | undefined;
        let cacheStats: CacheStats | undefined;
        for await (const event of events) {
          controller.enqueue(sseLine(event));
          if (event.type === "message_delta") {
            assistantContent += event.delta;
          } else if (event.type === "roadmap_draft") {
            latestDraft = event.draft;
          } else if (event.type === "message_complete") {
            if (event.content) {
              assistantContent = event.content;
            }
            inputTokens = event.input_tokens;
            outputTokens = event.output_tokens;
            cacheStats = event.cache_stats;
          }
        }

        // Persistence runs after the generator drains so a Gemini
        // failure mid-stream leaves the conversation row in a
        // clean "user message logged, no assistant reply" state
        // rather than half-writing the assistant turn.
        if (assistantContent.trim().length > 0) {
          await insertMessage({
            conversationId: conversationIdFinal,
            userId,
            role: "assistant",
            content: assistantContent,
          });
        }
        if (latestDraft) {
          const upserted = await upsertRoadmap({
            conversationId: conversationIdFinal,
            userId,
            draft: latestDraft,
          });
          if (upserted) {
            controller.enqueue(
              sseLine({
                type: "roadmap_persisted",
                roadmap_id: upserted.id,
                conversation_id: conversationIdFinal,
              }),
            );
          }
          if (latestDraft.title) {
            await updateConversationTitle({
              conversationId: conversationIdFinal,
              userId,
              title: latestDraft.title,
            });
          }
        }

        controller.close();
        void writeAudit({
          ip_hash: id.ipHash,
          ua_hash: id.uaHash,
          route: id.route,
          outcome: "ok",
          provider: engine.provider,
          model: engine.engine,
          input_tokens: inputTokens,
          output_tokens: outputTokens,
          user_id: userId,
          cache_stats: cacheStats,
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
          provider: engine.provider,
          model: engine.engine,
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
