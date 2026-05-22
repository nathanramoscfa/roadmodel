// web/lib/audit.ts
import { createClient } from "@supabase/supabase-js";
import { env } from "./env";

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
  | "bad_input";

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
