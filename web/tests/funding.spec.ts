// web/tests/funding.spec.ts
//
// Phase 4.8 T2 (#260 / #163) — the edge funding annotation. Pure tests over
// fundingNoteForModel: a held subscription yields a $0 path, an enabled API
// provider yields a PAYG path, a subscription beats an API key, and nothing
// declared (or an unknown model) yields no note (the recommendation is shown
// without a funding line — never suppressed).

import { test, expect } from "@playwright/test";

import { fundingNoteForModel, personalizeComparison } from "../lib/funding";

test("a held subscription that funds the model yields a $0 path", () => {
  const note = fundingNoteForModel("Claude 4.5 Haiku", ["claude-max"], []);
  expect(note).toContain("$0 path");
  expect(note).toContain("Claude Max");
  // The "($200)" disambiguator is stripped from the note.
  expect(note).not.toContain("($200)");
});

test("an enabled API provider yields a pay-per-token path", () => {
  const note = fundingNoteForModel("Claude 4.5 Haiku", [], ["anthropic"]);
  expect(note).toContain("Anthropic API");
  expect(note).toMatch(/\/M output/);
});

test("a held subscription beats an enabled API key", () => {
  const note = fundingNoteForModel(
    "Claude 4.5 Haiku",
    ["claude-max"],
    ["anthropic"],
  );
  expect(note).toContain("$0 path");
});

test("no declared funding → no note (recommendation still shown)", () => {
  expect(fundingNoteForModel("Claude 4.5 Haiku", [], [])).toBeNull();
});

test("an unknown model → no note", () => {
  expect(
    fundingNoteForModel("Not A Real Model", ["claude-max"], ["anthropic"]),
  ).toBeNull();
});

// --- Phase 4.8 T3: personalizeComparison (cost-table personalization) ---

const CLAUDE_CODE_ROW = {
  model_id: "claude-4.5-haiku",
  platform_id: "claude-code",
  platform_name: "Claude Code",
  total_usd: 0.01,
};
const ANTHROPIC_API_ROW = {
  model_id: "claude-4.5-haiku",
  platform_id: "anthropic-api",
  platform_name: "Anthropic API",
  total_usd: 0.012,
};

test("personalize: a held subscription marks the row $0 and funded", () => {
  const [row] = personalizeComparison([CLAUDE_CODE_ROW], ["claude-max"], []);
  expect(row.funded).toBe(true);
  expect(row.your_cost).toBe("$0 · Claude Max");
});

test("personalize: an enabled API provider shows a pay-per-token path", () => {
  const [row] = personalizeComparison([ANTHROPIC_API_ROW], [], ["anthropic"]);
  expect(row.funded).toBe(false);
  expect(row.your_cost).toContain("your Anthropic API");
});

test("personalize: a path the user does not fund reads as not funded", () => {
  // Holds Claude Max (funds claude-code) but not an Anthropic API key.
  const [row] = personalizeComparison([ANTHROPIC_API_ROW], ["claude-max"], []);
  expect(row.funded).toBe(false);
  expect(row.your_cost).toBe("pay-per-token (not funded)");
});

test("personalize: funded rows are ranked ahead of unfunded ones", () => {
  const rows = personalizeComparison(
    [ANTHROPIC_API_ROW, CLAUDE_CODE_ROW],
    ["claude-max"],
    [],
  );
  expect(rows[0].platform_id).toBe("claude-code"); // funded -> first
  expect(rows[0].funded).toBe(true);
  expect(rows[1].platform_id).toBe("anthropic-api");
  expect(rows[1].funded).toBe(false);
});

test("personalize: anon / no declared funding leaves rows unchanged", () => {
  const rows = personalizeComparison([CLAUDE_CODE_ROW, ANTHROPIC_API_ROW], [], []);
  expect(rows).toEqual([CLAUDE_CODE_ROW, ANTHROPIC_API_ROW]);
  expect(rows[0].your_cost).toBeUndefined();
});
