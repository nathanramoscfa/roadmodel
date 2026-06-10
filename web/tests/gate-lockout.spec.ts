// web/tests/gate-lockout.spec.ts
//
// The pre-launch SITE_PASSWORD gate locks a client out after MAX_ATTEMPTS
// failed submissions and fires ONE intrusion alert per lockout window. These
// tests exercise the lock + alert-dedup logic via the gateGuard test seam,
// with a fake Upstash backend (no live network).

// Seed placeholder env BEFORE lib/env.ts is evaluated (pulled in by gateGuard).
import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import {
  MAX_ATTEMPTS,
  fireGateAlert,
  gateLockState,
  recordGateFailure,
  setTestGateBackend,
  type GateBackend,
} from "../lib/gateGuard";

// A fake backend that models a sliding-window counter (allow MAX_ATTEMPTS, then
// block) plus the alert list + dedup SET NX, all in memory.
function fakeBackend() {
  const state = { failures: 0, alertNxKeys: new Set<string>(), list: [] as string[] };
  const reset = () => Date.now() + 300_000;
  const backend = {
    limiter: {
      async getRemaining() {
        return { remaining: Math.max(0, MAX_ATTEMPTS - state.failures), reset: reset() };
      },
      async limit() {
        state.failures += 1;
        const remaining = MAX_ATTEMPTS - state.failures;
        return {
          success: remaining >= 0,
          limit: MAX_ATTEMPTS,
          remaining: Math.max(0, remaining),
          reset: reset(),
        };
      },
    },
    redis: {
      async set(key: string, _value: unknown, _opts?: unknown) {
        if (state.alertNxKeys.has(key)) return null; // NX: already set
        state.alertNxKeys.add(key);
        return "OK";
      },
      async lpush(_key: string, ...values: unknown[]) {
        state.list.unshift(...values.map((v) => String(v)));
        return state.list.length;
      },
      async ltrim() {
        return "OK";
      },
      async expire() {
        return 1;
      },
    },
  } as unknown as GateBackend;
  return { backend, state };
}

test("gate locks after MAX_ATTEMPTS failures, not before", async () => {
  const { backend } = fakeBackend();
  setTestGateBackend(backend);
  try {
    // The first MAX_ATTEMPTS failures are allowed (wrong-password, not locked).
    for (let i = 1; i < MAX_ATTEMPTS; i++) {
      const r = await recordGateFailure("1.2.3.4");
      expect(r.locked).toBe(false);
      expect(r.remaining).toBe(MAX_ATTEMPTS - i);
    }
    // The MAX_ATTEMPTS-th failure exhausts the allowance → locked.
    const last = await recordGateFailure("1.2.3.4");
    expect(last.locked).toBe(true);
    expect(last.remaining).toBe(0);
    expect(last.retryAfter).toBeGreaterThan(0);

    // A subsequent read-only check still reports locked.
    const state = await gateLockState("1.2.3.4");
    expect(state.locked).toBe(true);
  } finally {
    setTestGateBackend(null);
  }
});

test("fireGateAlert pushes exactly one event per lockout window (dedup)", async () => {
  const { backend, state } = fakeBackend();
  setTestGateBackend(backend);
  try {
    await fireGateAlert("9.9.9.9", "curl/8.0");
    await fireGateAlert("9.9.9.9", "curl/8.0"); // same window → deduped
    await fireGateAlert("9.9.9.9", "curl/8.0");
    expect(state.list).toHaveLength(1);
    const event = JSON.parse(state.list[0]);
    expect(event.ip).toBe("9.9.9.9");
    expect(event.ua).toBe("curl/8.0");
    expect(event.attempts).toBe(MAX_ATTEMPTS);
  } finally {
    setTestGateBackend(null);
  }
});

test("gate fails OPEN when no backend is configured (never bricks access)", async () => {
  setTestGateBackend(null); // no backend → default unconfigured path in CI
  const state = await gateLockState("1.2.3.4");
  expect(state.locked).toBe(false);
  expect(state.remaining).toBe(MAX_ATTEMPTS);
  // Alert is a no-op without a backend (must not throw).
  await fireGateAlert("1.2.3.4", "ua");
});
