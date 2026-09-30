// web/tests/score-breakdown.spec.ts
//
// The Score hover card takes a Score apart into parts that must ADD UP to the
// figure printed in the table: AA Index − tier average = vs-average, and
// vs-average + price adjustment = Score. Rounded parts do not naturally sum to
// a rounded total, so lib/benchmark-grid derives the displayed parts in whole
// tenths from the displayed total. These pure tests hold that for EVERY
// measured catalog model, and pin the price-axis ticks the charts draw.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import { extractAaIndex } from "../lib/benchmark-scores";
import {
  blendedPrice,
  expectedIndex,
  fitScoreModel,
  formatScore,
  formatQualityBand,
  frontierLeaders,
  GRID_COLUMNS,
  groupBeatenBy,
  indexEvidence,
  newUntil,
  paretoFrontier,
  priceTicks,
  qualityBand,
  scoreBreakdown,
  scoreFor,
  standing,
  type BenchKey,
  type BenchRow,
} from "../lib/benchmark-grid";

interface CatalogModel {
  id: string;
  name: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  tier_cost: string;
  headline_benchmarks?: string;
}
const catalog = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "catalog.json"), "utf8"),
) as { models: CatalogModel[] };
const benchmarks = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "benchmarks.json"), "utf8"),
) as { models: Record<string, { evaluations: Record<string, number | null> }> };

// Same source order as the page: the AA snapshot, else the catalog's citation.
function aaIndexFor(m: CatalogModel): number | null {
  const measured = benchmarks.models[m.id]?.evaluations.artificial_analysis_intelligence_index;
  if (typeof measured === "number") return measured;
  return extractAaIndex(m.headline_benchmarks ?? "");
}

const priceOf = (m: CatalogModel) => blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
const fit = fitScoreModel(
  catalog.models.map((m) => ({ price: priceOf(m), index: aaIndexFor(m), tier: m.tier_cost })),
);
const tenths = (v: number) => Math.round(v * 10);

test("every model's breakdown adds up exactly to the Score the table prints", () => {
  expect(fit).not.toBeNull();
  let checked = 0;
  for (const m of catalog.models) {
    const b = scoreBreakdown(fit, m.tier_cost, priceOf(m), aaIndexFor(m));
    const score = scoreFor(fit, m.tier_cost, priceOf(m), aaIndexFor(m));
    if (score === null) {
      expect(b).toBeNull();
      continue;
    }
    expect(b).not.toBeNull();
    const s = b!.shown;
    // The ledger, in whole tenths so floating point cannot blur it.
    expect(tenths(s.index) - tenths(s.tierMean)).toBe(tenths(s.vsAverage));
    expect(tenths(s.vsAverage) + tenths(s.priceAdjustment)).toBe(tenths(s.score));
    expect(tenths(s.index) - tenths(s.score)).toBe(tenths(s.expected));
    // The total is the figure the table shows.
    expect(formatScore(s.score)).toBe(formatScore(score));
    // The displayed price adjustment is the model's real one, give or take
    // the rounding it absorbs.
    const trueAdjustment = -b!.slope * Math.log10(b!.priceRatio);
    expect(Math.abs(s.priceAdjustment - trueAdjustment)).toBeLessThanOrEqual(0.15);
    // Expected index is the tier's line at this price.
    expect(b!.expected).toBeCloseTo(expectedIndex(fit!, m.tier_cost, priceOf(m))!, 9);
    checked += 1;
  }
  expect(checked).toBe(fit!.n);
});

test("the typical price is where the tier's line meets the tier average", () => {
  for (const [tier, t] of Object.entries(fit!.tiers)) {
    const typical = 10 ** t.meanLogPrice;
    expect(expectedIndex(fit!, tier, typical)).toBeCloseTo(t.meanIndex, 9);
  }
});

test("price ticks: round values inside the range, enough of them for a narrow tier", () => {
  // A wide range reads 1-2-5.
  expect(priceTicks(0.08, 5.6)).toEqual([0.1, 0.2, 0.5, 1, 2, 5]);
  // A narrow one still gets several round prices, never just one.
  const narrow = priceTicks(8.6, 24);
  expect(narrow).toEqual(expect.arrayContaining([10, 12, 15, 20]));
  expect(narrow.length).toBeGreaterThanOrEqual(4);
  for (const [lo, hi] of [
    [0.08, 5.6],
    [8.6, 24],
    [4.4, 9.9],
    [2.7, 5.9],
  ]) {
    for (const v of priceTicks(lo, hi)) {
      expect(v).toBeGreaterThanOrEqual(lo * 0.999);
      expect(v).toBeLessThanOrEqual(hi * 1.001);
    }
  }
});

test("frontier leaders: a model leads itself exactly when it is on the Pareto frontier", () => {
  const pts = catalog.models.map((m) => ({ id: m.id, price: priceOf(m), index: aaIndexFor(m) }));
  const leaders = frontierLeaders(pts);
  const frontier = paretoFrontier(pts);
  expect(leaders.size).toBe(pts.filter((p) => p.index !== null).length);
  for (const [p, lead] of leaders) {
    expect(lead === p).toBe(frontier.has(p));
    // The leader costs no more and scores no less…
    expect(lead.price).toBeLessThanOrEqual(p.price);
    expect(lead.index!).toBeGreaterThanOrEqual(p.index!);
    // …and nothing at or below this model's price scores higher than it.
    for (const o of pts) {
      if (o.index !== null && o.price <= p.price) expect(o.index).toBeLessThanOrEqual(lead.index!);
    }
  }
});

test("quality bands are fixed ten-point ranges labelled by what they hold", () => {
  expect(qualityBand(57.6)).toBe(50);
  expect(qualityBand(50)).toBe(50);
  expect(qualityBand(49.9)).toBe(40);
  expect(qualityBand(9)).toBe(0);
  expect(qualityBand(null)).toBeNull();
  expect(formatQualityBand(40)).toBe("40–49.9");
  expect(formatQualityBand(0)).toBe("0–9.9");
  // Bands above today's leaders open on their own as models reach them.
  expect(qualityBand(63.2)).toBe(60);
  expect(formatQualityBand(60)).toBe("60–69.9");
  expect(qualityBand(87.5)).toBe(80);
  expect(formatQualityBand(80)).toBe("80–89.9");
  // The index tops out at 100, which joins the 90s rather than a band of one.
  expect(qualityBand(99.9)).toBe(90);
  expect(qualityBand(100)).toBe(90);
  expect(formatQualityBand(90)).toBe("90–100");
});

test("a group is 'beaten' only when none of its measured models is on the frontier", () => {
  const row = (aa: number | null, frontier: boolean, by: string | null) => ({
    aa_index: aa,
    value_frontier: frontier,
    value_beaten_by: by,
  });
  // One model on the frontier: the group is not beaten.
  expect(groupBeatenBy([row(50, true, null), row(40, false, "x")])).toBeNull();
  // Nothing measured: nothing to say.
  expect(groupBeatenBy([row(null, false, null)])).toBeNull();
  // All beaten: the leaders, most frequent first, unmeasured rows ignored.
  expect(
    groupBeatenBy([row(40, false, "b"), row(41, false, "a"), row(42, false, "a"), row(null, false, null)]),
  ).toEqual({ measured: 3, leaders: ["a", "b"] });

  // On the catalog: a group's leaders are always frontier models.
  const pts = catalog.models.map((m) => ({ id: m.id, price: priceOf(m), index: aaIndexFor(m) }));
  const leaders = frontierLeaders(pts);
  const frontierIds = new Set([...paretoFrontier(pts)].map((p) => p.id));
  for (const [p, lead] of leaders) {
    if (lead !== p) expect(frontierIds.has(lead.id)).toBe(true);
  }
});

test("standing ranks from the top, shares the better rank on a tie, and gives a mid-rank percentile", () => {
  const sorted = [10, 20, 20, 30];
  expect(standing(30, sorted)).toEqual({ rank: 1, of: 4, pct: 87.5 });
  expect(standing(20, sorted)).toEqual({ rank: 2, of: 4, pct: 50 });
  expect(standing(10, sorted)).toEqual({ rank: 4, of: 4, pct: 12.5 });
});

// A 10-model column set in which model values run 1..10 on every column.
function columnsOf(): Record<BenchKey, number[]> {
  const ten = Array.from({ length: 10 }, (_, i) => i + 1);
  return Object.fromEntries(GRID_COLUMNS.map((c) => [c.key, ten])) as Record<BenchKey, number[]>;
}
function benchOf(values: Partial<Record<BenchKey, number>>): BenchRow {
  const all = Object.fromEntries(GRID_COLUMNS.map((c) => [c.key, values[c.key] ?? null])) as Record<
    BenchKey,
    number | null
  >;
  return { aa_slug: "m", aa_name: "M (max)", release_date: null, values: all };
}

test("the index agrees with its own benchmarks when their ranks sit together, and leans when they part", () => {
  const cols = columnsOf();
  // Top index, top benchmarks: agrees.
  const top = indexEvidence(
    benchOf({ artificial_analysis_intelligence_index: 10, hle: 10, scicode: 9, lcr: 10 }),
    cols,
  )!;
  expect(top.verdict).toBe("agrees");
  expect(top.index).toMatchObject({ rank: 1, of: 10 });
  // Best standing first; speed never counts as evidence.
  expect(top.items.map((i) => i.key)).toEqual(["hle", "lcr", "scicode"]);
  // Top index over bottom benchmarks: the index leans above them.
  expect(
    indexEvidence(benchOf({ artificial_analysis_intelligence_index: 10, hle: 2, scicode: 3, lcr: 1 }), cols)!
      .verdict,
  ).toBe("above");
  // Bottom index over top benchmarks: below.
  expect(
    indexEvidence(benchOf({ artificial_analysis_intelligence_index: 1, hle: 9, scicode: 10 }), cols)!.verdict,
  ).toBe("below");
  // One benchmark makes no verdict; no index, no evidence.
  const lone = indexEvidence(benchOf({ artificial_analysis_intelligence_index: 5, hle: 5 }), cols)!;
  expect(lone.items).toHaveLength(1);
  expect(lone.verdict).toBeNull();
  expect(indexEvidence(benchOf({ hle: 5 }), cols)).toBeNull();
  expect(indexEvidence(null, cols)).toBeNull();
});

test("a model is new for fourteen days after its release date", () => {
  expect(newUntil("2026-09-28", new Date("2026-09-29T12:00:00Z"))).toBe("2026-10-12");
  expect(newUntil("2026-09-28", new Date("2026-10-11T23:59:59Z"))).toBe("2026-10-12");
  expect(newUntil("2026-09-28", new Date("2026-10-12T00:00:00Z"))).toBeNull();
  expect(newUntil(null, new Date())).toBeNull();
  expect(newUntil("September", new Date())).toBeNull();
});
