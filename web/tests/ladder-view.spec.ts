// web/tests/ladder-view.spec.ts
//
// One shape for an answer, whichever lane wrote it (lib/ladder-view.ts): Cost,
// Balanced and Quality, each ranked three deep as a roadmap's Settings rank it
// (the Pick, a Runner-up and a Backup from other makers), every option with
// the platform and level it runs at and its AA Index and price there. Pure
// tests: synthetic rows for the rules, then the captured answers as the page
// reads them.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import type { LadderPoint, MultiRecommendResponse, PriorityRecommendation, RankedOption } from "../lib/api";
import type { ModelRow } from "../lib/catalog-fields";
import { getBenchmarkMeta, getModelRows, getScoreFit } from "../lib/catalog-models";
import type { KeylessResponse } from "../lib/keyless";
import { categoryLabel, complexityLabel, parseLadderTask, rankedFor } from "../lib/ladder-task";
import { engineLadder, fundedZero, headlineCost, parseRanks, quickLadder } from "../lib/ladder-view";
import { picksData } from "../lib/recommend-picks";
import { toSaved } from "../lib/saved-recommendations";

const fixture = (name: string) => JSON.parse(readFileSync(path.join(__dirname, "fixtures", name), "utf8"));
const RANKED: MultiRecommendResponse = fixture("recommend-ranked.json");
const LEGACY: MultiRecommendResponse = fixture("recommend-response.json");

// A catalog row with the figures a test names, on the shape of a real one.
const TEMPLATE = getModelRows()[0];
function row(id: string, name: string, over: Partial<ModelRow> = {}): ModelRow {
  return {
    ...TEMPLATE,
    id,
    name,
    input_price_per_1m: 2,
    output_price_per_1m: 10,
    aa_index: 50,
    aa_index_source: "snapshot",
    aa_index_effort: "high",
    aa_index_by_effort: { medium: 45, high: 50 },
    token_multiplier_by_effort: { medium: 0.8, high: 1 },
    tiers_by_effort: undefined,
    configuration: undefined,
    superseded_by: null,
    ...over,
  };
}

const ROWS = [
  row("alpha", "Alpha"),
  row("beta", "Beta", { aa_index: 55, aa_index_by_effort: { high: 52, xhigh: 55 }, aa_index_effort: "xhigh", token_multiplier_by_effort: { high: 1, xhigh: 1.6 } }),
  row("gamma", "Gamma", { aa_index: 48, aa_index_source: "estimated", aa_index_by_effort: undefined, aa_index_effort: "high", aa_index_band: 3.5 }),
];
const FIT = getScoreFit(getModelRows());
const DATA = picksData(ROWS, { fit: FIT, snapshot: "2026-11-23 00:00 UTC" });

function ranked(model_id: string, model: string, over: Partial<RankedOption> = {}): RankedOption {
  return {
    model,
    model_id,
    platform: "Claude Code",
    platform_id: "claude-code",
    effort: "high",
    level: "High",
    aa_index: 50,
    aa_estimated: false,
    price_usd_per_1m: 4,
    price_measured: true,
    stepped_down: false,
    ultracode: false,
    ...over,
  };
}

function rec(priority: PriorityRecommendation["priority"], over: Partial<PriorityRecommendation> = {}): PriorityRecommendation {
  return {
    priority,
    model: "Alpha",
    platform: "Claude Code",
    settings: { effort: "High", thinking: "On", budget_priority: priority, rationale: "It fits." },
    session_cost_estimate: {},
    comparison_table: [],
    ...over,
  };
}

function answer(recommendations: PriorityRecommendation[], over: Partial<MultiRecommendResponse> = {}): MultiRecommendResponse {
  return { recommendations, primary: "balanced", ...over };
}

const point = (model_id: string, effort: string | null, aa: number, price: number, over: Partial<LadderPoint> = {}): LadderPoint => ({
  model_id, platform_id: "claude-code", effort, aa_index: aa, margin: 0, price_usd_per_1m: price, adequate: true, estimated: false, ...over,
});

test("columns read Cost, Balanced, Quality, whatever order the answer lists them in", () => {
  const view = engineLadder(DATA, answer([rec("best"), rec("cheap"), rec("balanced")], { primary: "best" }));
  expect(view.columns.map((c) => c.priority)).toEqual(["cheap", "balanced", "best"]);
  expect(view.primary).toBe("best");
  expect(view.primaryLabel).toBe("Default");
  expect(view.source).toBe("engine");
});

test("a ranked pick carries its Runner-up and Backup, each with its own platform, level and figures", () => {
  const ranks = {
    pick: ranked("alpha", "Alpha"),
    runner_up: ranked("beta", "Beta", { platform: "Codex", platform_id: "codex-cli", effort: "xhigh", level: "XHigh", aa_index: 55, price_usd_per_1m: 6.5 }),
    backup: ranked("gamma", "Gamma", { platform: "Antigravity", platform_id: "antigravity", effort: "medium", level: "Medium", aa_index: 44.2, aa_estimated: true, price_usd_per_1m: 3.1, price_measured: false }),
  };
  const view = engineLadder(DATA, answer([rec("balanced", { ranks, backup: { model: "Legacy", platform: "Cursor", settings: {} } })]));
  const [column] = view.columns;
  expect(view.ranked).toBe(true);
  expect(column.ranked).toBe(true);
  expect([column.pick.rank, column.runnerUp?.rank, column.backup?.rank]).toEqual(["pick", "runner_up", "backup"]);
  // The Runner-up: another maker's model, where it runs, and its figures there.
  expect(column.runnerUp).toMatchObject({ model: "Beta", platform: "Codex", level: "Extra high", effort: "xhigh", dial: "Intelligence", aa: 55, price: 6.5, priceEstimated: false });
  // The Backup the service ranked stands in place of the answer's older single backup.
  expect(column.backup).toMatchObject({ model: "Gamma", platform: "Antigravity", level: "Medium", effort: "medium", dial: "Effort", aa: 44.2, aaEstimated: true, price: 3.1, priceEstimated: true });
  // A figure the service read for a level the catalog has no row for is the one shown.
  expect(column.backup?.row?.aa_index).toBe(44.2);
  expect(column.backup?.row?.name).toBe("Gamma · Medium");
});

test("an answer from before the ranks keeps its Pick and its one backup, read from the catalog", () => {
  const view = engineLadder(
    DATA,
    answer([rec("balanced", { backup: { model: "Beta", platform: "Codex", settings: { intelligence: "XHigh" } } })]),
  );
  const [column] = view.columns;
  expect(view.ranked).toBe(false);
  expect(column.runnerUp).toBeNull();
  // The Pick at High: AA's row at that effort, priced at the tokens it writes there.
  expect(column.pick).toMatchObject({ model: "Alpha", platform: "Claude Code", level: "High", effort: "high", dial: "Effort", aa: 50 });
  expect(column.pick.price).toBeCloseTo((3 * 2 + 10 * 1) / 4, 6);
  // Codex calls its level dial Intelligence.
  expect(column.backup).toMatchObject({ model: "Beta", platform: "Codex", level: "Extra high", dial: "Intelligence", aa: 55 });
  expect(column.backup?.price).toBeCloseTo((3 * 2 + 10 * 1.6) / 4, 6);
  expect(view.frontier.served).toBe(false);
});

test("a level reads as the dials word it; a surface with no dial shows none and is still read at one", () => {
  const view = engineLadder(
    DATA,
    answer([
      rec("cheap", { ranks: { pick: ranked("alpha", "Alpha", { effort: "medium", level: "—", platform: "Cursor", platform_id: "cursor", aa_index: 45, price_usd_per_1m: 3.5 }), runner_up: null, backup: null }, platform: "Cursor" }),
      rec("balanced", { ranks: { pick: ranked("alpha", "Alpha", { effort: "fixed", level: "Fixed", aa_index: 50, price_usd_per_1m: 4 }), runner_up: null, backup: null } }),
      rec("best", { ranks: { pick: ranked("beta", "Beta", { effort: "xhigh", level: "XHigh", aa_index: 55, price_usd_per_1m: 6.5 }), runner_up: null, backup: ranked("beta", "Beta", { effort: "high", level: "High", aa_index: 52, price_usd_per_1m: 5, stepped_down: true }) }, model: "Beta" }),
    ]),
  );
  const [cost, balanced, quality] = view.columns;
  // Cursor: no level to set, and its figures are the model's at the level the recommender read.
  expect(cost.pick.level).toBeNull();
  expect(cost.pick.effort).toBe("medium");
  expect(cost.pick.row?.name).toBe("Alpha · Medium");
  expect(balanced.pick.level).toBe("Fixed");
  expect(balanced.pick.effort).toBeNull();
  expect(quality.pick.level).toBe("Extra high");
  // A rank no other maker fills: the Pick's own model a level lower.
  expect(quality.backup).toMatchObject({ model: "Beta", level: "High", steppedDown: true });
  expect(quality.runnerUp).toBeNull();
  expect(view.ranked).toBe(true);
});

test("a figure the service measured stays a measurement at a level the catalog does not name", () => {
  // AA names no effort for this model: its one figure stands at whatever
  // level a surface runs it. The service says it is no estimate, so it is
  // not marked ≈; an estimate for a level AA did not measure is.
  const rows = [row("plain", "Plain", { aa_index: 41, aa_index_effort: null, aa_index_by_effort: undefined }), row("alpha", "Alpha")];
  const data = picksData(rows, { fit: FIT });
  const view = engineLadder(
    data,
    answer([
      rec("cheap", { model: "Plain", ranks: { pick: ranked("plain", "Plain", { aa_index: 41, aa_estimated: false, price_usd_per_1m: 3 }), runner_up: null, backup: null } }),
      rec("best", { ranks: { pick: ranked("alpha", "Alpha", { effort: "xhigh", level: "XHigh", aa_index: 52.4, aa_estimated: true, price_usd_per_1m: 5 }), runner_up: null, backup: null } }),
    ]),
  );
  const [measured, estimated] = view.columns.map((c) => c.pick);
  expect(measured).toMatchObject({ aa: 41, aaEstimated: false });
  expect(measured.row?.aa_index_level_estimated).toBe(false);
  expect(estimated).toMatchObject({ aa: 52.4, aaEstimated: true, level: "Extra high" });
  expect(estimated.row?.aa_index_level_estimated).toBe(true);
});

test("each option's standing is read from the frontier the picks were read from", () => {
  const points = [
    point("gamma", "high", 48, 2.2, { margin: 1.8, estimated: true }),
    point("alpha", "medium", 45, 3.5, { adequate: false }),
    point("alpha", "high", 50, 4),
    point("beta", "high", 52, 5),
    point("beta", "xhigh", 55, 6.5),
  ];
  const view = engineLadder(
    DATA,
    answer(
      [
        rec("cheap", { model: "Gamma", ranks: { pick: ranked("gamma", "Gamma", { aa_index: 48, aa_estimated: true, price_usd_per_1m: 2.2 }), runner_up: ranked("alpha", "Alpha", { effort: "medium", level: "Medium", aa_index: 45, price_usd_per_1m: 3.5 }), backup: null } }),
        rec("balanced", { ranks: { pick: ranked("alpha", "Alpha"), runner_up: null, backup: null } }),
        rec("best", { model: "Beta", ranks: { pick: ranked("beta", "Beta", { effort: "xhigh", level: "XHigh", aa_index: 55, price_usd_per_1m: 6.5 }), runner_up: null, backup: null } }),
      ],
      { points },
    ),
  );
  expect(view.frontier.served).toBe(true);
  const [cost, balanced, quality] = view.columns;
  // Gamma prints 48 and is counted 46.2: still the top score at its price.
  expect(cost.pick.point?.key).toBe("gamma@high");
  expect(cost.pick.row?.value_frontier).toBe(true);
  expect(cost.pick.row?.aa_index_margin).toBeCloseTo(1.8, 6);
  expect(cost.pick.aaEstimated).toBe(true);
  // Alpha at Medium scores under Gamma for more money: Gamma holds the top score there.
  expect(cost.runnerUp?.row?.value_frontier).toBe(false);
  expect(cost.runnerUp?.leader?.name).toBe("Gamma · High");
  expect(balanced.pick.row?.value_frontier).toBe(true);
  expect(quality.pick.row?.value_frontier).toBe(true);
  expect(quality.pick.leader).toBeNull();
  // The Score is read at the figures shown.
  expect(balanced.pick.score).not.toBeNull();
});

test("the settings beside the level are the dials at least one pick sets", () => {
  const view = engineLadder(
    DATA,
    answer([
      rec("cheap", { settings: { effort: "Low", thinking: "On", max_mode: "OFF", budget_priority: "cheap", rationale: "x", orchestration: "None" } }),
      rec("best", { settings: { effort: "Max", ultracode: "On", budget_priority: "best", rationale: "y" } }),
    ]),
  );
  // Max Mode is Off for every pick, so it is not a row; the level has its own row.
  expect(view.columns[0].settings).toEqual([
    { key: "thinking", label: "Thinking", value: "On" },
    { key: "ultracode", label: "Ultracode", value: "—" },
  ]);
  expect(view.columns[1].settings).toEqual([
    { key: "thinking", label: "Thinking", value: "—" },
    { key: "ultracode", label: "Ultracode", value: "On" },
  ]);
});

test("what a pick costs the viewer comes from the funded row, else the session estimate", () => {
  const funded = rec("cheap", { comparison_table: [{ platform_name: "Claude Code", your_cost: "✓ $0 · Claude Max", funded: true }] });
  expect(headlineCost(funded)).toEqual({ amount: "$0", source: "Claude Max", funded: true });
  expect(headlineCost(rec("cheap", { session_cost_estimate: { total_usd: 0.0123 } }))).toEqual({ amount: "$0.0123", source: "per session", funded: false });
  expect(headlineCost(rec("cheap"))).toBeNull();
  // Every pick at $0 on one plan: the trade-off is capability, and the note says which plan.
  expect(fundedZero(engineLadder(DATA, answer([funded, { ...funded, priority: "best" }])))).toEqual({ source: "Claude Max" });
  const mixed = rec("best", { comparison_table: [{ platform_name: "Codex", your_cost: "$0 · ChatGPT Pro", funded: true }] });
  expect(fundedZero(engineLadder(DATA, answer([funded, mixed])))).toEqual({ source: null });
  expect(fundedZero(engineLadder(DATA, answer([funded, rec("best", { session_cost_estimate: { total_usd: 0.02 } })])))).toBeNull();
});

test("ranks a page cannot use are read as none", () => {
  expect(parseRanks(null)).toBeNull();
  expect(parseRanks({})).toBeNull();
  expect(parseRanks({ pick: { model: "Alpha" } })).toBeNull();
  expect(parseRanks({ pick: { ...ranked("alpha", "Alpha"), model: "  " } })).toBeNull();
  const loose = parseRanks({ pick: { ...ranked("alpha", "Alpha"), aa_index: "50", price_measured: "yes" }, runner_up: "Beta", backup: undefined });
  expect(loose).toMatchObject({ pick: { model: "Alpha", aa_index: null, price_measured: null }, runner_up: null, backup: null });
});

test("what the task was read as", () => {
  expect(parseLadderTask({ category: "coding", complexity: "high", novel: false })).toEqual({ category: "coding", complexity: "high", novel: false });
  expect(parseLadderTask({ category: "long-context", complexity: "low" })).toEqual({ category: "long-context", complexity: "low", novel: false });
  for (const bad of [null, "coding/high", [], { category: "poetry", complexity: "high" }, { category: "coding", complexity: "extreme" }]) {
    expect(parseLadderTask(bad)).toBeNull();
  }
  expect(rankedFor({ category: "coding", complexity: "high", novel: false })).toBe("coding, high complexity");
  expect(rankedFor({ category: "planning", complexity: "high", novel: true })).toBe("planning, high complexity, a new kind of problem");
  // Novel raises the bar for high-complexity work only, so it is named only there.
  expect(rankedFor({ category: "speed", complexity: "low", novel: true })).toBe("speed, low complexity");
  expect([categoryLabel("long-context"), complexityLabel("medium")]).toEqual(["Long-context", "Medium"]);
});

test("a Quick pick reads the same way, quality first on the wire", () => {
  const rung = (priority: "quality" | "balanced" | "cost", model: string, id: string) => ({
    priority, model_id: id, model_name: model, platform_id: "codex-cli", platform_name: "Codex", effort: "High", specialist: priority === "quality", backup: null,
    ranks: { pick: ranked(id, model, { platform: "Codex", platform_id: "codex-cli" }), runner_up: ranked("beta", "Beta"), backup: null },
    terms: { quality: 80, requirement_shortfall: 0, cost: 2 },
    why: { quality: `${model} rates 80 of 100.`, requirement_shortfall: "It clears the bar.", cost: "It runs free of charge." },
  });
  const quick: KeylessResponse = {
    rungs: [rung("quality", "Beta", "beta"), rung("balanced", "Alpha", "alpha"), rung("cost", "Gamma", "gamma")],
    task: { category: "agentic", complexity: "medium", novel: false, budget_priority: "best" },
    points: [point("alpha", "high", 50, 4), point("beta", "high", 52, 5)],
    backup_warning: "No cross-provider backup.",
    engine: "scoring-core",
    cost_usd: 0,
  };
  const view = quickLadder(DATA, quick);
  expect(view.source).toBe("quick");
  expect(view.columns.map((c) => [c.priority, c.pick.model])).toEqual([["cheap", "Gamma"], ["balanced", "Alpha"], ["best", "Beta"]]);
  expect(view.primary).toBe("best");
  expect(view.primaryLabel).toBe("Your priority");
  expect(view.task).toEqual({ category: "agentic", complexity: "medium", novel: false });
  expect(view.backupWarning).toBe("No cross-provider backup.");
  expect(view.columns[2].specialist).toBe("agentic");
  expect(view.columns[0].specialist).toBeNull();
  // Its three sentences are the pick's reasoning; it carries no cost table.
  expect(view.columns[1].why.sections.map((s) => s.label)).toEqual(["Strength", "Fit to the task", "Cost"]);
  expect(view.columns[1].cost).toBeNull();
  expect(view.columns[1].pick.dial).toBe("Intelligence");
  expect(view.frontier.served).toBe(true);
});

test("the captured ranked answer reads as three ranked columns over its own frontier", () => {
  const models = getModelRows();
  const data = picksData(models, { fit: getScoreFit(models), snapshot: getBenchmarkMeta().generatedAt });
  const view = engineLadder(data, RANKED);
  expect(view.task).toEqual(RANKED.task);
  expect(view.columns).toHaveLength(3);
  expect(view.ranked).toBe(true);
  for (const column of view.columns) {
    const sent = RANKED.recommendations.find((r) => r.priority === column.priority)!.ranks!;
    for (const [option, wire] of [[column.pick, sent.pick], [column.runnerUp, sent.runner_up], [column.backup, sent.backup]] as const) {
      expect(option?.model).toBe(wire?.model);
      expect(option?.platform).toBe(wire?.platform);
      expect(option?.price).toBe(wire?.price_usd_per_1m);
      expect(option?.aa).toBe(wire?.aa_index);
      expect(option?.steppedDown).toBe(false);
    }
    // Three makers: no model twice in a column.
    expect(new Set([column.pick.model, column.runnerUp?.model, column.backup?.model]).size).toBe(3);
    expect(column.why.sections.map((s) => s.label)).toEqual(["The task", "Why this pick", "Why this effort"]);
    expect(column.cost?.funded).toBe(true);
  }
  expect(fundedZero(view)).toEqual({ source: null });
});

test("a saved run keeps what the ladder is drawn from", () => {
  // Saved entries keep named fields only (lib/saved-recommendations.ts): the
  // ranks, the task and the frontier's points must be among them.
  const saved = toSaved({ kind: "engine", id: "r1", at: 1, task: "refactor", data: RANKED });
  expect(saved).not.toBeNull();
  const data = saved!.data as MultiRecommendResponse;
  expect(data.task).toEqual(RANKED.task);
  expect(data.points).toEqual(RANKED.points);
  expect(data.recommendations.map((r) => r.ranks)).toEqual(RANKED.recommendations.map((r) => r.ranks));
  // And an older saved run, with none of them, still loads.
  const older = toSaved({ kind: "engine", id: "r0", at: 1, task: "refactor", data: LEGACY });
  expect(older).not.toBeNull();
  expect((older!.data as MultiRecommendResponse).points).toBeUndefined();
});
