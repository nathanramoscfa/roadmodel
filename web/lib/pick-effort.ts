// web/lib/pick-effort.ts
//
// A pick runs its model at an effort, and Artificial Analysis measures a
// reasoning model at each effort separately: GPT-6 Luna reads 21.5 on the AA
// Index at low and 38.1 at max. The recommender reads its picks off the
// viewer's frontier drawn over each model at every effort AA measured
// (roadmodel scoring.effort_settings), each placed at its blended list price
// times the tokens it draws at that effort (tokenMultiplier). A pick's facts
// read the same way here:
// its AA Index and Score at the effort it runs, and whether anything the
// viewer can run beats it there.
import { blendedPrice, scoreFor } from "@/lib/benchmark-grid";
import { inPool, type PicksData, type SlimRow } from "@/lib/recommend-picks";

// Expected output tokens at each effort, relative to a typical model at high,
// for a model or effort not measured (docs/effort-tokens.json). Mirrors
// EFFORT_TOKEN_MULTIPLIER in src/roadmodel/scoring.py
// (tests/test_web_effort_sync.py holds the two together).
export const EFFORT_TOKEN_MULTIPLIER = {
  low: 0.6,
  medium: 0.8,
  high: 1,
  xhigh: 1.6,
  max: 2.5,
} as const;

export type EffortLevel = keyof typeof EFFORT_TOKEN_MULTIPLIER;

// The tokens a model draws at an effort, relative to a typical model at high:
// measured where update/measure_effort_tokens.py ran it there, else the
// uniform table. Mirrors scoring.token_multiplier.
export function tokenMultiplier(row: SlimRow, level: EffortLevel): number {
  return row.token_multiplier_by_effort?.[level] ?? EFFORT_TOKEN_MULTIPLIER[level];
}

// A surface's word for a level, compared case- and spacing-free: Claude
// Code's "Extra high" is xhigh, its Ultracode stands for max, and so does
// Codex's ultra (the scorer reads both as max).
const LEVEL_WORDS: Record<string, EffortLevel> = {
  low: "low",
  medium: "medium",
  high: "high",
  xhigh: "xhigh",
  extrahigh: "xhigh",
  max: "max",
  ultracode: "max",
  ultra: "max",
};

const LEVEL_LABEL: Record<EffortLevel, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

export function effortLabel(level: EffortLevel): string {
  return LEVEL_LABEL[level];
}

// Any AA effort name as the dials word it ("xhigh" → "Extra high"), Gemini's
// "minimal" included; an unknown name is shown as given.
export function effortWord(level: string): string {
  if (level === "minimal") return "Minimal";
  return level in LEVEL_LABEL ? LEVEL_LABEL[level as EffortLevel] : level;
}

// The level a pick's settings run it at: Effort, or Intelligence on Codex.
export function pickEffort(settings: Record<string, unknown> | null | undefined): EffortLevel | null {
  const raw = settings?.effort ?? settings?.intelligence;
  if (typeof raw !== "string" || !raw) return null;
  return LEVEL_WORDS[raw.toLowerCase().replace(/[\s_-]+/g, "")] ?? null;
}

export interface EffortPoint {
  row: SlimRow;
  level: EffortLevel | null;
  index: number;
  price: number;
}

// A model's points on the frontier: one per effort AA measured, priced by
// the tokens it draws there (tokenMultiplier), or its headline figure at list
// price.
export function effortPoints(row: SlimRow): EffortPoint[] {
  const blended = blendedPrice(row.input_price_per_1m, row.output_price_per_1m);
  const by = row.aa_index_by_effort ?? {};
  const levels = Object.keys(by).filter((l): l is EffortLevel => l in EFFORT_TOKEN_MULTIPLIER);
  if (levels.length === 0) {
    return row.aa_index === null ? [] : [{ row, level: null, index: row.aa_index, price: blended }];
  }
  return levels.map((level) => ({
    row,
    level,
    index: by[level],
    price: blended * tokenMultiplier(row, level),
  }));
}

// The model's row read at one effort: named for it, its AA Index there.
export function named(row: SlimRow, level: EffortLevel, index: number): SlimRow {
  return { ...row, name: `${row.name} · ${effortLabel(level)}`, aa_index: index };
}

export interface PickAtEffort {
  // The pick's row as it runs: named for its effort, its AA Index, Score and
  // frontier mark read there. The model's own row when AA did not measure
  // the pick's effort (or the pick names none).
  row: SlimRow;
  // What beats it at its price or less, read the same way; null on the
  // frontier or with no measured effort (the row's own mark then holds).
  leader: SlimRow | null;
  // The effort the facts were read at, or null.
  level: EffortLevel | null;
}

export function pickAtEffort(data: PicksData, row: SlimRow, level: EffortLevel | null): PickAtEffort {
  const index = level ? row.aa_index_by_effort?.[level] : undefined;
  if (!level || index === undefined) {
    const leader = row.value_beaten_by ? (data.rows[row.value_beaten_by] ?? null) : null;
    return { row, leader, level: null };
  }
  const blended = blendedPrice(row.input_price_per_1m, row.output_price_per_1m);
  const price = blended * tokenMultiplier(row, level);
  // The strongest point the viewer can run at this price or less that scores
  // higher; ties on index go to the cheaper.
  const leader =
    Object.values(data.rows)
      .filter((r) => inPool(data, r))
      .flatMap(effortPoints)
      .filter((p) => p.price <= price + 1e-9 && p.index > index)
      .sort((a, b) => b.index - a.index || a.price - b.price)[0] ?? null;
  const at: SlimRow = {
    ...named(row, level, index),
    value_score: scoreFor(data.fit, row.tier_cost, blended, index),
    value_frontier: inPool(data, row) && leader === null,
    value_beaten_by: leader ? leader.row.id : null,
  };
  return {
    row: at,
    leader: leader ? (leader.level ? named(leader.row, leader.level, leader.index) : leader.row) : null,
    level,
  };
}
