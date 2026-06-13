// web/tests/funding.spec.ts
//
// Phase 4.8 T2 (#260 / #163) — the edge funding annotation. Pure tests over
// fundingNoteForModel: a held subscription yields a $0 path, an enabled API
// provider yields a PAYG path, a subscription beats an API key, and nothing
// declared (or an unknown model) yields no note (the recommendation is shown
// without a funding line — never suppressed).

import { test, expect } from "@playwright/test";

import { fundingNoteForModel } from "../lib/funding";

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
