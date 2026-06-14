// web/tests/ratelimit.spec.ts
//
// Issue #157: the roadmap monthly cap must (a) only consume a token on a
// SUCCESSFUL roadmap (read-only pre-flight check), and (b) honor a
// configurable limit + an exempt user_id list. These tests exercise the
// check/consume split via the test seam and the exempt-id parser directly.

// Side-effect import seeds the placeholder env vars BEFORE web/lib/env.ts
// is evaluated (transitively pulled in by ratelimit.ts). Must be first.
import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import {
  checkRoadmapMonthlyLimit,
  consumeRoadmapMonthlyToken,
  isRateLimitExempt,
  parseExemptIds,
  setTestRoadmapLimiter,
} from "../lib/ratelimit";

interface LimiterCalls {
  getRemaining: string[];
  limit: string[];
}

function fakeLimiter(remaining: number, calls: LimiterCalls) {
  return {
    async getRemaining(id: string) {
      calls.getRemaining.push(id);
      return { remaining, reset: Date.now() + 60_000 };
    },
    async limit(id: string) {
      calls.limit.push(id);
      return { success: true, limit: 10, remaining: remaining - 1, reset: Date.now() + 60_000 } as never;
    },
  } as unknown as Parameters<typeof setTestRoadmapLimiter>[0];
}

test("parseExemptIds trims, drops blanks, and dedups", () => {
  expect([...parseExemptIds("")]).toEqual([]);
  expect([...parseExemptIds("a, b ,, c,")]).toEqual(["a", "b", "c"]);
  expect([...parseExemptIds("u1,u1")]).toEqual(["u1"]);
});

test("isRateLimitExempt: only configured user_ids are exempt (default-closed)", () => {
  // RECOMMEND_RATELIMIT_EXEMPT_USER_IDS is seeded to "rl-exempt-test-uid" by
  // fixtures/seed-test-env. A configured id is exempt; everyone else is not.
  expect(isRateLimitExempt("rl-exempt-test-uid")).toBe(true);
  expect(isRateLimitExempt("some-other-user")).toBe(false);
});

test("checkRoadmapMonthlyLimit is READ-ONLY — uses getRemaining, never limit (#157)", async () => {
  const calls: LimiterCalls = { getRemaining: [], limit: [] };
  setTestRoadmapLimiter(fakeLimiter(5, calls));
  try {
    const res = await checkRoadmapMonthlyLimit("user-abc");
    expect(res.allowed).toBe(true);
    // The check must NOT consume a token — that only happens on success.
    expect(calls.getRemaining).toEqual(["user:user-abc"]);
    expect(calls.limit).toEqual([]);
  } finally {
    setTestRoadmapLimiter(null);
  }
});

test("checkRoadmapMonthlyLimit blocks when no allowance remains", async () => {
  const calls: LimiterCalls = { getRemaining: [], limit: [] };
  setTestRoadmapLimiter(fakeLimiter(0, calls));
  try {
    const res = await checkRoadmapMonthlyLimit("user-xyz");
    expect(res.allowed).toBe(false);
    expect(res.reason).toBe("roadmap_monthly_cap");
    expect(calls.limit).toEqual([]);
  } finally {
    setTestRoadmapLimiter(null);
  }
});

test("consumeRoadmapMonthlyToken consumes exactly one token (#157)", async () => {
  const calls: LimiterCalls = { getRemaining: [], limit: [] };
  setTestRoadmapLimiter(fakeLimiter(5, calls));
  try {
    await consumeRoadmapMonthlyToken("user-abc");
    expect(calls.limit).toEqual(["user:user-abc"]);
    expect(calls.getRemaining).toEqual([]);
  } finally {
    setTestRoadmapLimiter(null);
  }
});
