// web/tests/env.spec.ts
//
// Phase 4 — ROADMAP_ENABLED off-switch (recommender-only app, issue
// #171). Playwright test() blocks run Node-side (no `page` fixture) —
// the repo's unit-test idiom. seed-test-env MUST be the first import so
// web/lib/env.ts parses with its required vars present.
//
// Guards the inverse of the #155 footgun: this flag is OPT-OUT (enabled
// unless "false"/"0"). A future "fix" to z.coerce.boolean() would make
// Boolean("false") === true and leave a disabled prod stuck ON, so the
// "false"/"0" -> false cases are asserted directly against the exported
// parser, and the unset -> true default against the real env singleton.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import { env, parseRoadmapEnabled } from "../lib/env";

test("parseRoadmapEnabled: opt-out semantics — only 'false'/'0' disable", () => {
  expect(parseRoadmapEnabled("false")).toBe(false);
  expect(parseRoadmapEnabled("0")).toBe(false);
  expect(parseRoadmapEnabled("true")).toBe(true);
  expect(parseRoadmapEnabled("1")).toBe(true);
  // Any other non-empty value is treated as enabled (opt-out).
  expect(parseRoadmapEnabled("yes")).toBe(true);
});

test("env.ROADMAP_ENABLED defaults to true when unset (#171)", () => {
  // seed-test-env does not set ROADMAP_ENABLED, so this asserts the
  // real unset -> default("true") -> true chain through the schema.
  // The default-ON keeps CI, the Playwright app server, and existing
  // roadmap/history/nav specs unaffected.
  expect(process.env.ROADMAP_ENABLED).toBeUndefined();
  expect(env.ROADMAP_ENABLED).toBe(true);
});
