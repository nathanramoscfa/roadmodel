// web/tests/glossary.spec.ts
//
// Phase 4.8 dogfood #269 — segmentRationale (the inline-glossary matcher).
// Pure tests over the term/benchmark detection that powers the rationale
// popovers.
import { test, expect } from "@playwright/test";

import { segmentRationale } from "../lib/glossary";

test("detects an S-tier mention with its definition", () => {
  const term = segmentRationale("Fable 5 is S-tier in the agentic category.").find(
    (s) => s.term,
  );
  expect(term?.term).toBe("S-tier");
  expect(term?.text).toBe("S-tier");
  expect(term?.definition).toMatch(/Top-1 or top-2/);
});

test("prefers the longest benchmark match", () => {
  const term = segmentRationale("leads on Terminal-Bench Hard (62.9).").find(
    (s) => s.term,
  );
  // "Terminal-Bench Hard" wins over the shorter "Terminal-Bench".
  expect(term?.text).toBe("Terminal-Bench Hard");
  expect(term?.term).toBe("Terminal-Bench");
});

test("detects multiple terms and reconstructs the text losslessly", () => {
  const input = "Strong SWE-bench Verified and AIME results.";
  const segments = segmentRationale(input);
  expect(segments.map((s) => s.text).join("")).toBe(input);
  expect(segments.some((s) => s.term === "SWE-bench Verified")).toBe(true);
  expect(segments.some((s) => s.term === "AIME")).toBe(true);
});

test("does not match an acronym inside a word", () => {
  // "aime" inside "claimed" must not match the AIME benchmark.
  const segments = segmentRationale("He claimed the result was fine.");
  expect(segments.every((s) => !s.term)).toBe(true);
});

test("text with no glossary terms is a single passthrough segment", () => {
  expect(segmentRationale("A plain sentence with no jargon.")).toEqual([
    { text: "A plain sentence with no jargon." },
  ]);
});
