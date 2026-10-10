// Normalized profile observations. Stale/missing data retains saved states;
// only a known passed subscription reset clears one. Prepaid credits never reset.
import { z } from "zod";

const CONFIG = {
  "claude:weekly": ["claude", "claude-code", 10080],
  "claude:5h": ["claude", "claude-code", 300],
  "codex:weekly": ["codex", "codex-cli", 10080],
  "codex:5h": ["codex", "codex-cli", 300],
  "antigravity:all": ["antigravity", "antigravity", null],
  "openrouter:credits": ["openrouter", "openrouter", 0],
} as const;
const ORDER = { headroom: 0, tight: 1, exhausted: 2 };
export const poolSchema = z.object({
  pool: z.enum(["claude:weekly", "claude:5h", "codex:weekly", "codex:5h", "antigravity:all", "openrouter:credits"]),
  state: z.enum(["headroom", "tight", "exhausted"]),
  source: z.string().optional(),
  platform_id: z.string().optional(),
  observed_at: z.number().finite().positive(),
  resets_at: z.number().finite().positive().nullable(),
  used_percent: z.number().finite().min(0).max(100),
  window_minutes: z.number().finite().min(0),
}).strict().refine((r) => {
  const [source, platform, minutes] = CONFIG[r.pool];
  if (r.source !== undefined && r.source !== source) return false;
  if (r.platform_id !== undefined && r.platform_id !== platform) return false;
  if (minutes !== null ? r.window_minutes !== minutes : ![300, 10080].includes(r.window_minutes)) return false;
  if (minutes === 0) return r.resets_at === null;
  if (r.resets_at === null) return source === "antigravity" && r.used_percent === 0 && r.state === "headroom";
  return r.observed_at < r.resets_at && r.resets_at <= r.observed_at + r.window_minutes * 60 + 60;
});
export type PoolObservation = z.infer<typeof poolSchema>;

export function normalizePools(raw: unknown, now = Date.now() / 1000): PoolObservation[] {
  if (!Array.isArray(raw) || raw.length > 6) return [];
  const rows = new Map<string, PoolObservation>();
  for (const value of raw) {
    const parsed = poolSchema.safeParse(value);
    if (!parsed.success || parsed.data.observed_at > now) continue;
    const row = parsed.data;
    const old = rows.get(row.pool);
    if (!old || ORDER[row.state] > ORDER[old.state]) rows.set(row.pool, row);
  }
  return [...rows.values()].sort((a, b) => a.pool.localeCompare(b.pool));
}

export function mergePools(previous: unknown, incoming: unknown, now = Date.now() / 1000): PoolObservation[] {
  const rows = new Map(normalizePools(previous, now).map((r) => [r.pool, r]));
  for (const row of normalizePools(incoming, now)) {
    const ttl = row.window_minutes > 0 && row.window_minutes <= 300 ? 3600 : 21600;
    const old = rows.get(row.pool);
    if (now - row.observed_at <= ttl && (row.resets_at === null || now < row.resets_at)
        && (!old || row.observed_at > old.observed_at)) rows.set(row.pool, row);
  }
  return [...rows.values()].sort((a, b) => a.pool.localeCompare(b.pool));
}

export function poolState(raw: unknown, platform: string, now = Date.now() / 1000): "headroom" | "tight" | "exhausted" {
  let state: "headroom" | "tight" | "exhausted" = "headroom";
  for (const row of normalizePools(raw, now)) {
    if (CONFIG[row.pool][1] !== platform) continue;
    const next = row.resets_at !== null && now >= row.resets_at ? "headroom" : row.state;
    if (ORDER[next] > ORDER[state]) state = next;
  }
  return state;
}
