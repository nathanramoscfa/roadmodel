// web/tests/models.spec.ts
//
// The /models catalog reference page (public): renders the full model table,
// the "how to read this" legend, sortable columns, the jurisdiction filter, the
// ratings/benchmarks view toggle, and benchmark + provider-doc links.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

// Expected row counts are DERIVED from the catalog the page renders, never
// hardcoded. The catalog grows whenever the daily refresh cron picks up a new
// upstream model, and a hardcoded count turns every one of those cron PRs red
// — which is what stranded the catalog-refresh PRs from #392 onward. Reading
// the same JSON the page imports keeps this a rendering test (does every
// catalog model reach the table?) instead of a snapshot of a moving number.
//
// `data/catalog.json` is the build-time copy of docs/catalog.json that
// web/scripts/sync-catalog.mjs writes; the `pretest` npm hook refreshes it
// before Playwright starts, so it always matches the server under test.
interface CatalogModel {
  jurisdiction?: string;
  name: string;
  output_price_per_1m: number;
}
const catalog = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "catalog.json"), "utf8"),
) as { models: CatalogModel[] };

const MODEL_COUNT = catalog.models.length;
const CN_MODEL_COUNT = catalog.models.filter((m) => m.jurisdiction === "cn").length;
const byOutputPrice = [...catalog.models].sort(
  (a, b) => a.output_price_per_1m - b.output_price_per_1m,
);
const CHEAPEST_MODEL = byOutputPrice[0].name;
const PRICIEST_MODEL = byOutputPrice[byOutputPrice.length - 1].name;

test("renders the catalog table, legend, and model links", async ({ page }) => {
  await page.goto("/models");

  await expect(page.getByRole("heading", { name: "Model catalog" })).toBeVisible();
  await expect(page.getByText("How to read this table")).toBeVisible();
  await expect(page.getByTestId("model-catalog")).toBeVisible();

  // Every catalog model renders as a row.
  await expect(page.getByTestId("model-row")).toHaveCount(MODEL_COUNT);

  // Model names link to their provider's docs in a new tab.
  const fable = page.getByRole("link", { name: /^Fable 5$/ });
  await expect(fable).toHaveAttribute("href", /docs\.claude\.com/);
  await expect(fable).toHaveAttribute("target", "_blank");
});

test("default sort is output price descending; the header toggles ascending", async ({ page }) => {
  await page.goto("/models");

  // Highest output price first.
  await expect(page.getByTestId("model-row").first()).toContainText(PRICIEST_MODEL);

  await page.getByRole("button", { name: /Output/ }).click();
  // Cheapest output first.
  await expect(page.getByTestId("model-row").first()).toContainText(CHEAPEST_MODEL);
});

test("the jurisdiction filter narrows the rows", async ({ page }) => {
  await page.goto("/models");

  await page.getByLabel("Filter by jurisdiction").selectOption("cn");
  // Exactly the catalog's cn-jurisdiction models (DeepSeek, GLM, Kimi) — the
  // count follows the catalog rather than pinning today's lineup.
  await expect(page.getByTestId("model-row")).toHaveCount(CN_MODEL_COUNT);
  await expect(page.getByText("No models match")).toHaveCount(0);
});

test("the benchmark view linkifies scores to their source leaderboards", async ({ page }) => {
  await page.goto("/models");

  await page.getByTestId("view-benchmarks").click();
  // "AA Intelligence Index" (cited by many models) becomes a link to its source.
  const aa = page.locator('a[href="https://artificialanalysis.ai/"]').first();
  await expect(aa).toBeVisible();
  await expect(aa).toHaveAttribute("target", "_blank");
});
