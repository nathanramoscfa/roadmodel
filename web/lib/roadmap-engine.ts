// web/lib/roadmap-engine.ts
//
// Engine-facing wrapper for the roadmap builder. Phase 4 routes
// every request through resolveRoadmapEngine() (web/lib/model-
// routing.ts) so the model string + provider come from the
// catalog-tracked resolver rather than a hard-coded literal. The
// Phase 5 paid-frontier Anthropic branch is defended here: the
// resolver returns a valid Anthropic configuration when the
// FRONTIER_ROADMAP_ENABLED env var or the per-user override fires,
// but this wrapper throws a documented "Phase 5 scope" error if
// the branch is ever actually invoked during Phase 4.
//
// Step 6 adds Google `cachedContent` integration via the
// provider-agnostic facade in web/lib/llm-cache.ts. The
// orientation + project + phase template segments form the
// stable cache prefix; the per-user profile segment stays AFTER
// the cached prefix so per-user variation does not invalidate
// the shared cachedContent resource. On cache reuse, the SDK
// reports `cachedContentTokenCountUsed > 0` on subsequent turns
// — the 70 % cache-hit-rate target acceptance criterion checks
// that signal across a representative sample.

import type { GenerateContentResponse } from "@google/genai";

import { resolveGeminiClient, withGeminiRetry, GEMINI_MAX_OUTPUT_TOKENS } from "./gemini-client";
import {
  extractCacheStats,
  getOrCreateCachedPrefix,
  type CacheStats,
  type GoogleCacheClient,
} from "./llm-cache";
import {
  resolveRoadmapEngine,
  type ResolvedEngine,
} from "./model-routing";
import type { Profile } from "./profile";
import { getRoadmapPromptParts } from "./roadmap-prompts";
import type {
  GlossaryEntry,
  Message,
  RoadmapDraft,
  RoadmapPhase,
} from "./roadmap-types";

export type RoadmapModel =
  | "gemini-2.5-flash"
  | "gemini-3-flash"
  | (string & {});

// Step 4 PASS default kept for backward compatibility with any
// caller that still passes an explicit `model` literal; in Step 6
// the route handler delegates to resolveRoadmapEngine() and lets
// the resolver pick the catalog-tracked engine.
export const DEFAULT_ROADMAP_MODEL: RoadmapModel = "gemini-2.5-flash";

export interface MessageDeltaEvent {
  type: "message_delta";
  delta: string;
}

export interface RoadmapDraftEvent {
  type: "roadmap_draft";
  draft: RoadmapDraft;
}

export interface MessageCompleteEvent {
  type: "message_complete";
  content: string;
  input_tokens?: number;
  output_tokens?: number;
  cache_stats?: CacheStats;
  engine?: string;
  provider?: string;
}

export type RoadmapStreamEvent =
  | MessageDeltaEvent
  | RoadmapDraftEvent
  | MessageCompleteEvent;

interface CreateRoadmapStreamArgs {
  messages: Message[];
  profile: Profile | null;
  // Step 6 onward callers pass envFrontierEnabled from the route
  // handler so the resolver can gate the Phase 5 frontier branch.
  // The route reads env.FRONTIER_ROADMAP_ENABLED at request time
  // rather than at module-load so test fixtures can flip the flag
  // between describe blocks.
  envFrontierEnabled?: boolean;
  // Pre-resolved engine override (used by tests and by callers
  // that want to force a specific model). Production callers omit
  // this and let resolveRoadmapEngine() compute it from the
  // profile.
  engine?: ResolvedEngine;
  // Back-compat for any caller that still passes an explicit model
  // string (e.g. legacy tests). When provided this wins over the
  // resolver. Phase 5+ should remove this in favor of `engine`.
  model?: RoadmapModel;
}

// Convert the rolling chat history into the @google/genai
// `contents` shape: oldest-first, alternating user/model. The
// cache-prefix contract (see Step 6) depends on this ordering —
// reversing it would invalidate the systemInstruction prefix's
// cache key on every turn.
type GeminiTurn = { role: "user" | "model"; parts: { text: string }[] };

function toGeminiContents(messages: Message[]): GeminiTurn[] {
  return messages.map((m) => ({
    role: m.role === "assistant" ? "model" : "user",
    parts: [{ text: m.content }],
  }));
}

// Heuristic draft extractor. Triggers when the buffered assistant
// output contains a top-level "# " heading followed downstream by
// an "Executive Summary" block. The shape we emit matches
// RoadmapDraft so PreviewPanel can render without further parsing.
// If any required region is missing, return null — the route
// handler skips the roadmap_draft event for that chunk and the
// assistant message still streams as plain text.
// The bundled project-roadmap-template.md NUMBERS its section headings
// ("## 1. Executive Summary", "## 7. Glossary"), and the model follows
// the template faithfully — so the heading matchers MUST tolerate an
// optional leading section number (e.g. "1. ", "1.2 ", "7. "). The
// pre-#158 patterns required a bare "## Executive Summary" and silently
// failed on every real roadmap, so parseRoadmapDraft returned null and
// the preview panel never populated (issue #158).
const SECTION_NUM = String.raw`(?:\d+(?:\.\d+)*\.?\s+)?`;
const EXECUTIVE_SUMMARY_RE = new RegExp(
  `(?:^|\\n)#{1,3}\\s+${SECTION_NUM}Executive Summary\\s*\\n+([\\s\\S]*?)(?=\\n#{1,3}\\s|\\n*$)`,
  "i",
);
const ACCEPTANCE_RE = /Acceptance criteria\s*\n+((?:[-*]\s+[^\n]+\n?)+)/i;
const GLOSSARY_RE = new RegExp(
  `(?:^|\\n)#{1,3}\\s+${SECTION_NUM}Glossary\\s*\\n+([\\s\\S]*?)(?=\\n#{1,3}\\s|\\n*$)`,
  "i",
);
const TOP_HEADING_RE = /(?:^|\n)#\s+[^\n]+/;
// Title capture mirrors TOP_HEADING_RE but in a capturing form so
// the parsed draft carries the project name. Step 5 stores this
// as a top-level field on roadmaps.draft so the /history search
// can index by name without re-parsing the body on every query.
const TITLE_CAPTURE_RE = /(?:^|\n)#\s+([^\n]+)/;

function parseBulletList(block: string): string[] {
  return block
    .split("\n")
    .map((line) => line.replace(/^\s*[-*]\s+/, "").trim())
    .filter((line) => line.length > 0);
}

function parseRoadmapDraft(buffered: string): RoadmapDraft | null {
  if (!TOP_HEADING_RE.test(buffered)) {
    return null;
  }
  const summaryMatch = buffered.match(EXECUTIVE_SUMMARY_RE);
  if (!summaryMatch) {
    return null;
  }
  const project_overview = summaryMatch[1].trim();

  const phases: RoadmapPhase[] = [];
  const phaseSplitRe = /\n#{2,3}\s+(Phase\s+[^\n]+)\n+/gi;
  const chunks = buffered.split(phaseSplitRe);
  // chunks alternates: [pre, heading1, body1, heading2, body2, ...]
  for (let i = 1; i + 1 < chunks.length; i += 2) {
    const title = chunks[i].trim();
    const body = chunks[i + 1] ?? "";
    const goalMatch = body.match(/(?:^|\n)Goal:\s*([^\n]+)/i);
    const goal = goalMatch
      ? goalMatch[1].trim()
      : body.split("\n").find((l) => l.trim().length > 0)?.trim() ?? "";
    const accMatch = body.match(ACCEPTANCE_RE);
    const acceptance_criteria = accMatch ? parseBulletList(accMatch[1]) : [];
    // Sub-sections: bullets that aren't inside the Acceptance block.
    const bodyWithoutAcc = accMatch
      ? body.replace(accMatch[0], "")
      : body;
    const sub_sections = parseBulletList(bodyWithoutAcc).filter(
      (line) =>
        !/^goal:/i.test(line) &&
        !acceptance_criteria.includes(line),
    );
    phases.push({ title, goal, sub_sections, acceptance_criteria });
  }
  if (phases.length === 0) {
    return null;
  }

  const glossary: GlossaryEntry[] = [];
  const glossMatch = buffered.match(GLOSSARY_RE);
  if (glossMatch) {
    for (const line of glossMatch[1].split("\n")) {
      const m = line.match(/^\s*[-*]\s+\*?\*?([^*:\-—]+?)\*?\*?\s*[—\-:]\s+(.+)$/);
      if (m) {
        glossary.push({ term: m[1].trim(), definition: m[2].trim() });
      }
    }
  }

  const titleMatch = buffered.match(TITLE_CAPTURE_RE);
  const title = titleMatch ? titleMatch[1].trim() : undefined;

  return {
    title,
    project_overview,
    phases,
    glossary,
    generated_at: new Date().toISOString(),
  };
}

// Extract the text delta from a Gemini stream chunk. The
// @google/genai SDK exposes `chunk.text` as a convenience getter
// (concatenated text across candidates[0].content.parts); falling
// back to manual parts traversal keeps the wrapper robust to SDK
// versions that haven't promoted the getter.
function chunkText(chunk: GenerateContentResponse): string {
  const direct = (chunk as unknown as { text?: string | (() => string) }).text;
  if (typeof direct === "string") {
    return direct;
  }
  if (typeof direct === "function") {
    return direct.call(chunk) ?? "";
  }
  const parts = chunk.candidates?.[0]?.content?.parts ?? [];
  return parts
    .map((p) => (typeof p === "object" && p !== null && "text" in p ? p.text : ""))
    .filter((t): t is string => typeof t === "string")
    .join("");
}

// Build the GoogleCacheClient the llm-cache facade calls when no
// memoized cachedContent name exists. Wraps the @google/genai
// SDK's `ai.caches.create` so the facade stays decoupled from the
// SDK type surface — every Phase 5 provider branch slots in
// behind a similar adapter.
function buildGoogleCacheClient(
  client: ReturnType<typeof resolveGeminiClient>,
): GoogleCacheClient {
  return {
    async create({ model, contents, systemInstruction, ttl_seconds }) {
      const created = await client.caches.create({
        model,
        config: {
          contents: contents.map((text) => ({
            role: "user",
            parts: [{ text }],
          })),
          systemInstruction: { role: "system", parts: [{ text: systemInstruction }] },
          ttl: `${ttl_seconds}s`,
        },
      });
      // The SDK's `name` field is nominally optional; in practice
      // a successful create always returns it. Treat absence as a
      // hard failure rather than silently falling back to a
      // non-cached call — a missing name on success means the
      // service contract changed and we want a loud signal.
      if (!created.name) {
        throw new Error(
          "ai.caches.create returned no name; @google/genai contract changed",
        );
      }
      return { name: created.name };
    },
  };
}

export async function* createRoadmapStream(
  args: CreateRoadmapStreamArgs,
): AsyncIterable<RoadmapStreamEvent> {
  const engine: ResolvedEngine =
    args.engine ??
    (args.model
      ? {
          engine: args.model,
          provider: "google",
          force_provider: `google-${args.model}`,
          max_tokens: GEMINI_MAX_OUTPUT_TOKENS,
          use_frontier: false,
        }
      : resolveRoadmapEngine({
          profile: args.profile,
          envFrontierEnabled: args.envFrontierEnabled ?? false,
        }));

  // Phase 5 frontier defensive gate. The resolver returns a valid
  // Anthropic-shape ResolvedEngine when the env flag or per-user
  // override fires; we refuse to execute it during Phase 4 because
  // the @google/genai SDK is the only wrapper that ships this
  // phase. Phase 5 will branch on engine.provider here and call
  // the Anthropic SDK instead of throwing.
  if (engine.use_frontier || engine.provider === "anthropic") {
    throw new Error(
      "Phase 5 scope: anthropic engine branch not yet wired",
    );
  }
  if (engine.provider !== "google") {
    throw new Error(
      `Engine wrapper not implemented for provider=${engine.provider}`,
    );
  }

  const promptParts = await getRoadmapPromptParts(args.profile);
  const cachedContents = [
    promptParts.projectTemplate,
    promptParts.phaseTemplate,
  ];

  // Try to mount the Google cachedContent prefix. The facade
  // returns null when the prefix is below Gemini's minimum size
  // (e.g. tests with short fixture templates) — the wrapper
  // gracefully falls back to a non-cached call rather than
  // crashing the stream.
  const client = resolveGeminiClient();
  let cachedContentName: string | null = null;
  try {
    cachedContentName = await getOrCreateCachedPrefix({
      provider: "google",
      model: engine.engine,
      segments: {
        systemInstruction: promptParts.orientation,
        contents: cachedContents,
      },
      client: buildGoogleCacheClient(client),
    });
  } catch (err) {
    // A cache-create failure is non-fatal: log and continue with a
    // non-cached call. The cache_stats row written below will
    // carry zeros for the cached-content fields, which is the
    // honest representation.
    console.warn("[roadmap-engine] cachedContent setup failed", err);
    cachedContentName = null;
  }

  const baseContents = toGeminiContents(args.messages);

  // Gemini REJECTS a request that sets BOTH cachedContent and
  // system_instruction (issue #161: "CachedContent can not be used
  // with GenerateContent request setting system_instruction"). When a
  // cached prefix is mounted, the orientation + templates already live
  // INSIDE the cached resource, so the request must NOT carry a
  // systemInstruction at all. The per-user profile segment is
  // intentionally NOT cached (so per-user variation never invalidates
  // the shared prefix) — when cached, deliver it as a leading content
  // turn instead. Without a cache we send the full four-segment prompt
  // as systemInstruction, matching the Step 4 baseline.
  const fullSystemInstruction = [
    promptParts.orientation,
    promptParts.projectTemplate,
    promptParts.phaseTemplate,
    promptParts.profile,
  ].join("\n\n");

  const generateConfig: Record<string, unknown> = {
    maxOutputTokens: engine.max_tokens ?? GEMINI_MAX_OUTPUT_TOKENS,
  };
  let contents: GeminiTurn[];
  if (cachedContentName) {
    generateConfig.cachedContent = cachedContentName;
    const profileText = promptParts.profile?.trim();
    contents = profileText
      ? [{ role: "user", parts: [{ text: profileText }] }, ...baseContents]
      : baseContents;
  } else {
    generateConfig.systemInstruction = fullSystemInstruction;
    contents = baseContents;
  }

  const stream = await withGeminiRetry(() =>
    client.models.generateContentStream({
      model: engine.engine,
      contents,
      config: generateConfig as Record<string, unknown>,
    }),
  );

  let buffered = "";
  let lastDraftJson: string | null = null;
  let inputTokens: number | undefined;
  let outputTokens: number | undefined;
  let lastChunk: GenerateContentResponse | null = null;

  for await (const chunk of stream) {
    lastChunk = chunk;
    const delta = chunkText(chunk);
    if (delta) {
      buffered += delta;
      yield { type: "message_delta", delta };
    }

    const usage = (chunk as unknown as {
      usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
    }).usageMetadata;
    if (usage) {
      if (typeof usage.promptTokenCount === "number") {
        inputTokens = usage.promptTokenCount;
      }
      if (typeof usage.candidatesTokenCount === "number") {
        outputTokens = usage.candidatesTokenCount;
      }
    }

    const draft = parseRoadmapDraft(buffered);
    if (draft) {
      const draftJson = JSON.stringify({
        title: draft.title,
        project_overview: draft.project_overview,
        phases: draft.phases,
        glossary: draft.glossary,
      });
      if (draftJson !== lastDraftJson) {
        lastDraftJson = draftJson;
        yield { type: "roadmap_draft", draft };
      }
    }
  }

  // Pull the final usageMetadata off the last chunk so cache_stats
  // captures the cachedContentTokenCount(Used) counters Gemini
  // emits at stream end. extractCacheStats() coalesces missing
  // counters to 0 so the audit row always carries a uniform shape.
  const cache_stats = extractCacheStats("google", lastChunk);

  yield {
    type: "message_complete",
    content: buffered,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    cache_stats,
    engine: engine.engine,
    provider: engine.provider,
  };
}
