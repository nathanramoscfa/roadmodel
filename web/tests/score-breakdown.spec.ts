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
  frontierLeaders,
  paretoFrontier,
  priceTicks,
  scoreBreakdown,
  scoreFor,
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
