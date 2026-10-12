import { z } from "zod";
import type { MultiRecommendResponse } from "./api";

export const RECENT_KEY = "roadmodel:recommend-recent";
export const RECENT_CLEAR_SIGNAL = "roadmodel:recommend-clear-signal";
export const RECENT_CLEARED = "roadmodel:recommend-cleared";
const MAX_BYTES = 512 * 1024;
const priority = z.enum(["cheap", "balanced", "best"]);
const text = z.string().max(50_000);
const scalar = z.union([text, z.number().finite(), z.boolean(), z.null()]);
const fields = z.record(z.string().max(100), z.union([scalar, z.array(scalar).max(128)])).refine((v) => Object.keys(v).length <= 64);
const pick = z.object({
  priority, model: z.string().min(1).max(256), platform: z.string().max(256),
  settings: fields, session_cost_estimate: fields.default({}),
  comparison_table: z.array(fields).max(128),
  rationale_sections: z.record(text).nullable().optional(),
  backup: z.object({ model: text, platform: text.nullable(), settings: z.record(text) }).nullable().optional(),
  specialist: z.boolean().optional(), specialist_category: text.nullable().optional(),
});
const engine = z.object({
  hint: text, name: text, maker: text, requested: text, requested_name: text,
  fell_back: z.boolean(), latency_ms: z.number().finite().nonnegative().nullable(),
  cost_usd: z.number().finite().nonnegative(), cost_source: z.enum(["measured", "estimated"]),
  cached_share: z.number().finite().min(0).max(1).nullable(),
  funded_by: z.enum(["operator", "visitor"]).optional(),
});
const runSchema = z.object({
  id: z.string().min(1).max(128), at: z.number().finite().nonnegative().max(8.64e15),
  task: text, data: z.object({ primary: priority, recommendations: z.array(pick).min(1).max(3), engine: engine.optional() }),
});

export interface RecentRun { id: string; at: number; task: string; data: MultiRecommendResponse }

export function clearRecent(): void {
  try { window.localStorage.removeItem(RECENT_KEY); window.localStorage.setItem(RECENT_CLEAR_SIGNAL, crypto.randomUUID()); } catch { /* Storage may be disabled. */ }
  window.dispatchEvent(new Event(RECENT_CLEARED));
}

export function recentOwner(raw: string | null): string | null {
  try {
    if (!raw || raw.length > MAX_BYTES) return null;
    const value: unknown = JSON.parse(raw);
    const parsed = z.object({ version: z.literal(1), owner: z.string() }).safeParse(value);
    return parsed.success ? parsed.data.owner : null;
  } catch { return null; }
}

export function loadRecent(owner: string): RecentRun[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    if (raw.length > MAX_BYTES || new TextEncoder().encode(raw).length > MAX_BYTES) {
      window.localStorage.removeItem(RECENT_KEY); return [];
    }
    const envelope = z.object({ version: z.literal(1), owner: z.string(), runs: z.array(z.unknown()).max(8) }).safeParse(JSON.parse(raw));
    if (!envelope.success || envelope.data.owner !== owner) { window.localStorage.removeItem(RECENT_KEY); return []; }
    return envelope.data.runs.flatMap((run) => { const parsed = runSchema.safeParse(run); return parsed.success ? [parsed.data] : []; });
  } catch { return []; }
}

export function saveRecent(owner: string, runs: RecentRun[]): RecentRun[] {
  const kept: RecentRun[] = [];
  for (const run of runs.slice(0, 8)) {
    const parsed = runSchema.safeParse(run);
    if (!parsed.success) continue;
    const candidate = JSON.stringify({ version: 1, owner, runs: [...kept, parsed.data] });
    if (new TextEncoder().encode(candidate).length <= MAX_BYTES) kept.push(parsed.data);
  }
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify({ version: 1, owner, runs: kept }));
  } catch { /* A storage failure must not prevent displaying a recommendation. */ }
  return kept;
}
