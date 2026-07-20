// web/tests/recommend-frontier.spec.ts
//
// Signed-in quality-tier engine routing. Playwright test() blocks run Node-side
// (no `page` fixture) — the repo's unit-test idiom. resolveRecommenderEngine
// returns the GPT-5 mini frontier engine (2026-07-19 eval-backed cutover from
// Gemini 2.5 Pro) ONLY for signed-in requests when the RECOMMENDER_FRONTIER_ENABLED
// gate is on; anonymous requests and the gated-off (increment-1 dark-ship) state
// always get the free catalog engine. seed-test-env first so web/lib/env.ts
// parses (model-routing imports the bundled catalog).

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import { resolveRecommenderEngine } from "../lib/model-routing";
import { env } from "../lib/env";

test("signed-in + frontier gate on → GPT-5 mini frontier engine", () => {
  const e = resolveRecommenderEngine({
    profile: null,
    signedIn: true,
    frontierEnabled: true,
  });
  expect(e.engine).toBe("gpt-5-mini");
  expect(e.provider).toBe("openai");
  expect(e.force_provider).toBe("openai-gpt-5-mini");
  expect(e.use_frontier).toBe(true);
});

test("signed-in but gate OFF → free engine (increment-1 dark-ship)", () => {
  const e = resolveRecommenderEngine({
    profile: null,
    signedIn: true,
    frontierEnabled: false,
  });
  expect(e.use_frontier).toBe(false);
  expect(e.engine).not.toBe("gemini-2.5-pro");
});

test("anonymous + gate ON → free engine (frontier is signed-in only)", () => {
  const e = resolveRecommenderEngine({
    profile: null,
    signedIn: false,
    frontierEnabled: true,
  });
  expect(e.use_frontier).toBe(false);
  expect(e.engine).not.toBe("gemini-2.5-pro");
});

test("default args (no signedIn/frontierEnabled) → free engine", () => {
  const e = resolveRecommenderEngine({ profile: null });
  expect(e.use_frontier).toBe(false);
});

test("env.RECOMMENDER_FRONTIER_ENABLED defaults to false when unset (#155-safe dark-ship)", () => {
  // seed-test-env does not set it → asserts the unset -> default("false") chain.
  expect(process.env.RECOMMENDER_FRONTIER_ENABLED).toBeUndefined();
  expect(env.RECOMMENDER_FRONTIER_ENABLED).toBe(false);
});
