// web/lib/audit.ts
import { createClient } from "@supabase/supabase-js";
import { env } from "./env";
import type { CacheStats } from "./llm-cache";

const supabase = createClient(
  env.SUPABASE_URL,
  env.SUPABASE_SERVICE_ROLE_KEY,
  {
    auth: { persistSession: false },
  },
);

export type AuditOutcome =
  | "ok"
  | "rate_limited"
  | "burst_dropped"
  | "recommender_error"
  | "bad_input"
  // Phase 4 Step 4 outcomes for /api/roadmap.
  | "roadmap_monthly_cap"
  | "roadmap_error"
  | "unauthorized";

export interface AuditEntry {
  ip_hash: string;
  ua_hash: string;
  route: string;
  provider?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  outcome: AuditOutcome;
  error_class?: string;
  // Populated for signed-in requests (Phase 4 Step 1+). Anonymous
  // routes (Phase 3 /api/recommend) keep this undefined; the column
  // is nullable in 20260602000000_audit_log_user_id.sql.
  user_id?: string;
  // Provider-discriminated context-caching stats. Phase 4 writes
  // the Google variant only; Phase 5 paid-frontier starts writing
  // the Anthropic variant against the same column. Schema lives
  // in 20260606000000_audit_log_cache_stats.sql.
  cache_stats?: CacheStats;
}

export async function writeAudit(entry: AuditEntry): Promise<void> {
  const { error } = await supabase.from("audit_log").insert({
    ts: new Date().toISOString(),
    ...entry,
  });
  if (error) {
    console.error("audit write failed", error);
  }
}
