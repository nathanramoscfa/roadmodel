// web/lib/keyless.ts
//
// Quick pick: the keyless lane's request and answer. The page sends a task
// already classified (task type, difficulty, whether it is a new kind of
// problem, budget priority) to /api/recommend/keyless, which asks the
// service's POST /v1/score (service/app/score.py) for the three picks the
// scoring core reads off the cost/quality frontier. The enums here are the
// service's, so a body the edge accepts is one the service accepts.
//
// Pure: safe to import from client components.

import type { BudgetPriority } from "./profile";

export const KEYLESS_CATEGORIES = [
  "coding",
  "planning",
  "agentic",
  "multimodal",
  "long-context",
  "knowledge",
  "speed",
] as const;
export type KeylessCategory = (typeof KEYLESS_CATEGORIES)[number];

export const KEYLESS_COMPLEXITIES = ["low", "medium", "high"] as const;
export type KeylessComplexity = (typeof KEYLESS_COMPLEXITIES)[number];

const BUDGETS: readonly BudgetPriority[] = ["cheap", "balanced", "best"];

export interface KeylessTask {
  category: KeylessCategory;
  complexity: KeylessComplexity;
  novel: boolean;
  budget_priority?: BudgetPriority;
}

// The browser's body, checked field by field. Only these four fields are
// read; anything else in the body is ignored and never forwarded.
export function parseKeylessTask(body: unknown): KeylessTask | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const b = body as Record<string, unknown>;
  if (!(KEYLESS_CATEGORIES as readonly unknown[]).includes(b.category)) return null;
  if (!(KEYLESS_COMPLEXITIES as readonly unknown[]).includes(b.complexity)) return null;
  if (b.novel !== undefined && typeof b.novel !== "boolean") return null;
  if (b.budget_priority !== undefined && !(BUDGETS as readonly unknown[]).includes(b.budget_priority)) return null;
  return {
    category: b.category as KeylessCategory,
    complexity: b.complexity as KeylessComplexity,
    novel: b.novel === true,
    ...(b.budget_priority !== undefined ? { budget_priority: b.budget_priority as BudgetPriority } : {}),
  };
}

// The list fields /v1/score accepts: at most 64 items, each an id-shaped
// token of at most 64 characters. Anything else would be a 422 there.
const ITEM = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
export function scoreList(values: readonly unknown[] | null | undefined): string[] {
  const out: string[] = [];
  for (const v of values ?? []) {
    if (typeof v !== "string") continue;
    const t = v.trim();
    if (t.length > 0 && t.length <= 64 && ITEM.test(t)) out.push(t);
    if (out.length === 64) break;
  }
  return out;
}

export type KeylessPriority = "quality" | "balanced" | "cost";

export interface KeylessRung {
  priority: KeylessPriority;
  model_id: string;
  model_name: string;
  platform_id: string;
  platform_name: string;
  effort: string;
  specialist: boolean;
  backup: {
    model_id: string;
    model_name: string;
    platform_id: string;
    platform_name: string;
    effort: string;
  } | null;
  terms: { quality: number; requirement_shortfall: number; cost: number };
  why: { quality: string; requirement_shortfall: string; cost: string };
}

export interface KeylessResponse {
  rungs: KeylessRung[];
  task: { category: string; complexity: string; novel: boolean; budget_priority: string };
  backup_warning: string | null;
  engine: "scoring-core";
  cost_usd: number;
}

const PRIORITIES: readonly KeylessPriority[] = ["quality", "balanced", "cost"];

function isString(v: unknown): v is string {
  return typeof v === "string";
}

// The service's answer, checked before it reaches the page: three rungs, one
// per priority, each with its model, platform, effort and three sentences.
export function isKeylessResponse(value: unknown): value is KeylessResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as { rungs?: unknown };
  if (!Array.isArray(v.rungs) || v.rungs.length !== 3) return false;
  return v.rungs.every((r: unknown, i) => {
    if (typeof r !== "object" || r === null) return false;
    const rung = r as Record<string, unknown>;
    const why = rung.why as Record<string, unknown> | undefined;
    return (
      rung.priority === PRIORITIES[i] &&
      isString(rung.model_id) &&
      isString(rung.model_name) &&
      isString(rung.platform_name) &&
      isString(rung.effort) &&
      typeof why === "object" &&
      why !== null &&
      isString(why.quality) &&
      isString(why.requirement_shortfall) &&
      isString(why.cost)
    );
  });
}

// The measured agreement the result states (docs/keyless-eval.json, copied
// into the build by scripts/sync-catalog.mjs): picks that matched the AI
// recommender, out of how many, over how many test tasks, and when.
export interface KeylessAgreement {
  agree: number;
  total: number;
  tasks: number;
  evaluatedOn: string;
}
