// web/tests/models.spec.ts
//
// The /models catalog reference page (public): renders the full model table,
// the "how to read this" legend, sortable columns, the provider + jurisdiction
// filters, the ratings/benchmark-notes view toggle, the expanded row, and
// benchmark + provider-doc links.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import { scoresFor } from "../lib/benchmark-scores";

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
// Mirror the table's comparator exactly: price, then name ascending on a tie
// (ModelCatalog.tsx applies `localeCompare` WITHOUT the sort direction, so ties
// read A→Z in both directions). Sorting on price alone left ties to Array.sort's
// stability, which is catalog order — fine until 2026-09-05, when Fable 5.1
// landed at the same $50 output price as Fable 5 and the two models disagreed
// about which row comes first.
const byOutputPrice = [...catalog.models].sort(
  (a, b) =>
    a.output_price_per_1m - b.output_price_per_1m || a.name.localeCompare(b.name),
);
const CHEAPEST_MODEL = byOutputPrice[0].name;
const priciestPrice =
  byOutputPrice[byOutputPrice.length - 1].output_price_per_1m;
const PRICIEST_MODEL = byOutputPrice.find(
  (m) => m.output_price_per_1m === priciestPrice,
)!.name;

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

// --- The one composite number (AA Index) --------------------------------------

interface ScoredModel extends CatalogModel {
  headline_benchmarks?: string;
}
const scored = catalog.models as ScoredModel[];
// A row the cron prices with an AA Index, and one with no figure at all (the
// same extractor the page uses decides, so the pick follows the catalog).
const WITH_AA = scored.find((m) => /AA Intelligence Index \d/.test(m.headline_benchmarks ?? ""))!;
const WITHOUT_ANY = scored.find((m) => {
  const s = scoresFor(m.headline_benchmarks ?? "");
  return s.aaIndex === null && s.all.length === 0;
})!;
const AA_VALUE = /Intelligence Index (\d+(?:\.\d+)?)/.exec(WITH_AA.headline_benchmarks ?? "")![1];

test("the AA Index column shows the composite where measured and a dash where not", async ({ page }) => {
  await page.goto("/models");

  const withRow = page.getByTestId("model-row").filter({ hasText: WITH_AA.name }).first();
  await expect(withRow.getByTestId("aa-index")).toHaveText(AA_VALUE);
  const withoutRow = page.getByTestId("model-row").filter({ hasText: WITHOUT_ANY.name }).first();
  await expect(withoutRow.getByTestId("aa-index")).toHaveText("—");

  // Sortable: the header puts the highest index first.
  await page.getByRole("button", { name: /AA Index/ }).click();
  const values = scored
    .map((m) => /Intelligence Index (\d+(?:\.\d+)?)/.exec(m.headline_benchmarks ?? ""))
    .filter((m): m is RegExpExecArray => m !== null)
    .map((m) => Number(m[1]));
  const top = Math.max(...values);
  await expect(page.getByTestId("model-row").first().getByTestId("aa-index")).toHaveText(String(top));
});

test("rating cells are letters only; the expanded row carries the cited benchmarks", async ({ page }) => {
  await page.goto("/models");

  // A row citing Terminal-Bench 2.1: the letter cell shows no sub-figure, and
  // expanding the row reveals the figure, linkified to its source leaderboard.
  const tb = scored.find((m) => /Terminal-Bench 2\.1 (\d+(?:\.\d+)?)/.test(m.headline_benchmarks ?? ""))!;
  const tbScore = /Terminal-Bench 2\.1 (\d+(?:\.\d+)?)/.exec(tb.headline_benchmarks ?? "")![1];
  const row = page.getByTestId("model-row").filter({ hasText: tb.name }).first();
  await expect(row.getByTestId("cell-score")).toHaveCount(0);
  await expect(page.getByTestId("model-detail")).toHaveCount(0);

  await row.getByRole("button", { name: `Show details for ${tb.name}` }).click();
  const detail = page.getByTestId("model-detail");
  await expect(detail).toHaveCount(1);
  await expect(detail).toContainText("Benchmarks cited");
  // The benchmark name is a glossary link (its hidden tooltip sits between the
  // name and the figure in the DOM), so check the two halves separately.
  await expect(detail.locator('a[href="https://www.tbench.ai/"]')).toHaveCount(1);
  await expect(detail).toContainText(`2.1 ${tbScore}`);
  // Pricing detail moved out of the main table into the row.
  await expect(detail).toContainText("Cache read");
  await expect(detail).toContainText(/Cost tier/);
});

test("the cost tier is a dot beside the output price, not a column", async ({ page }) => {
  await page.goto("/models");

  const priciest = page.getByTestId("model-row").filter({ hasText: PRICIEST_MODEL }).first();
  await expect(priciest.getByTestId("cost-tier-dot")).toHaveAttribute("data-tier", "very-high");
  const cheapest = page.getByTestId("model-row").filter({ hasText: CHEAPEST_MODEL }).first();
  await expect(cheapest.getByTestId("cost-tier-dot")).toHaveAttribute("data-tier", "low");
});

test("the provider column and filter follow the model id", async ({ page }) => {
  await page.goto("/models");

  const fable = page.getByTestId("model-row").filter({ hasText: /Fable 5/ }).first();
  await expect(fable).toContainText("Anthropic");

  await page.getByLabel("Filter by provider").selectOption("Anthropic");
  const rows = page.getByTestId("model-row");
  const n = await rows.count();
  expect(n).toBeGreaterThan(0);
  for (let i = 0; i < n; i += 1) await expect(rows.nth(i)).toContainText("Anthropic");
});

test("the ratings view fits a 1280px viewport without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/models");

  const overflow = await page
    .getByTestId("model-catalog")
    .locator("table")
    .evaluate((t) => {
      const wrap = t.parentElement!;
      return wrap.scrollWidth - wrap.clientWidth;
    });
  expect(overflow).toBe(0);
});

test("sorting a category orders by letter, then AA Index", async ({ page }) => {
  await page.goto("/models");
  await page.getByRole("button", { name: /^Sort by Knowledge/ }).click();

  // Column order: chevron, model, provider, juris, input, output, AA index,
  // then the seven categories — knowledge is the sixth category.
  const KNOWLEDGE_TD = 7 + 5;
  const rows = page.getByTestId("model-row");
  const count = await rows.count();
  const seen: { rating: string; aa: number | null }[] = [];
  for (let i = 0; i < count; i += 1) {
    const r = rows.nth(i);
    const rating = (await r.locator("td").nth(KNOWLEDGE_TD).innerText()).trim();
    const aaText = (await r.getByTestId("aa-index").innerText()).trim();
    seen.push({ rating, aa: aaText === "—" ? null : Number(aaText) });
  }
  const order = "SABCD";
  for (let i = 1; i < seen.length; i += 1) {
    const prev = seen[i - 1];
    const cur = seen[i];
    expect(order.indexOf(cur.rating)).toBeGreaterThanOrEqual(order.indexOf(prev.rating));
    if (cur.rating !== prev.rating) continue;
    // Same letter: AA Index is non-increasing; rows without one sort last.
    if (prev.aa !== null && cur.aa !== null) {
      expect(cur.aa).toBeLessThanOrEqual(prev.aa);
    } else {
      expect(prev.aa === null && cur.aa !== null).toBe(false);
    }
  }
});
