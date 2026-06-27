// web/lib/spend-guard.ts
//
// Real-time daily spend circuit breaker — the in-app complement to the
// provider-side GCP budget kill-switch (infra/gcp-killswitch/). It sums the
// metered per-call cost (audit_log.cost_usd) for the current UTC day and, once
// that reaches ROADMODEL_DAILY_COST_CAP_USD, trips so the paid routes
// (/api/recommend, /api/roadmap via withRateLimit) stop until UTC midnight.
//
// Why this AND the GCP function: GCP billing data lags hours, so its budget
// notification is a delayed backstop. This reacts in seconds off our own
// ledger. Together: real-time app cap + independent provider-side kill.
//
// Fail-OPEN by design: when no cap is set, or the ledger read errors, this
// never trips — a metering hiccup must not take the app down. It only ever
// BLOCKS when a cap is configured AND the day's spend has actually crossed it.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { env } from "./env";

let supabaseClient: SupabaseClient | null = null;
function getSupabase(): SupabaseClient {
  if (!supabaseClient) {
    supabaseClient = createClient(
      env.SUPABASE_URL,
      env.SUPABASE_SERVICE_ROLE_KEY,
      { auth: { persistSession: false } },
    );
  }
  return supabaseClient;
}

// Test seam: inject a fake "sum cost_usd since <iso>" reader so the trip logic
// is exercised without a live audit_log (mirrors audit.ts _setAuditSinkForTest).
type SpendReader = (sinceIso: string) => Promise<number>;
let testReader: SpendReader | null = null;
export function _setSpendReaderForTest(reader: SpendReader | null): void {
  testReader = reader;
}

// Small in-process memo so a configured cap doesn't add a DB read to EVERY
// paid request — Vercel reuses function instances (Fluid Compute), so a short
// TTL meaningfully cuts ledger queries under load. Bypassed by the test reader.
const MEMO_TTL_MS = 30_000;
let memo: { sinceIso: string; value: number; at: number } | null = null;

async function sumCostSince(sinceIso: string): Promise<number> {
  if (testReader) {
    return testReader(sinceIso);
  }
  const now = Date.now();
  if (memo && memo.sinceIso === sinceIso && now - memo.at < MEMO_TTL_MS) {
    return memo.value;
  }
  const { data, error } = await getSupabase()
    .from("audit_log")
    .select("cost_usd")
    .gte("ts", sinceIso)
    .not("cost_usd", "is", null);
  if (error) {
    throw error;
  }
  const total = (data ?? []).reduce(
    (sum, row) => sum + (Number((row as { cost_usd: unknown }).cost_usd) || 0),
    0,
  );
  memo = { sinceIso, value: total, at: now };
  return total;
}

export function startOfUtcDayIso(now: Date = new Date()): string {
  const d = new Date(now);
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString();
}

export function secondsToUtcMidnight(now: Date = new Date()): number {
  const next = new Date(now);
  next.setUTCHours(24, 0, 0, 0);
  return Math.max(1, Math.ceil((next.getTime() - now.getTime()) / 1000));
}

export interface SpendGuardResult {
  tripped: boolean;
  spentUsd?: number;
  capUsd?: number;
  retryAfter?: number;
}

// Trips ONLY when capUsd > 0 and today's summed cost_usd >= capUsd. Defaults
// the cap from env so callers just `await dailyCostCapTripped()`; the param
// keeps it unit-testable without env juggling.
export async function dailyCostCapTripped(
  capUsd: number = env.ROADMODEL_DAILY_COST_CAP_USD,
): Promise<SpendGuardResult> {
  if (!capUsd || capUsd <= 0) {
    return { tripped: false };
  }
  try {
    const spent = await sumCostSince(startOfUtcDayIso());
    if (spent >= capUsd) {
      return {
        tripped: true,
        spentUsd: spent,
        capUsd,
        retryAfter: secondsToUtcMidnight(),
      };
    }
    return { tripped: false, spentUsd: spent, capUsd };
  } catch (err) {
    console.warn("[spend-guard] ledger read failed — failing open", err);
    return { tripped: false };
  }
}
