// web/lib/classification-pin.ts
//
// Same task, same answer. The ladder's picks come from a table in code; the
// one judgement the engine makes is the task's classification (the table row),
// and at its reasoning floor it varies between identical calls (Phase 4.5 soak,
// 2026-10-08: 6 of 33 probes landed on a different row across three calls).
// The first answer to a task pins its row here for PIN_TTL_SECONDS, and every
// later request with the same text sends it to the service, which holds it
// (maintainer decision 2026-10-08). The row is a classification, not the picks:
// the picks are recomputed from the current table on every request, so a
// catalog change still reaches a pinned task.
//
// Stored: a SHA-256 of the engine hint and the whitespace-normalized task, and
// the row key (`coding/medium`). Never the task text. Every read and write
// fails open: without the store a request just classifies afresh.

import { createHash } from "node:crypto";
import { after } from "next/server";
import { Redis } from "@upstash/redis";

import { env } from "./env";

export const PIN_TTL_SECONDS = 7 * 24 * 60 * 60;
// A pin read waits at most this long before the request classifies afresh, so
// a slow store never adds latency to a recommendation.
export const PIN_READ_TIMEOUT_MS = 300;

// A ladder-table key (scoring.table_key): `<category>/<complexity>[/novel]`.
const TABLE_KEY = /^[a-z][a-z-]{1,31}\/(?:low|medium|high)(?:\/novel)?$/;

export interface PinStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds: number): Promise<void>;
}

let store: PinStore | null | undefined;

function getStore(): PinStore | null {
  if (store === undefined) {
    const redis =
      env.UPSTASH_REDIS_URL && env.UPSTASH_REDIS_TOKEN
        ? new Redis({
            url: env.UPSTASH_REDIS_URL,
            token: env.UPSTASH_REDIS_TOKEN,
            retry: { retries: 0 },
          })
        : null;
    store = redis
      ? {
          get: async (key) => {
            const v = await redis.get<string>(key);
            return typeof v === "string" ? v : null;
          },
          set: async (key, value, ttlSeconds) => {
            await redis.set(key, value, { ex: ttlSeconds });
          },
        }
      : null;
  }
  return store;
}

export function _setPinStoreForTest(s: PinStore | null): void {
  store = s;
}

export function isTableKey(value: unknown): value is string {
  return typeof value === "string" && TABLE_KEY.test(value);
}

export function pinKey(engineHint: string, task: string): string {
  const normalized = task.trim().replace(/\s+/g, " ");
  const digest = createHash("sha256").update(`${engineHint}\n${normalized}`).digest("hex");
  return `rm:pin:v1:${digest}`;
}

// The row an earlier answer to this task landed on, or null.
export async function readPin(engineHint: string, task: string): Promise<string | null> {
  const s = getStore();
  if (!s) return null;
  try {
    const value = await Promise.race([
      s.get(pinKey(engineHint, task)),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), PIN_READ_TIMEOUT_MS)),
    ]);
    return isTableKey(value) ? value : null;
  } catch (err) {
    console.warn("[classification-pin] read failed (classifying afresh)", err);
    return null;
  }
}

// Pin the row a fresh answer landed on: one the service voted on or the engine
// declared (roadmodel >= 0.2.76 reports which). A pinned answer does not renew
// its pin, so the TTL runs from the first answer; an older service reports no
// source, and its unvoted row is not pinned.
export async function writePin(
  engineHint: string,
  task: string,
  classification: unknown,
  source: unknown,
): Promise<void> {
  if (!isTableKey(classification) || (source !== "vote" && source !== "declared")) return;
  const s = getStore();
  if (!s) return;
  try {
    await s.set(pinKey(engineHint, task), classification, PIN_TTL_SECONDS);
  } catch (err) {
    console.warn("[classification-pin] write failed (non-fatal)", err);
  }
}

// Write the pin once the response is out (`after` keeps the function alive
// until it settles); outside a request scope, a best-effort write.
export function schedulePin(
  engineHint: string,
  task: string,
  classification: unknown,
  source: unknown,
): void {
  const write = () => writePin(engineHint, task, classification, source);
  try {
    after(write);
  } catch {
    void write();
  }
}
