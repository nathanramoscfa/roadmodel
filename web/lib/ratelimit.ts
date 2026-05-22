// web/lib/ratelimit.ts
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

import { isE2eAuthEnabled } from "./e2e-mode";
import { env } from "./env";

export type RateLimitReason = "rate_limited" | "burst_dropped";

export interface RateLimitResult {
  allowed: boolean;
  reason?: RateLimitReason;
  retryAfter?: number;
}

interface Limiters {
  daily: Ratelimit;
  burst: Ratelimit;
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
  };
}

const limiters = buildLimiters();

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
