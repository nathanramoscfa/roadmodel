// web/lib/audit.ts
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { env } from "./env";
import type { LatencyTimings } from "./latency";
import type { CacheStats } from "./llm-cache";

// Lazy-init the Supabase client so importing this module doesn't
// trigger @supabase/realtime-js' WebSocket constructor lookup at
// load time. Under CI Node 20 the lookup throws (no native
// WebSocket; `ws` not installed), which breaks any test that
// statically imports this module — e.g. web/tests/latency.spec.ts
// installing the test sink. Production callers hit writeAudit
// during a request anyway, so deferring init costs nothing.
let supabaseClient: SupabaseClient | null = null;
function getSupabase(): SupabaseClient {
  if (!supabaseClient) {
    supabaseClient = createClient(
      env.SUPABASE_URL,
      env.SUPABASE_SERVICE_ROLE_KEY,
      {
        auth: { persistSession: false },
      },
    );
  }
  return supabaseClient;
}

export type AuditOutcome =
  | "ok"
  | "rate_limited"
  | "burst_dropped"
  | "recommender_error"
  | "bad_input"
  // Phase 4 Step 4 outcomes for /api/roadmap.
  | "roadmap_monthly_cap"
  | "roadmap_error"
  | "unauthorized"
  // Real-time daily spend circuit breaker tripped (web/lib/spend-guard.ts):
  // the UTC day's metered cost_usd reached ROADMODEL_DAILY_COST_CAP_USD.
  | "daily_cost_cap"
  // Phase 4 Step 7 — env-gated rate-limit bypass for the
  // maintainer-run latency sweep. Removed in PR 7c alongside the
  // ROADMODEL_LATENCY_BYPASS_TOKEN env var.
  | "bypassed_rate_limit";

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
  // Phase 4 Step 7 — per-request span timings. Schema lives in
  // 20260606000002_audit_log_latency.sql. Optional so non-
  // instrumented routes (Phase 4 /api/roadmap, gate/auth audit
  // rows) keep writing rows with this column null.
  latency_ms?: LatencyTimings;
}

// Test seam: when set, writeAudit hands the entry to the sink
// instead of inserting into Supabase. Production never touches
// this — the latency.spec test installs a sink to capture rows
// without standing up a real database. Returns the previous sink
// so a test can chain installs / restores.
type AuditSink = (entry: AuditEntry) => void;
let testSink: AuditSink | null = null;

export function _setAuditSinkForTest(sink: AuditSink | null): AuditSink | null {
  const prior = testSink;
  testSink = sink;
  return prior;
}

export async function writeAudit(entry: AuditEntry): Promise<void> {
  if (testSink) {
    testSink(entry);
    return;
  }
  const { error } = await getSupabase().from("audit_log").insert({
    ts: new Date().toISOString(),
    ...entry,
  });
  if (error) {
    console.error("audit write failed", error);
  }
}
