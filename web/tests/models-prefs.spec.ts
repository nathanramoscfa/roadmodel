// web/tests/models-prefs.spec.ts
//
// /models remembers the visitor's view: Provider, Jurisdiction, Cost tier,
// Group by and Ratings / Benchmark scores are saved in a cookie
// (lib/models-prefs) and applied by the SERVER on the next visit, so the
// page never opens on the default table and then jumps. A bad or stale
// cookie falls back to the defaults instead of breaking the page.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import {
  DEFAULT_PREFS,
  filtersFromPrefs,
  parsePrefs,
  PREFS_COOKIE,
  prefsFromFilters,
} from "../lib/models-prefs";

interface CatalogModel {
  id: string;
  jurisdiction: string;
  tier_cost: string;
}
const catalog = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "catalog.json"), "utf8"),
) as { models: CatalogModel[] };
const MODEL_COUNT = catalog.models.length;

test("the saved cookie is parsed field by field, never trusted", () => {
  expect(parsePrefs(undefined)).toEqual(DEFAULT_PREFS);
  expect(parsePrefs("not json")).toEqual(DEFAULT_PREFS);
  expect(parsePrefs("[1,2]")).toEqual(DEFAULT_PREFS);
  const good = { provider: "Anthropic", hideJurisdictions: ["cn"], cost: "high", grouping: "tier", view: "benchmarks" };
  expect(parsePrefs(JSON.stringify(good))).toEqual(good);
  // The browser's encoded form parses the same.
  expect(parsePrefs(encodeURIComponent(JSON.stringify(good)))).toEqual(good);
  // Each bad field falls back alone.
  expect(parsePrefs(JSON.stringify({ ...good, cost: "free", grouping: "price", view: 3, hideJurisdictions: "cn" }))).toEqual({
    ...good,
    cost: "all",
    grouping: "quality",
    view: "ratings",
    hideJurisdictions: [],
  });
  // A cookie from before Quality became the default carries `groupBy: "tier"`
  // whether or not the visitor chose it; it opens on Quality, the rest kept.
  const old = { provider: "Anthropic", hideJurisdictions: ["cn"], cost: "high", groupBy: "tier", view: "benchmarks" };
  expect(parsePrefs(JSON.stringify(old))).toEqual({ ...good, grouping: "quality" });
});

test("saved filters map onto today's catalog: a new jurisdiction starts checked, a gone provider falls back", () => {
  const prefs = { ...DEFAULT_PREFS, provider: "Gone Labs", hideJurisdictions: ["cn"], cost: "low" as const };
  const f = filtersFromPrefs(prefs, ["Anthropic", "OpenAI"], ["us", "eu", "cn", "uk"]);
  expect(f.provider).toBe("all");
  expect([...f.jurisdictions].sort()).toEqual(["eu", "uk", "us"]);
  expect(f.cost).toBe("low");
  expect(prefsFromFilters(f, ["us", "eu", "cn", "uk"])).toEqual({ provider: "all", hideJurisdictions: ["cn"], cost: "low" });
});

test("every choice survives a reload, and the server renders it before any script runs", async ({ page }) => {
  await page.goto("/models");
  const tier = "high";
  await page.getByTestId("jurisdiction-cn").uncheck();
  await page.getByLabel("Filter by provider").selectOption("OpenAI");
  await page.getByLabel("Filter by cost tier").selectOption(tier);
  await page.getByTestId("group-by-tier").click();
  await page.getByTestId("view-benchmarks").click();

  const expectRestored = async () => {
    await expect(page.getByTestId("jurisdiction-cn")).not.toBeChecked();
    await expect(page.getByTestId("jurisdiction-us")).toBeChecked();
    await expect(page.getByLabel("Filter by provider")).toHaveValue("OpenAI");
    await expect(page.getByLabel("Filter by cost tier")).toHaveValue(tier);
    await expect(page.getByTestId("group-by-tier")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("view-benchmarks")).toHaveAttribute("aria-pressed", "true");
    const rows = page.getByTestId("model-row");
    const n = await rows.count();
    for (let i = 0; i < n; i += 1) await expect(rows.nth(i)).toHaveAttribute("data-tier-cost", tier);
    await expect(page.getByTestId("score-charts-filter")).toContainText("OpenAI");
  };
  await expectRestored();
  await page.reload();
  await expectRestored();

  // The raw HTML already carries the saved view: nothing waits for hydration.
  const html = await (await page.request.get("/models")).text();
  expect(html).toMatch(/data-testid="group-by-tier"[^>]*aria-pressed="true"/);
  expect(html).toMatch(/data-testid="view-benchmarks"[^>]*aria-pressed="true"/);
  const box = (code: string) => html.match(new RegExp(`<input[^>]*data-testid="jurisdiction-${code}"[^>]*>`))?.[0] ?? "";
  expect(box("us")).toContain("checked");
  expect(box("cn")).not.toBe("");
  expect(box("cn")).not.toContain("checked");

  // Clearing the filters is remembered too; Group by and view stay as chosen.
  await page.getByTestId("clear-filters").click();
  await page.reload();
  await expect(page.getByTestId("jurisdiction-cn")).toBeChecked();
  await expect(page.getByLabel("Filter by provider")).toHaveValue("all");
  await expect(page.getByTestId("model-row")).toHaveCount(MODEL_COUNT);
  await expect(page.getByTestId("group-by-tier")).toHaveAttribute("aria-pressed", "true");
});

test("a malformed cookie opens the default page", async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: PREFS_COOKIE, value: "%7Bbroken", url: `${baseURL}/models` }]);
  await page.goto("/models");
  await expect(page.getByTestId("model-row")).toHaveCount(MODEL_COUNT);
  await expect(page.getByTestId("group-by-quality")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("view-ratings")).toHaveAttribute("aria-pressed", "true");
});
