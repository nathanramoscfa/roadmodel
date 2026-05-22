// web/lib/roadmap-prompts.ts
//
// Provider-portable prompt assembly for the roadmap builder. The
// shape here is the cache-prefix contract Step 6 builds on:
//
//   segment 0  orientation
//   segment 1  project-roadmap-template.md      ──┐ stable cache prefix
//   segment 2  phase-roadmap-template.md        ──┘ (segments 1+2)
//   segment 3  per-user profile                    (after cache prefix)
//
// Segments are joined with the literal sentinel "\n\n" between
// them so cache-prefix detection can split on a known delimiter
// without re-parsing the templates. Per-user variation lives in
// segment 3 only — the cached prefix (segments 0–2) is identical
// across users so the cached-content resource is reusable.
//
// The Phase 5 paid frontier Anthropic adapter consumes the same
// segments via getRoadmapPromptParts() without re-reading the
// template files, so prompt parity across providers is enforced
// by construction rather than by a parallel set of template
// loaders.

import { promises as fs } from "node:fs";
import path from "node:path";

import { DEFAULT_PROFILE, type Profile } from "./profile";
import type { Message } from "./roadmap-types";

export const PROMPT_SEGMENT_DELIMITER = "\n\n";

export const ROADMAP_ORIENTATION = [
  "You are roadmodel, a roadmap builder grounded in the following",
  "templates. Ask at most 3–5 clarifying questions before drafting.",
  "Output a Markdown roadmap once you have enough context.",
].join(" ");

export interface RoadmapPromptParts {
  orientation: string;
  projectTemplate: string;
  phaseTemplate: string;
  profile: string;
}

interface LoadOptions {
  profile: Profile | null;
  messages_so_far?: Message[];
}

// Templates are bundled with the deployment (docs/templates/*) and
// the path resolves relative to the repo root regardless of where
// Next.js boots from. process.cwd() inside a Vercel Function points
// to the project root by default — see Vercel docs on serverless
// function file inclusion.
const REPO_ROOT = path.resolve(process.cwd(), "..");

const PROJECT_TEMPLATE_PATH = path.join(
  REPO_ROOT,
  "docs",
  "templates",
  "project-roadmap-template.md",
);
const PHASE_TEMPLATE_PATH = path.join(
  REPO_ROOT,
  "docs",
  "templates",
  "phase-roadmap-template.md",
);

const templateCache = new Map<string, string>();

async function readTemplate(absPath: string): Promise<string> {
  const cached = templateCache.get(absPath);
  if (cached !== undefined) {
    return cached;
  }
  const text = await fs.readFile(absPath, "utf8");
  templateCache.set(absPath, text);
  return text;
}

function renderProfileSegment(profile: Profile | null): string {
  const subscriptions = profile?.subscriptions?.length
    ? profile.subscriptions.join(", ")
    : DEFAULT_PROFILE.subscriptions.length
      ? DEFAULT_PROFILE.subscriptions.join(", ")
      : "(none declared)";
  const budget =
    profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority;
  const jurisdictions = (
    profile?.allowed_jurisdictions ?? DEFAULT_PROFILE.allowed_jurisdictions
  ).join(", ");

  return [
    "User context:",
    `subscriptions = [${subscriptions}]`,
    `budget = ${budget}`,
    `allowed_jurisdictions = [${jurisdictions}]`,
  ].join("\n");
}

export async function getRoadmapPromptParts(
  profile: Profile | null,
): Promise<RoadmapPromptParts> {
  const [projectTemplate, phaseTemplate] = await Promise.all([
    readTemplate(PROJECT_TEMPLATE_PATH),
    readTemplate(PHASE_TEMPLATE_PATH),
  ]);
  return {
    orientation: ROADMAP_ORIENTATION,
    projectTemplate,
    phaseTemplate,
    profile: renderProfileSegment(profile),
  };
}

export async function loadSystemInstruction(
  opts: LoadOptions,
): Promise<string> {
  const parts = await getRoadmapPromptParts(opts.profile);
  return [
    parts.orientation,
    parts.projectTemplate,
    parts.phaseTemplate,
    parts.profile,
  ].join(PROMPT_SEGMENT_DELIMITER);
}

// Heuristic token counter — chars / 4 floor. Gemini's official
// tokenizer is more precise, but the budget here is the rolling
// message history against 2.5/3 Flash's 1M context window plus
// the cachedContent prefix-minimum check Step 6 enforces. A
// pessimistic 4-chars-per-token estimate over-counts slightly,
// which is the right side to err on for budgeting.
export function countTokens(input: Message[] | string): number {
  if (typeof input === "string") {
    return Math.floor(input.length / 4);
  }
  const total = input.reduce((sum, m) => sum + m.content.length, 0);
  return Math.floor(total / 4);
}

// Exported for test-only cache reset. Production code paths leave
// the cache hot for the lifetime of the Function instance, which
// matters more under Fluid Compute (instances are reused across
// requests).
export function _resetTemplateCacheForTest(): void {
  templateCache.clear();
}
