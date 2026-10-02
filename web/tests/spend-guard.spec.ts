// web/tests/spend-guard.spec.ts
//
// Daily spend circuit breaker trip logic (web/lib/spend-guard.ts), exercised
// via the injectable spend reader — no live audit_log needed.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import {
  _setLedgerPageForTest,
  _setSpendReaderForTest,
  dailyCostCapTripped,
  secondsToUtcMidnight,
  startOfUtcDayIso,
  sumLedgerSince,
} from "../lib/spend-guard";

test.afterEach(() => {
  _setSpendReaderForTest(null);
  _setLedgerPageForTest(null);
});

test("the ledger sum reads every page, not just the API's first 1,000 rows", async () => {
  // 2,500 calls at a cent each: a single capped read saw $10 and a $20 cap
  // could never trip.
  const rows = Array.from({ length: 2_500 }, () => 0.01);
  const pages: [number, number][] = [];
  _setLedgerPageForTest(async (_since, from, to) => {
    pages.push([from, to]);
    return rows.slice(from, to + 1);
  });
  expect(await sumLedgerSince("2026-10-02T00:00:00.000Z")).toBeCloseTo(25, 6);
  expect(pages).toEqual([
    [0, 999],
    [1000, 1999],
    [2000, 2999],
  ]);
});

test("cap of 0 is disabled — never trips, never reads the ledger", async () => {
  let called = false;
  _setSpendReaderForTest(async () => {
    called = true;
    return 9999;
  });
  const r = await dailyCostCapTripped(0);
  expect(r.tripped).toBe(false);
  expect(called).toBe(false); // short-circuits before any read
});

test("under cap → not tripped", async () => {
  _setSpendReaderForTest(async () => 5);
  const r = await dailyCostCapTripped(10);
  expect(r.tripped).toBe(false);
  expect(r.spentUsd).toBe(5);
  expect(r.capUsd).toBe(10);
});

test("at/over cap → tripped with retryAfter", async () => {
  _setSpendReaderForTest(async () => 10);
  const r = await dailyCostCapTripped(10);
  expect(r.tripped).toBe(true);
  expect(r.retryAfter).toBeGreaterThan(0);

  _setSpendReaderForTest(async () => 12.5);
  expect((await dailyCostCapTripped(10)).tripped).toBe(true);
});

test("ledger read error → fails OPEN (does not trip)", async () => {
  _setSpendReaderForTest(async () => {
    throw new Error("supabase unreachable");
  });
  const r = await dailyCostCapTripped(10);
  expect(r.tripped).toBe(false);
});

test("startOfUtcDayIso is midnight UTC; secondsToUtcMidnight within a day", () => {
  const noon = new Date("2026-06-27T12:00:00.000Z");
  expect(startOfUtcDayIso(noon)).toBe("2026-06-27T00:00:00.000Z");
  const secs = secondsToUtcMidnight(noon);
  expect(secs).toBe(12 * 60 * 60); // 12h to next midnight
});
