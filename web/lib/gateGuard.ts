// web/lib/gateGuard.ts
//
// Brute-force protection + intrusion alerting for the pre-launch SITE_PASSWORD
// gate (see lib/gate.ts). After MAX_ATTEMPTS failed password submissions from
// one client within WINDOW, the gate locks that client out for the rest of the
// window and pushes a single alert event to an Upstash list that a local
// watcher (scripts/gate-alert-watcher.py) drains into a desktop notification +
// email. Reuses the same Upstash creds as the recommend rate limiter — no new
// server secret.
//
// Fail-OPEN by design: if Upstash is unset/unreachable the gate still works
// (no lockout, no alert) so an infra hiccup can never brick the maintainer's
// own access. The lockout is a tripwire, not the security boundary — the
// shared password is.
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";
import { createHash } from "node:crypto";

import { env } from "./env";

const SALT = process.env.ROADMODEL_IP_SALT ?? "default-salt-rotate-quarterly";

export const MAX_ATTEMPTS = 3;
const WINDOW = "5 m";
export const LOCK_SECONDS = 5 * 60;
const ALERTS_KEY = "gate:alerts";
const ALERTS_MAX = 100;
const ALERTS_TTL_SECONDS = 60 * 60 * 24 * 7; // 7 days

export interface GateLockState {
  locked: boolean;
  retryAfter: number; // seconds until the window resets
  remaining: number; // attempts left before lockout
}

const OPEN: GateLockState = {
  locked: false,
  retryAfter: 0,
  remaining: MAX_ATTEMPTS,
};

export interface GateBackend {
  limiter: Pick<Ratelimit, "limit" | "getRemaining">;
  redis: Pick<Redis, "set" | "lpush" | "ltrim" | "expire">;
}

function buildBackend(): GateBackend | null {
  if (!env.UPSTASH_REDIS_URL || !env.UPSTASH_REDIS_TOKEN) {
    return null;
  }
  const redis = new Redis({
    url: env.UPSTASH_REDIS_URL,
    token: env.UPSTASH_REDIS_TOKEN,
  });
  const limiter = new Ratelimit({
    redis,
    limiter: Ratelimit.slidingWindow(MAX_ATTEMPTS, WINDOW),
    prefix: "gate:fail",
  });
  return { limiter, redis };
}

const defaultBackend = buildBackend();

// Test seam: inject a fake backend so the lock + alert-dedup behavior can be
// exercised without a live Upstash (mirrors ratelimit.ts setTestRoadmapLimiter).
let testBackend: GateBackend | null = null;
export function setTestGateBackend(fake: GateBackend | null): void {
  testBackend = fake;
}
function backend(): GateBackend | null {
  return testBackend ?? defaultBackend;
}

export function hashIp(ip: string): string {
  return createHash("sha256").update(`${ip}|${SALT}`).digest("hex");
}

function retryAfterFrom(reset: number): number {
  return Math.max(1, Math.ceil((reset - Date.now()) / 1000));
}

// Read-only: is this client already locked out? Consumes no attempt token, so
// calling it on every gate POST is safe.
export async function gateLockState(ip: string): Promise<GateLockState> {
  const b = backend();
  if (!b) return OPEN;
  try {
    const { remaining, reset } = await b.limiter.getRemaining(hashIp(ip));
    return {
      locked: remaining <= 0,
      retryAfter: retryAfterFrom(reset),
      remaining: Math.max(0, remaining),
    };
  } catch (err) {
    console.warn("[gate] lock-state check failed — failing open", err);
    return OPEN;
  }
}

// Record one FAILED password attempt and return the resulting lock state. Call
// this only on a wrong password, never on a correct one.
export async function recordGateFailure(ip: string): Promise<GateLockState> {
  const b = backend();
  if (!b) return OPEN;
  try {
    const r = await b.limiter.limit(hashIp(ip));
    return {
      locked: !r.success || r.remaining <= 0,
      retryAfter: retryAfterFrom(r.reset),
      remaining: Math.max(0, r.remaining),
    };
  } catch (err) {
    console.warn("[gate] failure record failed — failing open", err);
    return OPEN;
  }
}

// Push a single intrusion-alert event per lockout window (deduped via SET NX),
// for the local watcher to drain. Includes the raw IP + UA: this is an
// ephemeral self-alert to the maintainer (7-day TTL, never written to the
// privacy-scoped audit_log), so it carries useful identifying detail the
// hashed audit trail intentionally omits.
export async function fireGateAlert(ip: string, ua: string): Promise<void> {
  const b = backend();
  if (!b) return;
  try {
    const firstThisWindow = await b.redis.set(`gate:alerted:${hashIp(ip)}`, "1", {
      nx: true,
      ex: LOCK_SECONDS,
    });
    if (!firstThisWindow) return; // already alerted this lockout window
    const event = JSON.stringify({
      ts: new Date().toISOString(),
      ip,
      ua,
      attempts: MAX_ATTEMPTS,
      lock_seconds: LOCK_SECONDS,
    });
    await b.redis.lpush(ALERTS_KEY, event);
    await b.redis.ltrim(ALERTS_KEY, 0, ALERTS_MAX - 1);
    await b.redis.expire(ALERTS_KEY, ALERTS_TTL_SECONDS);
  } catch (err) {
    console.warn("[gate] alert push failed — non-fatal", err);
  }
}
