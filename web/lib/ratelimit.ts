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
  // The operator lane's per-user limits (lib/withFundingLane.ts): an invited
  // member gets INVITED_DAILY_LIMIT calls a day and at most 10 a minute, both
  // keyed on `user:<uid>`. The founder and the bypass header are unlimited.
  invitedDaily: Ratelimit;
  burst: Ratelimit;
  // Per-user monthly cap for /api/roadmap (rolling 30 days), keyed on the
  // Supabase user_id. Runs inside the route, after the funding lane.
  roadmapMonthly: Ratelimit;
}

// Recommendations an invited member may run on the operator's keys per day.
export const INVITED_DAILY_LIMIT = 20;

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
    invitedDaily: new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(INVITED_DAILY_LIMIT, "1 d"),
      prefix: "rl:invited",
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

// Subset of the @upstash/ratelimit API the operator-lane limits use.
type LaneLimiter = Pick<Ratelimit, "limit">;

// Test seam: inject fake burst + invited-daily limiters so the 20-a-day rule
// is exercised without a live Upstash backend (mirrors setTestRoadmapLimiter).
let testLaneLimiters: { burst: LaneLimiter; invitedDaily: LaneLimiter } | null = null;
export function setTestLaneLimiters(
  fake: { burst: LaneLimiter; invitedDaily: LaneLimiter } | null,
): void {
  testLaneLimiters = fake;
}

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

// The founder list: user_ids whose requests run on the operator lane with no
// rate limit (lib/funding-lane.ts), parsed once at module load. Empty →
// nobody is a founder (default-closed).
const RATE_LIMIT_EXEMPT = parseExemptIds(env.RECOMMEND_RATELIMIT_EXEMPT_USER_IDS);

export function isRateLimitExempt(userId: string): boolean {
  return RATE_LIMIT_EXEMPT.has(userId);
}

// The invited member's limits on the operator lane, keyed on their user id:
// the 10-a-minute burst, then INVITED_DAILY_LIMIT a day.
export async function checkInvitedLimits(userId: string): Promise<RateLimitResult> {
  const lane = testLaneLimiters ?? limiters;
  if (!lane) {
    // No Upstash configured. In PRODUCTION the limiter bounds the operator's
    // spend on invited members — refuse to serve uncapped rather than silently
    // fail open. Throwing here makes the route return 500 BEFORE any upstream
    // call (fail closed). Elsewhere (local/CI/preview, where Upstash is
    // intentionally unseeded) keep the fail-open behaviour so dev/test run.
    // Gated on VERCEL_ENV === "production" (not VERCEL=1, which is every
    // Vercel runtime). See also lib/ip-salt.ts for the same prod policy.
    if (process.env.VERCEL_ENV === "production") {
      throw new Error(
        "[ratelimit] UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN unset in " +
          "production — refusing to run the recommender without a rate " +
          'limiter. See infra/README.md "Environment variables".',
      );
    }
    return { allowed: true };
  }

  const key = `user:${userId}`;
  try {
    const burst = await lane.burst.limit(key);
    if (!burst.success) {
      return {
        allowed: false,
        reason: "burst_dropped",
        retryAfter: 60,
      };
    }

    const daily = await lane.invitedDaily.limit(key);
    if (!daily.success) {
      return {
        allowed: false,
        reason: "rate_limited",
        retryAfter: Math.max(1, Math.ceil((daily.reset - Date.now()) / 1000)),
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

// Per-user monthly cap for /api/roadmap. Invoked by the route handler
// AFTER the funding lane's limits pass. When Upstash is unseeded or
// unreachable, this layer fails open via the same E2E-vs-prod policy as
// checkInvitedLimits().
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
