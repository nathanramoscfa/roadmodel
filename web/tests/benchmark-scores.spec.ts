// web/tests/benchmark-scores.spec.ts
//
// The /models numbers: lib/benchmark-scores.ts pulls published leaderboard
// figures out of a row's headline_benchmarks prose. These pure tests pin the
// prose shapes the daily cron actually writes (versions, subsets, ranks, "~"
// throughput, parenthetical qualifiers) and the honesty rules: a figure is
// labelled with the benchmark AS CITED, "%" appears only where the prose has
// it, and a row with no figure for a category shows none.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import { CATEGORY_BENCHMARKS, extractAaIndex, extractScores, scoresFor } from "../lib/benchmark-scores";

test("AA Index: first figure after the name, ranks and settings ignored", () => {
  expect(extractAaIndex("AA Intelligence Index 60.7 (max); HLE 52.6% (max)")).toBe(60.7);
  expect(extractAaIndex("AA Intelligence Index 59.9 (#1); HLE 53.3% (#1)")).toBe(59.9);
  expect(extractAaIndex("AA Intelligence Index 51.2 (max) / 49.1 (xhigh)")).toBe(51.2);
  expect(extractAaIndex("Artificial Analysis Intelligence Index 42 (reasoning)")).toBe(42);
  expect(extractAaIndex("specific AA / LMArena numbers pending benchmark refresh")).toBeNull();
  expect(extractAaIndex("")).toBeNull();
});

test("version and subset tokens are consumed, not read as the score", () => {
  const scores = extractScores(
    "Terminal-Bench 2.1 89.1 (max); τ²-bench banking pass_1 48.7%; Terminal-Bench Hard 62.9 (#1)",
  );
  const tb = scores.find((s) => s.term === "Terminal-Bench");
  expect(tb).toMatchObject({ label: "Terminal-Bench 2.1", short: "TB 2.1", value: 89.1, display: "89.1" });
  const tau = scores.find((s) => s.term === "τ²-bench");
  expect(tau).toMatchObject({ label: "τ²-bench banking", short: "τ² bank", value: 48.7, display: "48.7%" });
});

test("LMArena Elo is read in both citation shapes and shown as a rounded Elo", () => {
  const direct = extractScores("LMArena Text Elo 1478.9 (#11); 1M-token context");
  expect(direct[0]).toMatchObject({ term: "LMArena", label: "LMArena Text", short: "", display: "1479 Elo" });
  const ranked = extractScores("LMArena Text #5 (Elo 1481.7); LMArena WebDev #5 (Elo 1556.9)");
  expect(ranked[0]).toMatchObject({ value: 1481.7, display: "1482 Elo" });
});

test("throughput reads 'Output Speed N tokens/s' and '~N tokens/s'", () => {
  expect(extractScores("Output Speed 151.4 tokens/s; latency leader")[0]).toMatchObject({
    term: "Output speed",
    display: "151 tok/s",
  });
  expect(extractScores("hosted by Groq (~500 tokens/s); us-jurisdiction")[0]).toMatchObject({
    display: "~500 tok/s",
  });
});

test("'%' is shown only where the prose writes it; parentheticals are skipped", () => {
  const scores = extractScores(
    "GPQA 90.3; LiveCodeBench 88.9; HLE 35.4%; SWE-bench Verified (mini-SWE-agent) 72.8%",
  );
  expect(scores.map((s) => s.display)).toEqual(["90.3", "88.9", "35.4%", "72.8%"]);
});

test("a benchmark named without a figure yields nothing", () => {
  expect(
    extractScores("Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance"),
  ).toEqual([]);
  expect(extractScores("specific public benchmark numbers pending")).toEqual([]);
});

test("figures glued to letters (1M, o3-mini) and negatives are never scores", () => {
  expect(extractScores("1M-token context; positions it near o3-mini; AA-Omniscience -4.2")).toEqual([]);
});

test("category mapping mirrors the cron's source-to-category rule", () => {
  // update/prompt.md "Tier rating updates": SWE-bench Verified / Aider /
  // LiveCodeBench / CursorBench → coding; Terminal-Bench / τ²-bench → agentic;
  // MMMU → multimodal; HLE / GPQA → knowledge; LMArena Elo → planning; tokens/s → speed.
  expect(CATEGORY_BENCHMARKS.coding[0]).toBe("SWE-bench Verified");
  expect(CATEGORY_BENCHMARKS.agentic).toEqual(["Terminal-Bench", "τ²-bench"]);
  expect(CATEGORY_BENCHMARKS.multimodal).toEqual(["MMMU"]);
  expect(CATEGORY_BENCHMARKS.knowledge[0]).toBe("Humanity's Last Exam");
  expect(CATEGORY_BENCHMARKS.planning).toEqual(["LMArena"]);
  expect(CATEGORY_BENCHMARKS.speed).toEqual(["Output speed"]);
  expect(CATEGORY_BENCHMARKS["long-context"]).toEqual([]);
});

test("scoresFor picks one headline figure per category", () => {
  const row = scoresFor(
    "AA Intelligence Index 52 (reasoning, max effort) — independently measured; SWE-bench Verified 80.6%, LiveCodeBench 93.5, Terminal-Bench 2.0 67.9, Codeforces CodeElo 3206; 1M-token context; ~46 tokens/s (notably slow)",
  );
  expect(row.aaIndex).toBe(52);
  expect(row.byCategory.coding?.display).toBe("80.6%");
  expect(row.byCategory.agentic?.label).toBe("Terminal-Bench 2.0");
  expect(row.byCategory.speed?.display).toBe("~46 tok/s");
  expect(row.byCategory.knowledge).toBeUndefined();
  expect(row.byCategory["long-context"]).toBeUndefined();
});

test("every catalog row parses without throwing and most rows carry an AA Index", () => {
  const catalog = JSON.parse(
    readFileSync(path.join(process.cwd(), "data", "catalog.json"), "utf8"),
  ) as { models: { headline_benchmarks?: string }[] };
  let withAa = 0;
  for (const m of catalog.models) {
    const row = scoresFor(m.headline_benchmarks ?? "");
    if (row.aaIndex !== null) withAa += 1;
    for (const s of row.all) {
      expect(Number.isFinite(s.value)).toBe(true);
      expect(s.display.length).toBeGreaterThan(0);
    }
  }
  // The composite is the densest figure in the catalog; if this drops sharply
  // the cron has changed how it writes the prose and the extractor needs care.
  expect(withAa).toBeGreaterThan(catalog.models.length / 2);
});
