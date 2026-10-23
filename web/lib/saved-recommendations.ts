// web/lib/saved-recommendations.ts
//
// Saved recommendations: what a saved entry is, checked on every write, read
// and import, and the file an export writes. Entries live only in the
// visitor's browser (lib/saved-store.ts keeps them in IndexedDB); roadmodel's
// servers never receive them. Nothing here touches storage, so the checks run
// in tests as they are.
import { z } from "zod";
import type { MultiRecommendResponse } from "./api";
import type { KeylessResponse } from "./keyless";

// Kept per account in one browser; past it the oldest go first.
export const MAX_SAVED = 500;
// One entry, serialized. A task is at most 50,000 characters.
export const MAX_ENTRY_BYTES = 512 * 1024;
// An import file. A full export of typical entries is a few megabytes.
export const MAX_IMPORT_BYTES = 64 * 1024 * 1024;
export const EXPORT_FORMAT = "roadmodel.saved-recommendations";

// The list before IndexedDB: localStorage, eight entries. Read once to carry
// it over, then removed.
export const LEGACY_KEY = "roadmodel:recommend-recent";
export const LEGACY_CLEAR_SIGNAL = "roadmodel:recommend-clear-signal";

const priority = z.enum(["cheap", "balanced", "best"]);
const text = z.string().max(50_000);
const scalar = z.union([text, z.number().finite(), z.boolean(), z.null()]);
const fields = z.record(z.string().max(100), z.union([scalar, z.array(scalar).max(128)])).refine((v) => Object.keys(v).length <= 64);
const pick = z.object({
  priority, model: z.string().min(1).max(256), platform: z.string().max(256),
  settings: fields, session_cost_estimate: fields.default({}),
  comparison_table: z.array(fields).max(128),
  rationale_sections: z.record(z.string(), text).nullable().optional(),
  backup: z.object({ model: text, platform: text.nullable(), settings: z.record(z.string(), text) }).nullable().optional(),
  specialist: z.boolean().optional(), specialist_category: text.nullable().optional(),
});
const engine = z.object({
  hint: text, name: text, maker: text, requested: text, requested_name: text,
  fell_back: z.boolean(), latency_ms: z.number().finite().nonnegative().nullable(),
  cost_usd: z.number().finite().nonnegative(), cost_source: z.enum(["measured", "estimated"]),
  cached_share: z.number().finite().min(0).max(1).nullable(),
  funded_by: z.enum(["operator", "visitor"]).optional(),
});
const engineData = z.object({ primary: priority, recommendations: z.array(pick).min(1).max(3), engine: engine.optional() });

// A Quick pick (lib/keyless.ts): three rungs, quality first.
const RUNGS = ["quality", "balanced", "cost"] as const;
const term = z.number().finite();
const quickBackup = z.object({ model_id: text, model_name: text, platform_id: text, platform_name: text, effort: text });
const rung = z.object({
  priority: z.enum(RUNGS), model_id: text, model_name: text, platform_id: text, platform_name: text, effort: text,
  specialist: z.boolean(), backup: quickBackup.nullable(),
  terms: z.object({ quality: term, requirement_shortfall: term, cost: term }),
  why: z.object({ quality: text, requirement_shortfall: text, cost: text }),
});
const quickData = z.object({
  rungs: z.array(rung).length(3).refine((rungs) => rungs.every((r, i) => r.priority === RUNGS[i])),
  task: z.object({ category: text, complexity: text, novel: z.boolean(), budget_priority: text.optional() }),
  backup_warning: text.nullable(),
  engine: z.literal("scoring-core"),
  cost_usd: z.number().finite().nonnegative(),
});

const base = { id: z.string().min(1).max(128), at: z.number().finite().nonnegative().max(8.64e15), task: text };
const savedSchema = z.discriminatedUnion("kind", [
  z.object({ ...base, kind: z.literal("engine"), data: engineData }),
  z.object({ ...base, kind: z.literal("quick"), data: quickData }),
]);

// "engine": an AI recommender's three picks for a written task. "quick": Quick
// pick's three picks for a task type, computed from benchmarks and prices.
export type SavedRun =
  | { kind: "engine"; id: string; at: number; task: string; data: MultiRecommendResponse }
  | { kind: "quick"; id: string; at: number; task: string; data: KeylessResponse };

// The entry with only the fields above, or null when it is malformed or too
// large. Unknown fields are dropped, so nothing else a response carried is kept.
export function toSaved(value: unknown): SavedRun | null {
  const parsed = savedSchema.safeParse(value);
  if (!parsed.success) return null;
  const bytes = new TextEncoder().encode(JSON.stringify(parsed.data)).length;
  return bytes <= MAX_ENTRY_BYTES ? (parsed.data as SavedRun) : null;
}

// The models an entry picked, cheapest first, for a one-line summary.
export function pickedModels(run: SavedRun): string[] {
  if (run.kind === "quick") return [...run.data.rungs].reverse().map((r) => r.model_name);
  const byPriority = new Map(run.data.recommendations.map((r) => [r.priority, r.model]));
  return (["cheap", "balanced", "best"] as const).flatMap((p) => byPriority.get(p) ?? []);
}

export function exportFile(runs: SavedRun[], now: Date): string {
  return JSON.stringify({ format: EXPORT_FORMAT, version: 1, exported_at: now.toISOString(), runs }, null, 2);
}

// An export file's valid entries, or null when the file is not an export.
// Malformed entries are skipped and counted.
export function parseImport(raw: string): { runs: SavedRun[]; skipped: number } | null {
  if (raw.length > MAX_IMPORT_BYTES) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  const file = z.object({ format: z.literal(EXPORT_FORMAT), version: z.literal(1), runs: z.array(z.unknown()).max(MAX_SAVED) }).safeParse(value);
  if (!file.success) return null;
  const runs = file.data.runs.flatMap((run) => toSaved(run) ?? []);
  return { runs, skipped: file.data.runs.length - runs.length };
}

// The localStorage list this owner may take over: a list from before accounts
// were recorded (a bare array, which every visitor of the browser saw), or a
// list recorded for this owner. Another owner's list is left for them (null).
export function legacyRuns(raw: string | null, owner: string): SavedRun[] | null {
  if (!raw || raw.length > MAX_IMPORT_BYTES) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return []; }
  const envelope = z.object({ version: z.literal(1), owner: z.string(), runs: z.array(z.unknown()) }).safeParse(value);
  const runs = Array.isArray(value) ? value : envelope.success && envelope.data.owner === owner ? envelope.data.runs : null;
  if (runs === null) return envelope.success ? null : [];
  return runs.slice(0, MAX_SAVED).flatMap((run) => toSaved(run && typeof run === "object" ? { kind: "engine", ...run } : run) ?? []);
}
