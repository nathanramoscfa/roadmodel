// web/tests/recommend-engines.spec.ts
//
// The /recommend engine registry as the web reads it (lib/recommend-engines):
// who may choose which engine, that only evaluated engines are offered, that
// every engine prices against a real catalog model, and that the ledger bills
// cache reads and writes correctly. Node-side unit tests (no `page`), the
// repo's idiom; seed-test-env first so lib/env.ts parses.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import catalog from "../data/catalog.json";
import registry from "../data/engines.json";
import {
  DEFAULT_ENGINE,
  MENU,
  canUse,
  chooseEngine,
  costFromUsage,
  engineByHint,
  estimatedCost,
  isEvaluated,
  menuFor,
  promptTokens,
  viewerFor,
  type Engine,
} from "../lib/recommend-engines";

const FOUNDER_UID = "rl-exempt-test-uid"; // seeded in RECOMMEND_RATELIMIT_EXEMPT_USER_IDS
const INVITED_UID = "invited-test-uid"; // seeded in RECOMMEND_INVITED_USER_IDS

test("viewers: signed out, signed in on neither list, invited, and the founder", () => {
  expect(viewerFor(undefined)).toBe("anonymous");
  expect(viewerFor("some-user")).toBe("visitor");
  expect(viewerFor(INVITED_UID)).toBe("invited");
  expect(viewerFor(FOUNDER_UID)).toBe("founder");
});

test("the default engine is open to invited members and always runnable", () => {
  expect(DEFAULT_ENGINE.hint).toBe(registry.default);
  expect(DEFAULT_ENGINE.access).toBe("invited");
  expect(isEvaluated(DEFAULT_ENGINE)).toBe(true);
  expect(chooseEngine(undefined, "invited")).toEqual({ ok: true, engine: DEFAULT_ENGINE });
  expect(chooseEngine("", "invited")).toEqual({ ok: true, engine: DEFAULT_ENGINE });
});

test("the retired tiers are gone: every menu engine is invited or founder", () => {
  expect(new Set(registry.engines.map((e) => e.menu))).toEqual(new Set(["invited", "founder", null]));
});

test("every registry engine bills as a catalog model", () => {
  const ids = new Set(catalog.models.map((m) => m.id));
  for (const e of registry.engines) expect(ids.has(e.catalog_id), e.hint).toBe(true);
});

test("the menu lists offered engines only, cheapest first", () => {
  expect(MENU.length).toBeGreaterThan(1);
  expect(MENU.every((e) => e.access !== null)).toBe(true);
  for (let i = 1; i < MENU.length; i++) {
    expect(MENU[i].coldUsd).toBeGreaterThanOrEqual(MENU[i - 1].coldUsd);
  }
});

test("access: a viewer may use engines at or below their tier, once evaluated", () => {
  for (const e of MENU) {
    const evaluated = isEvaluated(e);
    expect(canUse("founder", e)).toBe(evaluated);
    expect(canUse("invited", e)).toBe(evaluated && e.access === "invited");
    // Only the viewers the operator lane funds may choose an operator engine.
    expect(canUse("visitor", e)).toBe(false);
    expect(canUse("anonymous", e)).toBe(false);
  }
});

test("chooseEngine refuses what a viewer may not use, and names unknown engines", () => {
  expect(chooseEngine("no-such-engine", "founder")).toEqual({ ok: false, error: "unknown_engine" });
  expect(chooseEngine(42, "founder")).toEqual({ ok: false, error: "unknown_engine" });
  // A runnable engine the menu does not offer is unknown to the menu.
  const offMenu = registry.engines.find((e) => e.menu === null);
  if (offMenu) expect(chooseEngine(offMenu.hint, "founder")).toEqual({ ok: false, error: "unknown_engine" });

  const founderOnly = MENU.find((e) => e.access === "founder" && isEvaluated(e));
  if (founderOnly) {
    expect(chooseEngine(founderOnly.hint, "anonymous")).toMatchObject({ ok: false, error: "engine_not_allowed" });
    expect(chooseEngine(founderOnly.hint, "invited")).toMatchObject({ ok: false, error: "engine_not_allowed" });
    expect(chooseEngine(founderOnly.hint, "founder")).toMatchObject({ ok: true });
  }
  const unevaluated = MENU.find((e) => !isEvaluated(e));
  if (unevaluated) {
    expect(chooseEngine(unevaluated.hint, "founder")).toMatchObject({ ok: false, error: "engine_not_evaluated" });
  }
});

test("menuFor marks what each viewer may choose, without internals", () => {
  const anon = menuFor("anonymous");
  expect(anon.map((o) => o.hint)).toEqual(MENU.map((e) => e.hint));
  for (const o of anon) {
    expect(o.allowed).toBe(false);
    expect(Object.keys(o).sort()).toEqual(
      ["access", "allowed", "coldUsd", "eval", "evaluated", "hint", "isDefault", "maker", "name", "payer", "warmUsd"].sort(),
    );
    expect(o.payer).toBe("operator");
  }
});

test("menuFor: an invited member may choose the evaluated invited engines", () => {
  for (const o of menuFor("invited")) {
    expect(o.allowed).toBe(o.evaluated && o.access === "invited");
  }
  expect(menuFor("visitor").some((o) => o.allowed)).toBe(false);
});

test("costFromUsage bills uncached input, cache reads, cache writes and output", () => {
  const engine: Engine = {
    ...DEFAULT_ENGINE,
    inputPer1m: 2,
    outputPer1m: 10,
    cacheReadPer1m: 0.2,
  };
  // 61k prompt: 1k uncached, 59k read from cache, 1k written (Anthropic), 800 out.
  const usd = costFromUsage(engine, {
    input_tokens: 61_000,
    cached_input_tokens: 59_000,
    cache_write_tokens: 1_000,
    output_tokens: 800,
  });
  const expected = (1_000 * 2 + 59_000 * 0.2 + 1_000 * 2 * 1.25 + 800 * 10) / 1_000_000;
  expect(usd).toBeCloseTo(expected, 9);
});

test("the cold estimate bills the whole measured prompt per call", () => {
  const e = engineByHint(registry.default) as Engine;
  const one = estimatedCost(e, 400);
  expect(one.input_tokens).toBe(promptTokens(e) + 100);
  expect(one.cached_input_tokens).toBe(0);
  const fanout = estimatedCost(e, 400, { inputCalls: 3, outputCalls: 3 });
  expect(fanout.input_tokens).toBe(3 * (promptTokens(e) + 100));
  expect(fanout.costUsd).toBeGreaterThan(one.costUsd * 2.9);
});

test("each provider's tokenizer counts the same prompt differently", () => {
  // Measured 2026-10-02: 60,914 (OpenAI), 66,221 (Google), 94,049 (Anthropic).
  expect(promptTokens({ provider: "openai" })).toBeLessThan(promptTokens({ provider: "google" }));
  expect(promptTokens({ provider: "google" })).toBeLessThan(promptTokens({ provider: "anthropic" }));
  expect(promptTokens({ provider: "unknown" })).toBe(promptTokens({ provider: "openai" }));
});
