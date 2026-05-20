// web/lib/ratelimit.ts
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";
import { env } from "./env";

const redis = new Redis({
  url: env.UPSTASH_REDIS_URL,
  token: env.UPSTASH_REDIS_TOKEN,
});

export const dailyLimiter = new Ratelimit({
  redis,
  limiter: Ratelimit.slidingWindow(3, "1 d"),
  prefix: "rl:day",
});

export const burstLimiter = new Ratelimit({
  redis,
  limiter: Ratelimit.slidingWindow(10, "1 m"),
  prefix: "rl:burst",
});

export type RateLimitReason = "rate_limited" | "burst_dropped";

export interface RateLimitResult {
  allowed: boolean;
  reason?: RateLimitReason;
  retryAfter?: number;
}

export async function checkLimits(key: string): Promise<RateLimitResult> {
  const burst = await burstLimiter.limit(key);
  if (!burst.success) {
    return {
      allowed: false,
      reason: "burst_dropped",
      retryAfter: 60,
    };
  }

  const daily = await dailyLimiter.limit(key);
  if (!daily.success) {
    return {
      allowed: false,
      reason: "rate_limited",
      retryAfter: Math.ceil((daily.reset - Date.now()) / 1000),
    };
  }

  return { allowed: true };
}
