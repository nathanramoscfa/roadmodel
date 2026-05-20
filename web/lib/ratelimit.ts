// web/lib/ratelimit.ts
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";
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
}
