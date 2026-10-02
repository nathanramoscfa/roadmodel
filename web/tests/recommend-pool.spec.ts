// web/tests/recommend-pool.spec.ts
//
// /recommend draws the cost/quality frontier over the models the viewer can
// run: the catalog access methods their saved plans cover or their enabled
// API providers sell per token, in a jurisdiction they allow (the service's
// accessible_model_ids, mirrored by lib/funding reachableModelIds), less the
// models the recommender sets aside too. Pure tests over the pool and the
// frontier it carries, then the page for a signed-in Claude Max holder.

import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

import catalog from "../data/catalog.json";
import { blendedPrice } from "../lib/benchmark-grid";
import { getModelRows } from "../lib/catalog-models";
import { reachableModelIds } from "../lib/funding";
import { picksData, viewerPool } from "../lib/recommend-picks";
import { fundedSurfacesForSubscription } from "../lib/subscriptions";
import { resetE2eState, signInViaCallback } from "./fixtures/onboarding-auth";

const ALL = ["us", "eu", "uk", "ca", "au", "jp", "kr", "cn"];
const methods = catalog.access_methods as { id: string; provider: string; billing: string; supports_models: string[] }[];
const offeredOn = (surfaces: readonly string[]) =>
  new Set(methods.filter((m) => surfaces.includes(m.id)).flatMap((m) => m.supports_models));

test("no saved plan and no API provider: no pool, as the service applies no filter", () => {
  expect(reachableModelIds([], [], ALL)).toBeNull();
});

test("a plan reaches exactly the models its surfaces offer", () => {
  const reach = reachableModelIds(["claude-max"], [], ALL)!;
  const offered = offeredOn(fundedSurfacesForSubscription("claude-max"));
  expect(reach.size).toBeGreaterThan(0);
  for (const id of reach) expect(offered.has(id)).toBe(true);
  expect(reach.has("claude-opus-5-5")).toBe(true);
  expect(reach.has("gpt-6-luna")).toBe(false);
});

test("an enabled API provider reaches its pay-per-token methods' models", () => {
  const reach = reachableModelIds([], ["openai"], ALL)!;
  const offered = new Set(
    methods
      .filter((m) => m.provider === "openai" && ["per-token", "subscription-or-key"].includes(m.billing))
      .flatMap((m) => m.supports_models),
  );
  expect(reach.has("gpt-6-luna")).toBe(true);
  for (const id of reach) expect(offered.has(id)).toBe(true);
});

test("a jurisdiction the viewer leaves out takes its models out of reach", () => {
  const juris = new Map(catalog.models.map((m) => [m.id, m.jurisdiction]));
  const withCn = reachableModelIds(["cursor-ultra"], [], ALL)!;
  const withoutCn = reachableModelIds(["cursor-ultra"], [], ALL.filter((j) => j !== "cn"))!;
  expect([...withCn].some((id) => juris.get(id) === "cn")).toBe(true);
  expect([...withoutCn].some((id) => juris.get(id) === "cn")).toBe(false);
});

test("the pool sets aside a superseded model while its successor is in reach, and a benched one", () => {
  const models = getModelRows();
  const reach = reachableModelIds(["claude-max"], [], ALL)!;
  const superseded = models.find((m) => m.superseded_by && reach.has(m.id) && reach.has(m.superseded_by));
  expect(superseded, "a superseded Claude model with its successor on the same plan").toBeTruthy();
  const pool = viewerPool(models, reach)!;
  expect(pool.has(superseded!.id)).toBe(false);
  expect(pool.has(superseded!.superseded_by!)).toBe(true);
  // Its successor benched, the superseded model stands in again.
  const benched = viewerPool(models, reach, [superseded!.superseded_by!])!;
  expect(benched.has(superseded!.superseded_by!)).toBe(false);
  expect(benched.has(superseded!.id)).toBe(true);
});

test("too few measured models for a frontier: no pool", () => {
  const models = getModelRows();
  const one = models.find((m) => m.aa_index !== null)!;
  expect(viewerPool(models, new Set([one.id]))).toBeNull();
});

test("the frontier is redrawn over the pool: every mark and every leader is a model the viewer can run", () => {
  const models = getModelRows();
  const pool = viewerPool(models, reachableModelIds(["claude-max", "chatgpt-pro"], [], ALL))!;
  const data = picksData(models, { pool });
  expect(data.pool).toEqual([...pool].sort());
  let onFrontier = 0;
  for (const row of Object.values(data.rows)) {
    if (!pool.has(row.id)) {
      expect(row.value_frontier, `${row.id} is outside the pool`).toBe(false);
      expect(row.value_beaten_by).toBeNull();
      continue;
    }
    if (row.aa_index === null) continue;
    if (row.value_frontier) {
      onFrontier += 1;
      continue;
    }
    const leader = data.rows[row.value_beaten_by!];
    expect(pool.has(leader.id), `${row.id} is beaten by ${leader.id}, a model in the pool`).toBe(true);
    expect(leader.aa_index!).toBeGreaterThanOrEqual(row.aa_index);
    expect(blendedPrice(leader.input_price_per_1m, leader.output_price_per_1m)).toBeLessThanOrEqual(
      blendedPrice(row.input_price_per_1m, row.output_price_per_1m),
    );
  }
  expect(onFrontier).toBeGreaterThanOrEqual(2);
});

test.describe("signed in with saved Settings", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await resetE2eState(page);
  });

  // A real /api/recommend answer whose Quality pick is Sonnet 5.5 on Claude
  // Code; its Cost and Balanced picks run on Google and OpenAI surfaces.
  const FIXTURE = readFileSync(path.join(__dirname, "fixtures", "recommend-response.json"), "utf8");

  test("the chart and the frontier marks are the viewer's own models", async ({ page }) => {
    await signInViaCallback(page);
    await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
    await page.getByRole("button", { name: /Save and continue/i }).click();
    await expect(page).toHaveURL("/");

    await page.route("**/api/recommend", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: FIXTURE }),
    );
    await page.goto("/recommend");
    await page.getByPlaceholder(/Describe the task/i).fill("Refactor a data pipeline into typed modules.");
    await page.getByRole("button", { name: /^Recommend/ }).click();

    const pool = viewerPool(getModelRows(), reachableModelIds(["claude-max"], [], ALL))!;
    await expect(page.getByTestId("picks-chart-scope")).toContainText("models you can use");
    const points = page.getByTestId("picks-chart-point");
    await expect(points.first()).toBeVisible();
    for (const id of await points.evaluateAll((els) => els.map((e) => e.getAttribute("data-model-id")))) {
      expect(pool.has(id!), `${id} is a model Claude Max reaches`).toBe(true);
    }
    // The rest of the catalog stays in the background, not as candidates.
    expect(await page.getByTestId("picks-chart-outside").count()).toBeGreaterThan(0);

    // Sonnet 5.5 is on the Claude Max frontier, and its card says so of the
    // viewer's models.
    const quality = page.locator('[data-priority="best"]');
    await expect(quality.getByTestId("pick-frontier")).toHaveText("your frontier");
    await page.locator('[data-pick="best"][data-row="__aa"]').getByTestId("pick-aa-index").hover();
    await expect(page.getByTestId("frontier-status")).toContainText("Across your models");
  });

  test("a category specialist off the frontier reads as the top model for its category", async ({ page }) => {
    await signInViaCallback(page);
    await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
    await page.getByRole("button", { name: /Save and continue/i }).click();
    await expect(page).toHaveURL("/");

    // Fable 5.1 costs more than Opus 5.5 and scores lower on the AA Index, so
    // the frontier would mark it beaten; as the multimodal specialist it is the
    // top model for that work.
    const body = JSON.parse(FIXTURE);
    const best = body.recommendations.find((r: { priority: string }) => r.priority === "best");
    Object.assign(best, {
      model: "Fable 5.1",
      platform: "Claude Code",
      specialist: true,
      specialist_category: "multimodal",
    });
    await page.route("**/api/recommend", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }),
    );
    await page.goto("/recommend");
    await page.getByPlaceholder(/Describe the task/i).fill("Read the chart in this screenshot.");
    await page.getByRole("button", { name: /^Recommend/ }).click();

    const quality = page.locator('[data-priority="best"]');
    await expect(quality.getByTestId("pick-specialist")).toHaveText("Top for multimodal work");
    await expect(quality.getByTestId("pick-beaten")).toHaveCount(0);
  });
});
