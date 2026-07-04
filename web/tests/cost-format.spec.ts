// web/tests/cost-format.spec.ts
//
// Pure tests for the honest "cost by platform" helpers (#6). The per-1k figure
// is the MODEL's blended API token rate — identical across platform rows for one
// model — so it is lifted out of the table and shown once; the table then reads
// as "Your cost is the per-platform column". Third-party pool-billed platforms
// (Cursor) are flagged so the copy names them.

import { test, expect } from "@playwright/test";

import { hasPoolBilledRow, per1kCost, sharedApiRate } from "../lib/cost-format";

// One model across three surfaces at the SAME blended token rate (Anthropic
// bills identically across Claude Code / claude.ai / API) → a single shared rate.
const SINGLE_MODEL = [
  { model: "Opus 4.8", platform: "Claude Code", input_tokens: 1000, output_tokens: 2000, total_usd: 0.155, funding_source: "subscription-included" },
  { model: "Opus 4.8", platform: "claude.ai", input_tokens: 1000, output_tokens: 2000, total_usd: 0.155, funding_source: "subscription-included" },
  { model: "Opus 4.8", platform: "Cursor", input_tokens: 1000, output_tokens: 2000, total_usd: 0.155, funding_source: "subscription-pool" },
];

test("per1kCost is the model's blended token rate", () => {
  // (0.155 / 3000) * 1000 = 0.0517 -> $0.0517
  expect(per1kCost(SINGLE_MODEL[0])).toBe("$0.0517");
});

test("per1kCost falls back to a session total when token counts are absent", () => {
  expect(per1kCost({ total_usd: 0.42 })).toBe("$0.4200 (session)");
  expect(per1kCost({})).toBe("—");
});

test("sharedApiRate returns the single rate when one model spans platforms", () => {
  // The rate is identical across the surfaces, so it collapses to one value.
  expect(sharedApiRate(SINGLE_MODEL)).toBe("$0.0517");
});

test("sharedApiRate is null when rows span different token rates (multiple models)", () => {
  const multi = [
    { model: "Opus 4.8", input_tokens: 1000, output_tokens: 2000, total_usd: 0.155 },
    { model: "Composer 2.5", input_tokens: 1000, output_tokens: 2000, total_usd: 0.005 },
  ];
  expect(sharedApiRate(multi)).toBeNull();
});

test("sharedApiRate is null when any row is session-only or unpriced", () => {
  expect(sharedApiRate([{ total_usd: 0.42 }])).toBeNull();
  expect(sharedApiRate([{}])).toBeNull();
  expect(sharedApiRate([])).toBeNull();
});

test("hasPoolBilledRow detects a subscription-pool platform (Cursor)", () => {
  expect(hasPoolBilledRow(SINGLE_MODEL)).toBe(true);
  expect(
    hasPoolBilledRow([{ funding_source: "subscription-included" }, { funding_source: "per-token" }]),
  ).toBe(false);
});
