// web/lib/ladder-task.ts
//
// What a task was read as: the category and complexity its picks were ranked
// for, and whether it is a new kind of problem. The AI recommender reads this
// from the visitor's words (the service reports the frontier-table row it
// copied the picks from); on Quick pick the visitor chooses it. A roadmap's
// Settings print the same line under their ladder ("Ranked for coding, high
// complexity.").
//
// Pure: safe to import from client components and from the edge.

import type { LadderTask } from "./api";
import { CATEGORY_DEFS, type Category } from "./catalog-fields";
import { KEYLESS_CATEGORIES, KEYLESS_COMPLEXITIES, type KeylessComplexity } from "./keyless";

const COMPLEXITY_LABEL: Record<KeylessComplexity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

// The service's `task`, checked field by field; null for anything else, so a
// malformed or absent value reads as "not classified".
export function parseLadderTask(value: unknown): LadderTask | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (!(KEYLESS_CATEGORIES as readonly unknown[]).includes(v.category)) return null;
  if (!(KEYLESS_COMPLEXITIES as readonly unknown[]).includes(v.complexity)) return null;
  return { category: v.category as string, complexity: v.complexity as string, novel: v.novel === true };
}

export function categoryLabel(category: string): string {
  return CATEGORY_DEFS[category as Category]?.label ?? category;
}

export function complexityLabel(complexity: string): string {
  return COMPLEXITY_LABEL[complexity as KeylessComplexity] ?? complexity;
}

// "coding, high complexity" / "planning, high complexity, a new kind of
// problem": the classification as a roadmap's ladder note words it.
export function rankedFor(task: LadderTask): string {
  return (
    `${categoryLabel(task.category).toLowerCase()}, ${complexityLabel(task.complexity).toLowerCase()} complexity` +
    (task.novel && task.complexity === "high" ? ", a new kind of problem" : "")
  );
}
