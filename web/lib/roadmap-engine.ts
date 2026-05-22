// web/lib/roadmap-engine.ts
//
// Engine-facing wrapper for the roadmap builder. Phase 4 default
// engine is Gemini 2.5 Flash; the FAIL-escalation pick is Gemini 3
// Flash. Both use the same @google/genai SDK call shape — only the
// model string changes. A Phase 5 Anthropic adapter slots in by
// adding an `if` branch on the model-string prefix; the public
// signature (caller passes a `model` string, receives SSE events of
// the documented shape) is engine-agnostic by construction.
//
// This file is the only place in Phase 4 that imports the
// @google/genai SDK directly. Step 6 will wrap createRoadmapStream
// with the Gemini cachedContent creation + reuse logic — the
// systemInstruction assembly here is already structured to keep
// segments 0–2 stable across users for that purpose.

import type {
  GenerateContentParameters,
  GenerateContentResponse,
} from "@google/genai";

import { resolveGeminiClient, withGeminiRetry, GEMINI_MAX_OUTPUT_TOKENS } from "./gemini-client";
import type { Profile } from "./profile";
import { loadSystemInstruction } from "./roadmap-prompts";
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
}

export type RoadmapStreamEvent =
  | MessageDeltaEvent
  | RoadmapDraftEvent
  | MessageCompleteEvent;

interface CreateRoadmapStreamArgs {
  messages: Message[];
  profile: Profile | null;
  model?: RoadmapModel;
}

// Convert the rolling chat history into the @google/genai
// `contents` shape: oldest-first, alternating user/model. The
// cache-prefix contract (see Step 6) depends on this ordering —
// reversing it would invalidate the systemInstruction prefix's
// cache key on every turn.
function toGeminiContents(
  messages: Message[],
): GenerateContentParameters["contents"] {
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
const EXECUTIVE_SUMMARY_RE = /(?:^|\n)#{1,3}\s+Executive Summary\s*\n+([\s\S]*?)(?=\n#{1,3}\s|\n*$)/i;
const ACCEPTANCE_RE = /Acceptance criteria\s*\n+((?:[-*]\s+[^\n]+\n?)+)/i;
const GLOSSARY_RE = /(?:^|\n)#{1,3}\s+Glossary\s*\n+([\s\S]*?)(?=\n#{1,3}\s|\n*$)/i;
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

export async function* createRoadmapStream(
  args: CreateRoadmapStreamArgs,
): AsyncIterable<RoadmapStreamEvent> {
  const model = args.model ?? DEFAULT_ROADMAP_MODEL;
  const systemInstruction = await loadSystemInstruction({
    profile: args.profile,
    messages_so_far: args.messages,
  });
  const contents = toGeminiContents(args.messages);

  const client = resolveGeminiClient();
  const stream = await withGeminiRetry(() =>
    client.models.generateContentStream({
      model,
      contents,
      config: {
        systemInstruction,
        maxOutputTokens: GEMINI_MAX_OUTPUT_TOKENS,
      },
    }),
  );

  let buffered = "";
  let lastDraftJson: string | null = null;
  let inputTokens: number | undefined;
  let outputTokens: number | undefined;

  for await (const chunk of stream) {
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

  yield {
    type: "message_complete",
    content: buffered,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
  };
}
