// web/tests/spend-guard.spec.ts
//
// Daily spend circuit breaker trip logic (web/lib/spend-guard.ts), exercised
// via the injectable spend reader — no live audit_log needed.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import {
  _setLedgerPageForTest,
  _setSpendCounterForTest,
  _setSpendReaderForTest,
  dailyCostCapTripped,
  operatorCost,
  recordSpend,
  secondsToUtcMidnight,
  startOfUtcDayIso,
  sumLedgerSince,
  type LedgerRow,
} from "../lib/spend-guard";

test.afterEach(() => {
  _setSpendReaderForTest(null);
  _setLedgerPageForTest(null);
  _setSpendCounterForTest(null);
});

test("the ledger sum reads every page, not just the API's first 1,000 rows", async () => {
  // 2,500 calls at a cent each: a single capped read saw $10 and a $20 cap
  // could never trip.
  const rows: LedgerRow[] = Array.from({ length: 2_500 }, () => ({ cost_usd: 0.01, funded_by: "operator" }));
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

test("the seed counts operator rows and unstamped history; visitor and keyless rows count nothing", async () => {
  const rows: LedgerRow[] = [
    { cost_usd: 0.5, funded_by: "operator" },
    { cost_usd: "0.25", funded_by: null }, // history from before funded_by
    { cost_usd: 0.1 }, // a reader that omits the column
    { cost_usd: 7, funded_by: "visitor" },
    { cost_usd: 9, funded_by: "keyless" },
  ];
  _setLedgerPageForTest(async (_since, from, to) => rows.slice(from, to + 1));
  expect(await sumLedgerSince("2026-10-02T00:00:00.000Z")).toBeCloseTo(0.85, 9);
  expect(operatorCost({ cost_usd: 3, funded_by: "visitor" })).toBe(0);
  expect(operatorCost({ cost_usd: 3, funded_by: "keyless" })).toBe(0);
  expect(operatorCost({ cost_usd: 3, funded_by: "operator" })).toBe(3);
});

test("the counter moves for operator-funded calls only", () => {
  const added: number[] = [];
  _setSpendCounterForTest((usd) => added.push(usd));
  recordSpend(0.004, "operator");
  recordSpend(0.5, "visitor");
  recordSpend(0.5, "keyless");
  recordSpend(0, "operator");
  expect(added).toEqual([0.004]);
});
