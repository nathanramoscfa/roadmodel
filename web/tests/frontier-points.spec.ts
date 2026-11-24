// web/tests/frontier-points.spec.ts
//
// The points /recommend's frontier is drawn over (lib/frontier-points.ts).
// An answer carries the settings its own ladder weighed, each with the AA
// Index it prints and the margin the recommender counts an estimate below it;
// the page draws the frontier over those, where the recommender counts them,
// so a pick sits on the line where the recommender found it. Pure tests over
// synthetic rows: the rule itself, with no catalog figure to age.

import { test, expect } from "@playwright/test";

import type { LadderPoint } from "../lib/api";
import { getModelRows } from "../lib/catalog-models";
import type { ModelRow } from "../lib/catalog-fields";
import {
  MAX_POINTS,
  frontierOf,
  leaderAt,
  parsePoints,
  pointFor,
  pointKey,
  pointName,
  pointRow,
} from "../lib/frontier-points";
import { picksData } from "../lib/recommend-picks";

// A catalog row with the figures a test names, on the shape of a real one.
const TEMPLATE = getModelRows()[0];
function row(id: string, over: Partial<ModelRow> = {}): ModelRow {
  return {
    ...TEMPLATE,
    id,
    name: id.toUpperCase(),
    input_price_per_1m: 1,
    output_price_per_1m: 1,
    aa_index: 50,
    aa_index_source: "snapshot",
    aa_index_effort: null,
    aa_index_by_effort: undefined,
    token_multiplier_by_effort: undefined,
    configuration: undefined,
    superseded_by: null,
    ...over,
  };
}

function point(model_id: string, effort: string | null, aa: number, price: number, over: Partial<LadderPoint> = {}): LadderPoint {
  return { model_id, platform_id: "p", effort, aa_index: aa, margin: 0, price_usd_per_1m: price, adequate: true, estimated: false, ...over };
}

const ROWS = [row("a"), row("b"), row("c"), row("d")];
const DATA = picksData(ROWS);
const keys = (f: ReturnType<typeof frontierOf>) => f.points.filter((p) => p.frontier).map((p) => p.key);

test("the frontier keeps each point that scores higher than every cheaper one", () => {
  const f = frontierOf(DATA, [
    point("a", "low", 30, 1),
    point("a", "high", 40, 2),
    point("b", "high", 35, 3), // costs more than a@high and scores lower
    point("c", "high", 50, 4),
    point("d", null, 45, 5), // beaten by c
  ]);
  expect(f.served).toBe(true);
  expect(f.points.map((p) => p.key)).toEqual(["a@low", "a@high", "b@high", "c@high", "d@-"]);
  expect(keys(f)).toEqual(["a@low", "a@high", "c@high"]);
});

test("a tie on the index goes to the cheaper point", () => {
  // The same score for more money is not on the frontier: the cards, the
  // chart's ring and the line all read this one rule.
  const f = frontierOf(DATA, [point("a", "max", 56, 8), point("b", "xhigh", 56, 8.29), point("c", "low", 40, 1)]);
  expect(keys(f)).toEqual(["c@low", "a@max"]);
  const b = f.byKey.get("b@xhigh")!;
  expect(leaderAt(f, b)?.key).toBe("a@max");
  // And the point that holds the top score at its price leads nothing.
  expect(leaderAt(f, f.byKey.get("a@max")!)).toBeNull();
});

test("an estimate stands where the recommender counts it, a margin below the figure it prints", () => {
  // b prints 53 and is counted 1.8 lower (51.2): it costs less than a and
  // prints higher, yet a (52.6, measured) is on the frontier, as the
  // recommender has it.
  const f = frontierOf(DATA, [
    point("b", "xhigh", 53, 3.23, { margin: 1.8, estimated: true }),
    point("a", "high", 52.6, 6.13),
  ]);
  const b = f.byKey.get("b@xhigh")!;
  expect(b.shown).toBe(53);
  expect(b.index).toBeCloseTo(51.2, 6);
  expect(b.estimated).toBe(true);
  expect(keys(f)).toEqual(["b@xhigh", "a@high"]);
  expect(leaderAt(f, f.byKey.get("a@high")!)).toBeNull();
  // The card reads the printed figure and says how far below it is counted.
  const card = pointRow(f, b);
  expect(card.aa_index).toBe(53);
  expect(card.aa_index_margin).toBeCloseTo(1.8, 6);
  expect(card.name).toBe("B · Extra high");
  expect(card.value_frontier).toBe(true);
});

test("a point's card names what holds the top score at its price", () => {
  const f = frontierOf(DATA, [point("a", "high", 50, 2), point("b", "high", 40, 3), point("c", "high", 60, 9)]);
  const b = f.byKey.get("b@high")!;
  const card = pointRow(f, b);
  expect(card.value_frontier).toBe(false);
  expect(card.value_beaten_by).toBe("a@high");
  expect(pointName(b)).toBe("B · High");
  expect(pointName(frontierOf(DATA, [point("a", null, 50, 2), point("b", null, 60, 3)]).points[0])).toBe("A");
});

test("a model is found at its own level, or at its one point when the frontier names no level for it", () => {
  const f = frontierOf(DATA, [point("a", "low", 30, 1), point("a", "high", 40, 2), point("b", null, 50, 3)]);
  expect(pointFor(f, "a", "high")?.key).toBe("a@high");
  expect(pointFor(f, "a", "max")).toBeNull();
  // b has one point and no level: a pick of b at any level sits there.
  expect(pointFor(f, "b", "medium")?.key).toBe("b@-");
  expect(pointFor(f, "nope", null)).toBeNull();
  expect(pointKey("a", null)).toBe("a@-");
});

test("each point says whether it meets the task's bar", () => {
  const f = frontierOf(DATA, [point("a", "low", 30, 1, { adequate: false }), point("b", "high", 50, 2)]);
  expect(f.points.map((p) => p.adequate)).toEqual([false, true]);
});

test("points the catalog cannot place are left out, and too few fall back to the catalog's own", () => {
  const some = frontierOf(DATA, [point("a", "high", 40, 2), point("ghost", "high", 99, 1), point("b", "high", 50, 3)]);
  expect(some.served).toBe(true);
  expect(some.points.map((p) => p.key)).toEqual(["a@high", "b@high"]);
  // One usable point draws no frontier: the page's own rows stand in.
  for (const served of [[point("a", "high", 40, 2), point("ghost", "high", 99, 1)], [], null, undefined]) {
    const f = frontierOf(DATA, served);
    expect(f.served).toBe(false);
    expect(new Set(f.points.map((p) => p.row.id))).toEqual(new Set(["a", "b", "c", "d"]));
  }
});

test("without an answer's points the frontier is over the viewer's models at every measured effort", () => {
  const rows = [
    row("a", { aa_index: 40, aa_index_effort: "high", aa_index_by_effort: { low: 30, high: 40 }, output_price_per_1m: 4 }),
    row("b", { aa_index: 60, input_price_per_1m: 10, output_price_per_1m: 10 }),
    row("c", { aa_index: null }),
    row("d", { aa_index: 55, input_price_per_1m: 5, output_price_per_1m: 5 }),
  ];
  const whole = frontierOf(picksData(rows), null);
  expect(whole.served).toBe(false);
  expect(whole.points.map((p) => p.key).sort()).toEqual(["a@high", "a@low", "b@-", "d@-"]);
  expect(whole.points.every((p) => p.adequate && p.shown === p.index)).toBe(true);
  // With saved Settings, only the models they reach.
  const mine = frontierOf(picksData(rows, { pool: new Set(["a", "d"]) }), null);
  expect(new Set(mine.points.map((p) => p.row.id))).toEqual(new Set(["a", "d"]));
});

test("an answer's points are checked one by one before the page plots them", () => {
  const good = point("a", "high", 40, 2, { margin: 1.5 });
  const parsed = parsePoints([
    good,
    { ...good, model_id: "" },
    { ...good, aa_index: "40" },
    { ...good, price_usd_per_1m: 0 },
    { ...good, price_usd_per_1m: Number.NaN },
    { model_id: "b", aa_index: 50, price_usd_per_1m: 3, effort: 7, margin: -2, adequate: "no" },
    null,
    "a@high",
  ]);
  expect(parsed).toEqual([
    good,
    { model_id: "b", platform_id: "", effort: null, aa_index: 50, margin: 0, price_usd_per_1m: 3, adequate: true, estimated: false },
  ]);
  for (const nothing of [null, undefined, "points", {}, [], [{ model_id: "a" }]]) {
    expect(parsePoints(nothing)).toBeNull();
  }
  expect(parsePoints(Array.from({ length: MAX_POINTS + 50 }, () => good))).toHaveLength(MAX_POINTS);
});
