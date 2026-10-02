// web/lib/spend-guard.ts
//
// Real-time daily spend circuit breaker — the in-app complement to the
// provider-side GCP budget kill-switch (infra/gcp-killswitch/). It tracks the
// metered per-call cost (the same figure written to audit_log.cost_usd) for the
// current UTC day and, once that reaches ROADMODEL_DAILY_COST_CAP_USD, trips so
// the paid routes (/api/recommend, /api/roadmap via withRateLimit) stop until
// UTC midnight.
//
// Why this AND the GCP function: provider billing data lags hours, so a budget
// notification is a delayed backstop. This reacts in seconds off our own meter.
//
// The day's total lives in an Upstash counter (`spend:<UTC day>`) that each
// paid call adds its cost to (recordSpend): one read per check, exact at any
// volume. It used to be summed from audit_log on every check, and that read
// was capped at the API's 1,000-row page, so past ~1,000 requests a day the cap
// could never trip. When a day's counter is missing (the first check of the
// day, or a flushed store) it is seeded from the ledger, summed page by page;
// when Upstash is unreachable the ledger sum stands in.
//
// Fail-OPEN by design: when no cap is set, or every read errors, this never
// trips — a metering hiccup must not take the app down. It only ever BLOCKS
// when a cap is configured AND the day's spend has actually crossed it.

import { after } from "next/server";
import { Redis } from "@upstash/redis";
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

let redisClient: Redis | null | undefined;
function getRedis(): Redis | null {
  if (redisClient === undefined) {
    redisClient =
      env.UPSTASH_REDIS_URL && env.UPSTASH_REDIS_TOKEN
        ? new Redis({ url: env.UPSTASH_REDIS_URL, token: env.UPSTASH_REDIS_TOKEN })
        : null;
  }
  return redisClient;
}

// Two days, so the counter outlives its own UTC day by a margin.
const COUNTER_TTL_SECONDS = 2 * 24 * 60 * 60;
const PAGE = 1000;

function counterKey(dayStartIso: string): string {
  return `spend:${dayStartIso.slice(0, 10)}`;
}

// Test seam: inject a fake "spend since <iso>" reader so the trip logic is
// exercised without live stores (mirrors audit.ts _setAuditSinkForTest).
type SpendReader = (sinceIso: string) => Promise<number>;
let testReader: SpendReader | null = null;
export function _setSpendReaderForTest(reader: SpendReader | null): void {
  testReader = reader;
}

// Test seam for the ledger page reader, so the pagination is testable.
type LedgerPage = (sinceIso: string, from: number, to: number) => Promise<number[]>;
let testLedgerPage: LedgerPage | null = null;
export function _setLedgerPageForTest(page: LedgerPage | null): void {
  testLedgerPage = page;
}

async function ledgerPage(sinceIso: string, from: number, to: number): Promise<number[]> {
  if (testLedgerPage) return testLedgerPage(sinceIso, from, to);
  const { data, error } = await getSupabase()
    .from("audit_log")
    .select("cost_usd")
    .gte("ts", sinceIso)
    .not("cost_usd", "is", null)
    .order("ts")
    .range(from, to);
  if (error) throw error;
  return (data ?? []).map((row) => Number((row as { cost_usd: unknown }).cost_usd) || 0);
}

// The day's spend from the ledger, every page of it.
export async function sumLedgerSince(sinceIso: string): Promise<number> {
  let total = 0;
  for (let from = 0; ; from += PAGE) {
    const costs = await ledgerPage(sinceIso, from, from + PAGE - 1);
    total += costs.reduce((sum, c) => sum + c, 0);
    if (costs.length < PAGE) return total;
  }
}

// A short in-process memo so a configured cap doesn't add a read to EVERY
// paid request (Fluid Compute reuses instances). Bypassed by the test reader.
const MEMO_TTL_MS = 5_000;
let memo: { sinceIso: string; value: number; at: number } | null = null;

async function spentSince(sinceIso: string): Promise<number> {
  if (testReader) return testReader(sinceIso);
  const now = Date.now();
  if (memo && memo.sinceIso === sinceIso && now - memo.at < MEMO_TTL_MS) {
    return memo.value;
  }
  let value: number;
  const redis = getRedis();
  try {
    if (!redis) throw new Error("upstash not configured");
    const key = counterKey(sinceIso);
    const raw = await redis.get<string | number>(key);
    if (raw === null || raw === undefined) {
      // No counter yet today: start it from what the ledger already holds.
      value = await sumLedgerSince(sinceIso);
      await redis.set(key, value, { nx: true, ex: COUNTER_TTL_SECONDS });
    } else {
      value = Number(raw) || 0;
    }
  } catch (err) {
    console.warn("[spend-guard] counter read failed — summing the ledger", err);
    value = await sumLedgerSince(sinceIso);
  }
  memo = { sinceIso, value, at: now };
  return value;
}

// Add one paid call's cost to the day's counter. Runs after the response is
// sent (it never delays the caller) and never throws.
export function recordSpend(costUsd: number, now: Date = new Date()): void {
  if (!(costUsd > 0) || testReader) return;
  const redis = getRedis();
  if (!redis) return;
  const key = counterKey(startOfUtcDayIso(now));
  const write = (async () => {
    try {
      await redis.incrbyfloat(key, costUsd);
      await redis.expire(key, COUNTER_TTL_SECONDS);
      if (memo && memo.sinceIso === startOfUtcDayIso(now)) memo.value += costUsd;
    } catch (err) {
      console.warn("[spend-guard] counter write failed (non-fatal)", err);
    }
  })();
  try {
    after(write);
  } catch {
    // Outside a request context: the write still runs, best-effort.
  }
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

// Trips ONLY when capUsd > 0 and today's spend >= capUsd. Defaults the cap from
// env so callers just `await dailyCostCapTripped()`; the param keeps it
// unit-testable without env juggling.
export async function dailyCostCapTripped(
  capUsd: number = env.ROADMODEL_DAILY_COST_CAP_USD,
): Promise<SpendGuardResult> {
  if (!capUsd || capUsd <= 0) {
    return { tripped: false };
  }
  try {
    const spent = await spentSince(startOfUtcDayIso());
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
    console.warn("[spend-guard] spend read failed — failing open", err);
    return { tripped: false };
  }
}
