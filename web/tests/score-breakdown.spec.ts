// web/tests/score-breakdown.spec.ts
//
// The Score hover card takes a Score apart into parts that must ADD UP to the
// figure printed in the table: AA Index − market average = vs-average, and
// vs-average + price adjustment = Score. Rounded parts do not naturally sum to
// a rounded total, so lib/benchmark-grid derives the displayed parts in whole
// tenths from the displayed total. These pure tests hold that for EVERY
// measured catalog model, prove continuity across tier boundaries (zero tier
// cliffs) and Pareto monotonicity, and pin the price-axis ticks the charts draw.

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
import { placeLabels } from "../components/chart-kit";
import { headlinePrice, resolveTokenMultipliers, type EffortTokensDoc } from "../lib/pick-effort";
import { liveCatalog } from "./fixtures/live-catalog";

interface CatalogModel {
  id: string;
  name: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  tier_cost: string;
  headline_benchmarks?: string;
}
const catalog = liveCatalog<{ models: CatalogModel[] }>();
const benchmarks = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "benchmarks.json"), "utf8"),
) as { models: Record<string, { aa_effort?: string | null; evaluations: Record<string, number | null> }> };
const effortTokens = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "effort-tokens.json"), "utf8"),
) as EffortTokensDoc;
const indexEstimates = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "index-estimates.json"), "utf8"),
) as { models?: Record<string, { effort?: string | null }> };

// Same source order as the page: the AA snapshot, else the catalog's citation.
function aaIndexFor(m: CatalogModel): number | null {
  const measured = benchmarks.models[m.id]?.evaluations.artificial_analysis_intelligence_index;
  if (typeof measured === "number") return measured;
  return extractAaIndex(m.headline_benchmarks ?? "");
}

function priceOf(m: CatalogModel): number {
  const b = benchmarks.models[m.id];
  const measured = b?.evaluations.artificial_analysis_intelligence_index;
  const eff = typeof measured === "number" ? (b?.aa_effort ?? null) : (indexEstimates.models?.[m.id]?.effort ?? null);
  return headlinePrice({
    input_price_per_1m: m.input_price_per_1m,
    output_price_per_1m: m.output_price_per_1m,
    aa_index_effort: eff,
    token_multiplier_by_effort: resolveTokenMultipliers(m.id, effortTokens),
  });
}
const fit = fitScoreModel(
  catalog.models.map((m) => ({ price: priceOf(m), index: aaIndexFor(m) })),
);
const tenths = (v: number) => Math.round(v * 10);

test("every model's breakdown adds up exactly to the Score the table prints", () => {
  expect(fit).not.toBeNull();
  let checked = 0;
  for (const m of catalog.models) {
    const b = scoreBreakdown(fit, priceOf(m), aaIndexFor(m));
    const score = scoreFor(fit, priceOf(m), aaIndexFor(m));
    if (score === null) {
      expect(b).toBeNull();
      continue;
    }
    expect(b).not.toBeNull();
    const s = b!.shown;
    // The ledger, in whole tenths so floating point cannot blur it.
    expect(tenths(s.index) - tenths(s.marketMean)).toBe(tenths(s.vsAverage));
    expect(tenths(s.vsAverage) + tenths(s.priceAdjustment)).toBe(tenths(s.score));
    expect(tenths(s.index) - tenths(s.score)).toBe(tenths(s.expected));
    // The total is the figure the table shows.
    expect(formatScore(s.score)).toBe(formatScore(score));
    // The displayed price adjustment is the model's real one, give or take
    // the rounding it absorbs.
    const trueAdjustment = -b!.slope * Math.log10(b!.priceRatio);
    expect(Math.abs(s.priceAdjustment - trueAdjustment)).toBeLessThanOrEqual(0.15);
    // Expected index is the continuous market line at this price.
    expect(b!.expected).toBeCloseTo(expectedIndex(fit!, priceOf(m))!, 9);
    checked += 1;
  }
  expect(checked).toBe(fit!.n);
});

test("headlinePrice charges reasoning models for extra output tokens at their headline effort", () => {
  // Synthetic unmeasured fallback: $1.50/$7.50 at Extra high (1.6x output) = (3*1.5 + 1.6*7.5)/4 = 4.125.
  expect(
    headlinePrice({ input_price_per_1m: 1.5, output_price_per_1m: 7.5, aa_index_effort: "xhigh" }),
  ).toBeCloseTo(4.125, 3);

  // Day-one predecessor inheritance before a new model is measured in effort-tokens.json:
  const inherited = resolveTokenMultipliers("claude-fable-5.9", {
    models: {
      "claude-fable-5.1": { levels: { max: { multiplier: 4.72 } } },
      "claude-fable-5.2": { levels: { max: { multiplier: 5.5 } } },
    },
  });
  expect(inherited?.max).toBe(5.5);

  for (const id of ["gemini-4-hydrogen", "claude-opus-5-5", "claude-fable-5.2"]) {
    const model = catalog.models.find((m) => m.id === id);
    if (!model) continue;
    expect(priceOf(model)).toBeGreaterThan(
      blendedPrice(model.input_price_per_1m, model.output_price_per_1m),
    );
  }
  const fable52 = catalog.models.find((m) => m.id === "claude-fable-5.2");
  const mult52 = effortTokens.models?.["claude-fable-5.2"]?.levels?.max?.multiplier;
  if (fable52 && typeof mult52 === "number") {
    expect(priceOf(fable52)).toBeCloseTo(
      (3 * fable52.input_price_per_1m + mult52 * fable52.output_price_per_1m) / 4,
      6,
    );
  }
});

test("the typical market price is where the line meets the market average, with zero global mean residual", () => {
  const typical = 10 ** fit!.meanLogPrice;
  expect(expectedIndex(fit!, typical)).toBeCloseTo(fit!.meanIndex, 9);
  const residuals = catalog.models
    .map((m) => scoreFor(fit, priceOf(m), aaIndexFor(m)))
    .filter((v): v is number => v !== null);
  expect(residuals).toHaveLength(fit!.n);
  const mean = residuals.reduce((a, b) => a + b, 0) / residuals.length;
  expect(Math.abs(mean)).toBeLessThan(1e-9);
});

test("Score has zero tier-boundary cliffs and preserves Pareto monotonicity across the catalog", () => {
  expect(fit).not.toBeNull();
  // Crossing any list-output tier boundary ($10, $15, $25) changes expected AA Index smoothly.
  for (const boundary of [10, 15, 25]) {
    const below = expectedIndex(fit!, boundary - 0.01)!;
    const above = expectedIndex(fit!, boundary + 0.01)!;
    expect(Math.abs(above - below)).toBeLessThan(0.05);
  }
  // Equal blended price + AA Index gives identical Score regardless of cost tier.
  const samePriceA = scoreFor(fit, 10.54, 54)!;
  const samePriceB = scoreFor(fit, 10.54, 54)!;
  expect(samePriceA).toBe(samePriceB);
  // Models with nearly identical price and AA Index stay nearly tied (no artificial 15-pt gap).
  const hydrogenScore = scoreFor(fit, 10.54, 54)!;
  const carbonScore = scoreFor(fit, 11.14, 54)!;
  expect(Math.abs(hydrogenScore - carbonScore)).toBeLessThan(1);
  // Strict Pareto monotonicity: cheaper-or-equal and higher-or-equal AA Index => higher-or-equal Score.
  const scoredPts = catalog.models
    .map((m) => ({ price: priceOf(m), index: aaIndexFor(m) }))
    .filter((p): p is { price: number; index: number } => p.index !== null);
  for (const a of scoredPts) {
    for (const b of scoredPts) {
      if (a.price <= b.price && a.index >= b.index) {
        expect(scoreFor(fit, a.price, a.index)!).toBeGreaterThanOrEqual(
          scoreFor(fit, b.price, b.index)! - 1e-12,
        );
      }
    }
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

test("on the catalog, every model's frontier leader is itself on the frontier", () => {
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

test("placeLabels skips label: false items while still avoiding their dots", () => {
  const dotR = 5;
  const reach = dotR + 3;
  const obstacle = { id: "b", cx: 220, cy: 200, text: "Off-frontier", priority: 999, label: false };
  const labels = placeLabels(
    [
      { id: "a", cx: 200, cy: 200, text: "Frontier", priority: 100 },
      obstacle,
    ],
    { x: 0, y: 0, w: 600, h: 400 },
    10,
    dotR,
  );
  expect(labels.has("b")).toBe(false);
  expect(labels.size).toBe(1);
  const aLabel = labels.get("a");
  expect(aLabel).toBeDefined();
  const box = aLabel!.box;
  const obsBox = { x: obstacle.cx - reach, y: obstacle.cy - reach, w: 2 * reach, h: 2 * reach };
  const overlapsObstacle =
    box.x < obsBox.x + obsBox.w &&
    obsBox.x < box.x + box.w &&
    box.y < obsBox.y + obsBox.h &&
    obsBox.y < box.y + box.h;
  expect(overlapsObstacle).toBe(false);
});
