// web/tests/classification-pin.spec.ts
//
// Same task, same row (web/lib/classification-pin.ts), exercised via the
// injectable store: no live Upstash needed.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import {
  _setPinStoreForTest,
  isTableKey,
  PIN_READ_TIMEOUT_MS,
  PIN_TTL_SECONDS,
  schedulePin,
  pinKey,
  readPin,
  writePin,
  type PinStore,
} from "../lib/classification-pin";

function memoryStore(): PinStore & { data: Map<string, string>; ttls: number[] } {
  const data = new Map<string, string>();
  const ttls: number[] = [];
  return {
    data,
    ttls,
    get: async (key) => data.get(key) ?? null,
    set: async (key, value, ttl) => {
      data.set(key, value);
      ttls.push(ttl);
    },
  };
}

test.afterEach(() => _setPinStoreForTest(null));

test("the key is the engine and the whitespace-normalized task, hashed", () => {
  const a = pinKey("openai-gpt-6-luna", "  Plan a   release\n");
  expect(a).toBe(pinKey("openai-gpt-6-luna", "Plan a release"));
  expect(a).not.toBe(pinKey("google-gemini-3.8-flash", "Plan a release"));
  expect(a).toMatch(/^rm:pin:v1:[0-9a-f]{64}$/);
  expect(a).not.toContain("release");
});

test("a fresh answer pins its row for seven days and a later request reads it", async () => {
  const s = memoryStore();
  _setPinStoreForTest(s);
  await writePin("e", "plan a release", "planning/medium", "vote");
  expect(await readPin("e", "plan a release")).toBe("planning/medium");
  expect(s.ttls).toEqual([PIN_TTL_SECONDS]);
  expect(PIN_TTL_SECONDS).toBe(7 * 24 * 60 * 60);
});

test("an answer from a pin does not renew it, and only table keys are pinned", async () => {
  const s = memoryStore();
  _setPinStoreForTest(s);
  await writePin("e", "t", "planning/medium", "pinned");
  await writePin("e", "t", "planning/extreme", "vote");
  await writePin("e", "t", undefined, "declared");
  // An older service reports no source: its unvoted row is not pinned.
  await writePin("e", "t", "planning/medium", undefined);
  expect(s.data.size).toBe(0);
  s.data.set(pinKey("e", "t"), "not a key");
  expect(await readPin("e", "t")).toBeNull();
});

test("the store failing never fails a request", async () => {
  _setPinStoreForTest({
    get: async () => {
      throw new Error("down");
    },
    set: async () => {
      throw new Error("down");
    },
  });
  expect(await readPin("e", "t")).toBeNull();
  await writePin("e", "t", "coding/low", "declared");
});

test("table keys", () => {
  expect(isTableKey("long-context/high/novel")).toBe(true);
  expect(isTableKey("coding/medium")).toBe(true);
  expect(isTableKey("Coding/Medium")).toBe(false);
  expect(isTableKey("coding/medium; x")).toBe(false);
});

test("a slow store times out instead of delaying the request", async () => {
  _setPinStoreForTest({
    get: () => new Promise((resolve) => setTimeout(() => resolve("coding/low"), 5_000)),
    set: async () => {},
  });
  const t0 = Date.now();
  expect(await readPin("e", "t")).toBeNull();
  expect(Date.now() - t0).toBeLessThan(PIN_READ_TIMEOUT_MS + 500);
});

test("a pin scheduled outside a request scope is still written", async () => {
  const s = memoryStore();
  _setPinStoreForTest(s);
  schedulePin("e", "t", "coding/low", "declared");
  await new Promise((resolve) => setTimeout(resolve, 10));
  expect(s.data.get(pinKey("e", "t"))).toBe("coding/low");
});
