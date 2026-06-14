// web/lib/ratelimit.ts
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

import { isE2eAuthEnabled } from "./e2e-mode";
import { env } from "./env";

export type RateLimitReason =
  | "rate_limited"
  | "burst_dropped"
  | "roadmap_monthly_cap";

export interface RateLimitResult {
  allowed: boolean;
  reason?: RateLimitReason;
  retryAfter?: number;
}

interface Limiters {
  daily: Ratelimit;
  burst: Ratelimit;
  // Per-user monthly cap for /api/roadmap — 3 roadmaps / 30 days,
  // keyed on the Supabase user_id rather than ip+ua. The IP-pool
  // burst+daily limiters above are still active and run BEFORE
  // this check inside withRateLimit; this layer is the per-user
  // capability-matrix gate ROADMAP.md documents for the free
  // signed-in tier.
  roadmapMonthly: Ratelimit;
}

function buildLimiters(): Limiters | null {
  if (!env.UPSTASH_REDIS_URL || !env.UPSTASH_REDIS_TOKEN) {
    console.warn(
      "[ratelimit] UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN unset — " +
        "rate limiter is INERT. /api/recommend will accept all traffic " +
        'until these are seeded. See infra/README.md "Environment ' +
        'variables".',
    );
    return null;
  }
  const redis = new Redis({
    url: env.UPSTASH_REDIS_URL,
    token: env.UPSTASH_REDIS_TOKEN,
  });
  return {
    daily: new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(3, "1 d"),
      prefix: "rl:day",
    }),
    burst: new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(10, "1 m"),
      prefix: "rl:burst",
    }),
    roadmapMonthly: new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(env.ROADMAP_MONTHLY_LIMIT, "30 d"),
      prefix: "rl:roadmap",
    }),
  };
}

const limiters = buildLimiters();

// Subset of the @upstash/ratelimit API the roadmap monthly cap uses.
// getRemaining is READ-ONLY (no token consumed); limit() consumes one.
type RoadmapLimiter = Pick<Ratelimit, "getRemaining" | "limit">;

// Test seam: inject a fake roadmap limiter so the read-only-check and
// consume-on-success behavior can be exercised deterministically
// without a live Upstash backend (mirrors setTestRedisClient).
let testRoadmapLimiter: RoadmapLimiter | null = null;
export function setTestRoadmapLimiter(fake: RoadmapLimiter | null): void {
  testRoadmapLimiter = fake;
}
function roadmapLimiter(): RoadmapLimiter | null {
  return testRoadmapLimiter ?? limiters?.roadmapMonthly ?? null;
}

// Parse the comma-separated exempt-user-id env var into a Set.
// Trimmed; blanks dropped. Pure + exported for unit testing.
export function parseExemptIds(raw: string): Set<string> {
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0),
  );
}

// User_ids exempt from the roadmap monthly cap (founder/dev dogfooding),
// parsed once from the env var at module load.
const ROADMAP_CAP_EXEMPT = parseExemptIds(env.ROADMAP_CAP_EXEMPT_USER_IDS);

export function isRoadmapCapExempt(userId: string): boolean {
  return ROADMAP_CAP_EXEMPT.has(userId);
}

// User_ids exempt from the /api/recommend IP-pool rate limit (founder/dev
// dogfooding via the browser), parsed once at module load. Empty → nobody
// exempt, so the global limit applies to everyone (default-closed).
const RATE_LIMIT_EXEMPT = parseExemptIds(env.RECOMMEND_RATELIMIT_EXEMPT_USER_IDS);

export function isRateLimitExempt(userId: string): boolean {
  return RATE_LIMIT_EXEMPT.has(userId);
}

export async function checkLimits(key: string): Promise<RateLimitResult> {
  if (!limiters) {
    return { allowed: true };
  }

  try {
    const burst = await limiters.burst.limit(key);
    if (!burst.success) {
      return {
        allowed: false,
        reason: "burst_dropped",
        retryAfter: 60,
      };
    }

    const daily = await limiters.daily.limit(key);
    if (!daily.success) {
      return {
        allowed: false,
        reason: "rate_limited",
        retryAfter: Math.ceil((daily.reset - Date.now()) / 1000),
      };
    }

    return { allowed: true };
  } catch (err) {
    // In E2E mode the CI env injects placeholder Upstash creds that
    // can't actually reach the network — fail open so tests don't
    // wedge on the rate limiter. In every other runtime (Vercel
    // Production / Preview / Development, local `vercel dev`), an
    // Upstash outage must NOT silently disable the limiter, so let
    // the exception propagate to the route handler.
    if (isE2eAuthEnabled()) {
      console.warn(
        "[ratelimit] Upstash unreachable in E2E mode — failing open",
        err,
      );
      return { allowed: true };
    }
    throw err;
  }
}

// Per-user 3-roadmaps-per-30-days cap for /api/roadmap. Invoked by
// the route handler AFTER the IP-pool burst+daily limits pass, so
// the user-visible 429 reason on this layer is always the per-user
// monthly cap rather than an unrelated IP-pool exhaustion. When
// Upstash is unseeded or unreachable, this layer fails open via
// the same E2E-vs-prod policy as checkLimits().
// READ-ONLY pre-flight check: does this user have monthly roadmap
// allowance left? Uses getRemaining (no token consumed) so a request
// that later fails mid-generation does NOT burn quota — the token is
// consumed separately by consumeRoadmapMonthlyToken() only after a
// roadmap successfully streams (issue #157: failed attempts used to
// drain the allowance, locking users out without ever getting output).
// Exempt user_ids (founder/dev) always pass.
export async function checkRoadmapMonthlyLimit(
  userId: string,
): Promise<RateLimitResult> {
  if (isRoadmapCapExempt(userId)) {
    return { allowed: true };
  }
  const limiter = roadmapLimiter();
  if (!limiter) {
    return { allowed: true };
  }
  try {
    const { remaining, reset } = await limiter.getRemaining(`user:${userId}`);
    if (remaining <= 0) {
      return {
        allowed: false,
        reason: "roadmap_monthly_cap",
        retryAfter: Math.ceil((reset - Date.now()) / 1000),
      };
    }
    return { allowed: true };
  } catch (err) {
    if (isE2eAuthEnabled()) {
      console.warn(
        "[ratelimit] Upstash unreachable in E2E mode (roadmap) — failing open",
        err,
      );
      return { allowed: true };
    }
    throw err;
  }
}

// Consume one monthly roadmap token. Called ONLY after a roadmap has
// successfully streamed, so errored/aborted attempts don't count
// (issue #157). Exempt users consume nothing. A metering failure here
// is non-fatal — the user already got their roadmap, so we log and
// move on rather than fail the completed request over a counter write.
export async function consumeRoadmapMonthlyToken(userId: string): Promise<void> {
  if (isRoadmapCapExempt(userId)) {
    return;
  }
  const limiter = roadmapLimiter();
  if (!limiter) {
    return;
  }
  try {
    await limiter.limit(`user:${userId}`);
  } catch (err) {
    console.warn(
      "[ratelimit] failed to consume roadmap monthly token (non-fatal)",
      err,
    );
  }
}
