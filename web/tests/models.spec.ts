// web/tests/models.spec.ts
//
// The /models catalog reference page (public): renders the full model table,
// the "how to read this" legend, sortable columns, the provider + jurisdiction
// filters, the ratings/benchmark-scores view toggle, the uniform Artificial
// Analysis figures (under the letters and as the full grid), the expanded row,
// and benchmark + provider-doc links.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import { scoresFor } from "../lib/benchmark-scores";
import {
  bandFor,
  blendedPrice,
  fitScoreModel,
  formatBench,
  formatScore,
  GRID_COLUMNS,
  paretoFrontier,
  scoreFor,
} from "../lib/benchmark-grid";

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
  id: string;
  jurisdiction?: string;
  name: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  tier_cost: string;
}
const catalog = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "catalog.json"), "utf8"),
) as { models: CatalogModel[] };

const MODEL_COUNT = catalog.models.length;

// The structured benchmark layer the grid reads (data/benchmarks.json is the
// synced copy of docs/benchmarks.json, like the catalog).
interface BenchModel {
  aa_name: string;
  evaluations: Record<string, number | null>;
  median_output_tokens_per_second: number | null;
}
const benchmarks = JSON.parse(
  readFileSync(path.join(process.cwd(), "data", "benchmarks.json"), "utf8"),
) as { models: Record<string, BenchModel> };
const MEASURED_COUNT = catalog.models.filter((m) => benchmarks.models[m.id]).length;

// --- The one composite number (AA Index) --------------------------------------

interface ScoredModel extends CatalogModel {
  headline_benchmarks?: string;
}
const scored = catalog.models as ScoredModel[];
// The AA Index column reads the structured layer first and falls back to the
// cron's prose citation, so mirror that here to derive the expected values.
function aaIndexFor(m: ScoredModel): number | null {
  const structured = benchmarks.models[m.id]?.evaluations.artificial_analysis_intelligence_index;
  if (typeof structured === "number") return structured;
  return scoresFor(m.headline_benchmarks ?? "").aaIndex;
}

const WITH_AA = scored.find((m) => aaIndexFor(m) !== null)!;
// An Anthropic model from today's catalog, for tests that need one by maker.
const ANTHROPIC_MODEL = catalog.models.find((m) => /^(claude-|opus-|sonnet-|haiku-)/.test(m.id))!;
const WITHOUT_ANY = scored.find((m) => aaIndexFor(m) === null)!;
const AA_VALUE = String(aaIndexFor(WITH_AA));

// The frontier, computed independently of the page: every measured model at
// its blended price, and its leader — the highest AA Index at its price or
// less, the cheapest of those on a tie, catalog order last. A model that is
// its own leader is on the frontier.
interface Measured {
  m: ScoredModel;
  price: number;
  index: number;
}
const MEASURED: Measured[] = scored
  .map((m) => ({ m, price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m), index: aaIndexFor(m) }))
  .filter((r): r is Measured => r.index !== null);
function leaderOf(r: Measured): Measured {
  const pool = MEASURED.filter((o) => o.price <= r.price);
  const top = Math.max(...pool.map((o) => o.index));
  const tied = pool.filter((o) => o.index === top);
  const cheapest = Math.min(...tied.map((o) => o.price));
  return tied.find((o) => o.price === cheapest)!;
}


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

  // Model names link to their provider's docs in a new tab. Any Anthropic
  // model the catalog carries today (models retire as newer ones supersede them).
  const claude = page
    .locator(`[data-testid="model-row"][data-model-id="${ANTHROPIC_MODEL.id}"]`)
    .getByRole("link", { name: ANTHROPIC_MODEL.name, exact: true });
  await expect(claude).toHaveAttribute("href", /docs\.claude\.com/);
  await expect(claude).toHaveAttribute("target", "_blank");
});

test("the page leads with the table, then the Score charts, the frontier chart, then the full key", async ({ page }) => {
  await page.goto("/models");
  const top = async (loc: ReturnType<typeof page.locator>) => (await loc.boundingBox())!.y;
  const table = await top(page.getByTestId("model-catalog"));
  const charts = await top(page.getByTestId("score-charts"));
  const frontierPanel = await top(page.getByTestId("frontier-panel"));
  const legend = await top(page.getByTestId("catalog-legend"));
  const reference = await top(page.locator("#benchmarks"));
  expect(table).toBeLessThan(charts);
  expect(charts).toBeLessThan(frontierPanel);
  expect(frontierPanel).toBeLessThan(legend);
  expect(legend).toBeLessThan(reference);
  // The table's caption points down to the key, and the key above the table
  // defines the two things readers trip on.
  await expect(page.getByTestId("model-catalog").locator('a[href="#how-to-read"]')).toHaveCount(1);
  await expect(page.getByTestId("catalog-legend")).toHaveAttribute("id", "how-to-read");
  await expect(page.getByTestId("table-key")).toContainText(
    "Cost/quality frontier: the top score at every price.",
  );
  await expect(page.getByTestId("table-key")).toContainText("Blended price = (3 × input + 1 × output) ÷ 4.");
});

test("default sort is Score, grouped by cost tier (priciest first); Output toggles to cheapest-first", async ({ page }) => {
  await page.goto("/models");

  // Default = Score: the table opens grouped, one header row per cost tier,
  // priciest tier first, so a cheap model's high score cannot read as
  // "better than the frontier model" three rows above it.
  const tiersPresent = new Set(scored.map((m) => m.tier_cost));
  await expect(page.getByTestId("score-group")).toHaveCount(tiersPresent.size);
  const groupOrder = await page
    .getByTestId("score-group")
    .evaluateAll((rows) => rows.map((r) => r.getAttribute("data-tier")));
  const rank: Record<string, number> = { low: 1, medium: 2, high: 3, "very-high": 4 };
  for (let i = 1; i < groupOrder.length; i += 1) {
    expect(rank[groupOrder[i - 1]!]).toBeGreaterThan(rank[groupOrder[i]!]);
  }
  // Each header prices its rows on both scales: output (which sets the tier,
  // and matches the Output column) and blended (which the Score is fitted on).
  const money = (v: number, digits: number) => `$${Number(v.toFixed(digits)).toString()}`;
  for (const tier of tiersPresent) {
    const inTier = scored.filter((m) => m.tier_cost === tier);
    const outs = inTier.map((m) => m.output_price_per_1m);
    const blends = inTier.map((m) => blendedPrice(m.input_price_per_1m, m.output_price_per_1m));
    const range = (vals: number[], digits: number) => {
      const lo = money(Math.min(...vals), digits);
      const hi = money(Math.max(...vals), digits);
      return lo === hi ? lo : `${lo}–${hi}`;
    };
    const header = page.locator(`[data-testid="score-group"][data-tier="${tier}"]`);
    await expect(header.getByTestId("score-group-prices")).toContainText(`output ${range(outs, 4)}`);
    await expect(header.getByTestId("score-group-prices")).toContainText(`blended ${range(blends, 2)}`);
  }
  // Sorting by AA Index still puts the highest-index model on top, unmeasured last.
  await page.getByRole("button", { name: /^AA Index/ }).click();
  const top = [...scored].filter((m) => aaIndexFor(m) !== null).sort((a, b) => aaIndexFor(b)! - aaIndexFor(a)!)[0];
  await expect(page.getByTestId("model-row").first()).toContainText(top.name);
  await expect(page.getByTestId("model-row").last().getByTestId("aa-index")).toHaveText("—");

  await page.getByRole("button", { name: /Output/ }).click();
  await expect(page.getByTestId("model-row").first()).toContainText(PRICIEST_MODEL);
  await page.getByRole("button", { name: /Output/ }).click();
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

test("the benchmark-scores view is a uniform grid: one AA column per evaluation", async ({ page }) => {
  await page.goto("/models");
  await page.getByTestId("view-benchmarks").click();

  // Every grid column (minus the Intelligence Index, which keeps its own AA
  // Index column) renders for every row, on its own scale.
  const bodyCols = GRID_COLUMNS.filter((c) => c.key !== "artificial_analysis_intelligence_index");
  await expect(page.getByTestId("model-row")).toHaveCount(MODEL_COUNT);
  await expect(page.getByTestId("bench-cell")).toHaveCount(MODEL_COUNT * bodyCols.length);
  await expect(page.getByText(`${MEASURED_COUNT} measured by Artificial Analysis`)).toBeVisible();

  // A measured model shows the API's value formatted on the column's scale;
  // an unmeasured model shows a dash in every column.
  const measuredId = catalog.models.find((m) => benchmarks.models[m.id]?.evaluations.hle !== null && benchmarks.models[m.id])!;
  const hle = benchmarks.models[measuredId.id].evaluations.hle!;
  const row = page.getByTestId("model-row").filter({ hasText: measuredId.name }).first();
  await expect(row.locator('[data-bench="hle"]')).toHaveText(formatBench(hle, "fraction"));
  const unmeasured = catalog.models.find((m) => !benchmarks.models[m.id]);
  if (unmeasured) {
    const bare = page.getByTestId("model-row").filter({ hasText: unmeasured.name }).first();
    for (const c of bodyCols) await expect(bare.locator(`[data-bench="${c.key}"]`)).toHaveText("—");
  }

  // Every measured cell is tinted by its within-column quintile, computed over
  // the whole catalog with the same helper the page uses.
  const hleSorted = Object.values(benchmarks.models)
    .map((m) => m.evaluations.hle)
    .filter((v): v is number => typeof v === "number")
    .sort((a, b) => a - b);
  await expect(row.locator('[data-bench="hle"]')).toHaveAttribute("data-band", String(bandFor(hle, hleSorted)));
  const bestHle = catalog.models.find((m) => benchmarks.models[m.id]?.evaluations.hle === hleSorted[hleSorted.length - 1])!;
  await expect(
    page.getByTestId("model-row").filter({ hasText: bestHle.name }).first().locator('[data-bench="hle"]'),
  ).toHaveAttribute("data-band", "5");

  // Headers link to the source and are sortable; sorting Coding Index puts the
  // top value first and rows without one last.
  await page.getByRole("button", { name: "Sort by Artificial Analysis Coding Index" }).click();
  const values = Object.values(benchmarks.models)
    .map((m) => m.evaluations.artificial_analysis_coding_index)
    .filter((v): v is number => typeof v === "number");
  const top = Math.max(...values);
  await expect(
    page.getByTestId("model-row").first().locator('[data-bench="artificial_analysis_coding_index"]'),
  ).toHaveText(formatBench(top, "index"));
  await expect(page.getByTestId("model-row").last().locator('[data-bench="artificial_analysis_coding_index"]')).toHaveText("—");

  // The grid fits the same 1280px budget as the ratings view.
  await page.setViewportSize({ width: 1280, height: 900 });
  const overflow = await page
    .getByTestId("model-catalog")
    .locator("table")
    .evaluate((t) => t.parentElement!.scrollWidth - t.parentElement!.clientWidth);
  expect(overflow).toBe(0);
});

test("rating cells are letters only; the Score column is the cost-adjusted score, grouped by cost tier", async ({ page }) => {
  await page.goto("/models");

  await expect(page.getByTestId("cell-figure")).toHaveCount(0);

  // Frontier = no catalog model, in any cost tier, is both cheaper and higher
  // on the AA Index, priced blended like the Score; recompute from the same
  // inputs and compare row by row. The ring sits beside the AA Index, never on
  // the within-tier Score.
  const inputs = scored.map((m) => ({
    m,
    price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m),
    index: aaIndexFor(m),
  }));
  const frontier = new Set([...paretoFrontier(inputs)].map((r) => r.m.id));
  expect(frontier.size).toBeGreaterThan(2);
  await expect(page.locator('[data-testid="aa-index"][data-frontier="1"]')).toHaveCount(frontier.size);
  await expect(page.getByTestId("frontier-mark")).toHaveCount(frontier.size);
  for (const id of frontier) {
    await expect(
      page.locator(`[data-testid="model-row"][data-model-id="${id}"] [data-testid="frontier-mark"]`),
    ).toHaveCount(1);
  }
  await expect(page.locator('[data-testid="value-cell"] [data-testid="frontier-mark"]')).toHaveCount(0);
  const cheapestMeasured = [...inputs].filter((r) => r.index !== null).sort((a, b) => a.price - b.price || b.index! - a.index!)[0];
  expect(frontier.has(cheapestMeasured.m.id)).toBe(true);

  // The score = AA Index minus the market fit (index ~ α_tier + b·log10 blended
  // price, one pooled slope, one intercept per cost tier) over every measured
  // model. Recompute from the same inputs and compare every rendered figure.
  const fitInputs = scored.map((m) => ({
    price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m),
    index: aaIndexFor(m),
    tier: m.tier_cost,
  }));
  const fit = fitScoreModel(fitInputs);
  expect(fit).not.toBeNull();
  expect(fit!.n).toBeGreaterThan(10);
  expect(fit!.slope).toBeGreaterThan(0); // pricier models do score higher, on average
  expect(fit!.sigma).toBeGreaterThan(0);
  const scoreOf = (m: ScoredModel) =>
    scoreFor(fit, m.tier_cost, blendedPrice(m.input_price_per_1m, m.output_price_per_1m), aaIndexFor(m));
  for (const m of scored) {
    // Match on the id: a name filter for "Fable 5" would also hit "Fable 5.1".
    const row = page.locator(`[data-testid="model-row"][data-model-id="${m.id}"]`);
    const sc = scoreOf(m);
    await expect(row.getByTestId("value-cell")).toContainText(sc === null ? "—" : formatScore(sc));
  }
  // Least-squares residuals sum to ~0 WITHIN EVERY TIER: each tier is centred
  // on its own peers, not a ratio that crowns the cheapest model overall.
  for (const tier of Object.keys(fit!.tiers)) {
    const residuals = scored.filter((m) => m.tier_cost === tier).map(scoreOf).filter((v): v is number => v !== null);
    expect(residuals.length).toBe(fit!.tiers[tier].n);
    const mean = residuals.reduce((a, b) => a + b, 0) / residuals.length;
    expect(Math.abs(mean)).toBeLessThan(1e-6);
  }

  // The header tooltips carry live statistics, never a typed-in figure: the
  // Score fit it just computed, and the AA snapshot the page just read.
  await expect(
    page.locator('[role="tooltip"]').filter({ hasText: `Fit over ${fit!.n} measured models` }),
  ).toHaveCount(1);
  await expect(
    page
      .locator('[role="tooltip"]')
      .filter({ hasText: `${MEASURED_COUNT} of ${MODEL_COUNT} catalog models measured` }),
  ).toHaveCount(1);

  // Score is the default sort: groups by cost tier (priciest first), one header
  // row per tier present, ordered by score inside each tier, unmeasured last.
  const tiersPresent = new Set(scored.map((m) => m.tier_cost));
  await expect(page.getByTestId("score-group")).toHaveCount(tiersPresent.size);
  const groupOrder = await page.getByTestId("score-group").evaluateAll((rows) => rows.map((r) => r.getAttribute("data-tier")));
  const rank: Record<string, number> = { low: 1, medium: 2, high: 3, "very-high": 4 };
  for (let i = 1; i < groupOrder.length; i += 1) expect(rank[groupOrder[i - 1]!]).toBeGreaterThan(rank[groupOrder[i]!]);
  const cells = await page.getByTestId("model-row").evaluateAll((rows) =>
    rows.map((r) => ({
      tier: r.getAttribute("data-tier-cost") ?? "",
      value: r.querySelector('[data-testid="value-cell"]')?.getAttribute("data-value") ?? "",
    })),
  );
  let measuredSeen = 0;
  for (const tier of groupOrder) {
    const group = cells.filter((c) => c.tier === tier);
    const measured = group.filter((c) => c.value !== "").map((c) => Number(c.value));
    measuredSeen += measured.length;
    for (let i = 1; i < measured.length; i += 1) expect(measured[i - 1]).toBeGreaterThanOrEqual(measured[i]);
    // Unmeasured rows trail their tier's measured rows.
    const firstBlank = group.findIndex((c) => c.value === "");
    if (firstBlank !== -1) expect(group.slice(firstBlank).every((c) => c.value === "")).toBe(true);
  }
  expect(measuredSeen).toBe(fit!.n);
});

test("derived letters match the published bands; unmeasured letters are marked editorial", async ({ page }) => {
  await page.goto("/models");

  // Column order: chevron, model, provider, juris, input, output, AA index,
  // value, then coding, planning, agentic, multimodal, long-context, knowledge, speed.
  const CODING_TD = 8;
  const KNOWLEDGE_TD = 8 + 5;
  const hleAll = Object.values(benchmarks.models)
    .map((m) => m.evaluations.hle)
    .filter((v): v is number => typeof v === "number");
  const leader = Math.max(...hleAll) * 100;
  const band = (gap: number) => (gap <= 5 ? "S" : gap <= 20 ? "A" : gap <= 35 ? "B" : gap <= 50 ? "C" : "D");

  const rows = page.getByTestId("model-row");
  const n = await rows.count();
  let derivedSeen = 0;
  let editorialSeen = 0;
  for (let i = 0; i < n; i += 1) {
    const r = rows.nth(i);
    // The row's id, not the name cell's text (which can carry a superseded tag).
    const id = await r.getAttribute("data-model-id");
    const model = catalog.models.find((m) => m.id === id)!;
    const hle = benchmarks.models[model.id]?.evaluations.hle;
    const cell = r.locator("td").nth(KNOWLEDGE_TD).getByTestId("rating-cell");
    if (typeof hle === "number") {
      await expect(cell).toHaveAttribute("data-basis", "derived");
      await expect(cell).toHaveText(band(leader - hle * 100));
      await expect(cell).toHaveAttribute("title", /Derived from Humanity's Last Exam .* points behind the category leader/);
      derivedSeen += 1;
    } else {
      await expect(cell).toHaveAttribute("data-basis", "editorial");
      await expect(cell).toHaveAttribute("title", /Editorial rating\./);
      editorialSeen += 1;
    }
    // Planning is never derived.
    await expect(r.locator("td").nth(CODING_TD + 1).getByTestId("rating-cell")).toHaveAttribute("data-basis", "editorial");
  }
  // Every measured model's letter is derived: as many as the catalog measures
  // on HLE (the count moves as models arrive and retire).
  const measuredOnHle = catalog.models.filter(
    (m) => typeof benchmarks.models[m.id]?.evaluations.hle === "number",
  ).length;
  expect(derivedSeen).toBe(measuredOnHle);
  expect(derivedSeen).toBeGreaterThan(0);
  expect(editorialSeen).toBeGreaterThan(0);
});

test("every model off the frontier names the model that beats it, from any cost tier", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/models");

  const measured = MEASURED;
  let offFrontier = 0;
  let crossTier = 0;
  for (const r of measured) {
    const lead = leaderOf(r);
    const cell = page.locator(`[data-testid="model-row"][data-model-id="${r.m.id}"] [data-testid="aa-index"]`);
    await expect(cell).toHaveAttribute("data-beaten-by", lead === r ? "" : lead.m.id);
    if (lead !== r) {
      offFrontier += 1;
      expect(lead.price).toBeLessThanOrEqual(r.price);
      expect(lead.index).toBeGreaterThanOrEqual(r.index);
      if (lead.m.tier_cost !== r.m.tier_cost) crossTier += 1;
    }
  }
  expect(offFrontier).toBeGreaterThan(0);

  // The case that reads as a contradiction without this: the best Score in the
  // table that has no dot. Its AA Index card and its Score card both name the
  // model that beats it; a frontier model's cards say it is on the frontier.
  const fit = fitScoreModel(measured.map((o) => ({ price: o.price, index: o.index, tier: o.m.tier_cost })));
  const scoreOf = (o: (typeof measured)[number]) => scoreFor(fit, o.m.tier_cost, o.price, o.index) ?? -Infinity;
  const beaten = measured.filter((r) => leaderOf(r) !== r).sort((a, b) => scoreOf(b) - scoreOf(a))[0];
  const lead = leaderOf(beaten);
  const row = page.locator(`[data-testid="model-row"][data-model-id="${beaten.m.id}"]`);
  await row.getByTestId("aa-index-trigger").hover();
  const indexCard = page.getByTestId("aa-index-card");
  await expect(indexCard).toContainText(beaten.m.name);
  await expect(indexCard.getByTestId("frontier-status")).toHaveAttribute("data-beaten-by", lead.m.id);
  await expect(indexCard.getByTestId("frontier-status")).toContainText(
    `Top score at this price or less: ${lead.m.name}`,
  );
  await page.mouse.move(2, 2);
  await expect(indexCard).toHaveCount(0);
  await row.getByTestId("score-trigger").hover();
  await expect(page.getByTestId("score-card").getByTestId("frontier-status")).toContainText(lead.m.name);
  await page.mouse.move(2, 2);

  const onFrontier = measured.find((r) => leaderOf(r) === r)!;
  await page
    .locator(`[data-testid="model-row"][data-model-id="${onFrontier.m.id}"]`)
    .getByTestId("aa-index-trigger")
    .hover();
  await expect(page.getByTestId("aa-index-card").getByTestId("frontier-status")).toContainText(
    "On the cost/quality frontier.",
  );
  // Recorded, not asserted: whether today's leaders cross tiers is data.
  test.info().annotations.push({ type: "cross-tier leaders", description: String(crossTier) });
});

test("Group by Quality bands the table by AA Index, cheapest first; Cost tier puts the tiers back", async ({ page }) => {
  await page.goto("/models");
  // Cost tier is the default grouping, and the caption says what it answers.
  await expect(page.getByTestId("group-by-tier")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("grouping-note")).toContainText("the best buy at your budget");

  await page.getByTestId("group-by-quality").click();
  await expect(page.getByTestId("group-by-quality")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("grouping-note")).toContainText("the cheapest way to each level");
  await expect(page.getByTestId("score-group")).toHaveCount(0);

  // Ten-point bands, best first, an unmeasured group last; within a band the
  // cheapest (blended) model first, the higher index breaking a price tie.
  const bandOf = (v: number | null) => (v === null ? null : Math.floor(v / 10) * 10);
  const rowsIn = scored.map((m) => ({
    m,
    band: bandOf(aaIndexFor(m)),
    price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m),
    index: aaIndexFor(m),
  }));
  const bands = [...new Set(rowsIn.map((r) => r.band).filter((b): b is number => b !== null))].sort((a, b) => b - a);
  const groups = await page.getByTestId("quality-group").evaluateAll((els) => els.map((e) => e.getAttribute("data-band")));
  expect(groups).toEqual([...bands.map(String), ...(rowsIn.some((r) => r.band === null) ? ["none"] : [])]);
  const expected = [...rowsIn]
    .sort((a, b) => {
      if (a.band !== b.band) return a.band === null ? 1 : b.band === null ? -1 : b.band - a.band;
      if (a.price !== b.price) return a.price - b.price;
      if (a.index !== b.index) return (b.index ?? -1) - (a.index ?? -1);
      return a.m.name.localeCompare(b.m.name);
    })
    .map((r) => r.m.id);
  const actual = await page.getByTestId("model-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-model-id")));
  expect(actual).toEqual(expected);
  const top = page.locator(`[data-testid="quality-group"][data-band="${bands[0]}"]`);
  await expect(top).toContainText(`AA Index ${bands[0]}–${(bands[0] + 9.9).toFixed(1)}`);
  await expect(top.getByTestId("quality-group-prices")).toContainText("cheapest first");

  await page.getByTestId("group-by-tier").click();
  await expect(page.getByTestId("quality-group")).toHaveCount(0);
  await expect(page.getByTestId("score-group")).toHaveCount(new Set(scored.map((m) => m.tier_cost)).size);
});

test("a group with nothing on the frontier says so in its header and its chart, naming what beats it", async ({ page }) => {
  await page.goto("/models");
  const frontier = new Set(MEASURED.filter((r) => leaderOf(r) === r).map((r) => r.m.id));
  const check = async (header: ReturnType<typeof page.locator>, members: Measured[]) => {
    const beaten = members.length > 0 && members.every((r) => !frontier.has(r.m.id));
    await expect(header.getByTestId("group-beaten")).toHaveCount(beaten ? 1 : 0);
    if (!beaten) return false;
    // The most frequent leader is named (a tie for most frequent may name
    // either); a single leader for the whole group names the count too.
    const counts = new Map<string, number>();
    for (const r of members) counts.set(leaderOf(r).m.name, (counts.get(leaderOf(r).m.name) ?? 0) + 1);
    const most = Math.max(...counts.values());
    const tops = [...counts.keys()].filter((name) => counts.get(name) === most);
    const note = header.getByTestId("group-beaten");
    await expect(note).toContainText(counts.size === 1 ? "The top score at th" : "The top scores at these prices or less are");
    const text = await note.innerText();
    expect(tops.some((name) => text.includes(name))).toBe(true);
    if (counts.size === 1 && members.length > 1) {
      await expect(note).toContainText(`The top score at these prices or less is ${tops[0]}`);
      await expect(note).toContainText(`all ${members.length} models here`);
    }
    return true;
  };

  // Cost tiers (the default grouping) and their charts.
  let beatenTiers = 0;
  for (const tier of new Set(scored.map((m) => m.tier_cost))) {
    const members = MEASURED.filter((r) => r.m.tier_cost === tier);
    const header = page.locator(`[data-testid="score-group"][data-tier="${tier}"]`);
    if (await check(header, members)) beatenTiers += 1;
    if (members.length >= 2) {
      const chart = page.locator(`[data-testid="score-chart"][data-tier="${tier}"]`);
      const beaten = members.every((r) => !frontier.has(r.m.id));
      await expect(chart.getByTestId("chart-beaten")).toHaveCount(beaten ? 1 : 0);
    }
  }
  test.info().annotations.push({ type: "tiers with nothing on the frontier", description: String(beatenTiers) });

  // Quality bands.
  await page.getByTestId("group-by-quality").click();
  const bandOf = (v: number) => Math.floor(v / 10) * 10;
  for (const band of new Set(MEASURED.map((r) => bandOf(r.index)))) {
    const header = page.locator(`[data-testid="quality-group"][data-band="${band}"]`);
    await check(header, MEASURED.filter((r) => bandOf(r.index) === band));
  }
});

test("the frontier chart plots every measured model and joins the frontier with a step line", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/models");
  const panel = page.getByTestId("frontier-panel");
  await expect(panel).toBeVisible();

  // Every measured model is a dot; the green ones are exactly the frontier.
  await expect(panel.getByTestId("frontier-chart-point")).toHaveCount(MEASURED.length);
  const onFrontier = MEASURED.filter((r) => leaderOf(r) === r).sort((a, b) => a.price - b.price);
  await expect(panel.locator('[data-testid="frontier-chart-point"][data-frontier="1"]')).toHaveCount(onFrontier.length);
  for (const r of onFrontier) {
    await expect(panel.locator(`[data-testid="frontier-chart-point"][data-model-id="${r.m.id}"]`)).toHaveAttribute(
      "data-frontier",
      "1",
    );
  }
  // The line joins them cheapest to priciest, each one scoring higher than the last.
  await expect(panel.getByTestId("frontier-line")).toHaveAttribute(
    "data-frontier-ids",
    onFrontier.map((r) => r.m.id).join(","),
  );
  for (let i = 1; i < onFrontier.length; i += 1) {
    expect(onFrontier[i].index).toBeGreaterThan(onFrontier[i - 1].index);
  }
  // One grey Score line per cost tier the fit covers.
  await expect(panel.getByTestId("frontier-tier-line")).toHaveCount(
    new Set(MEASURED.map((r) => r.m.tier_cost)).size,
  );
  await expect(panel).toContainText(`That keeps ${onFrontier.length} of the ${MEASURED.length} models plotted.`);

  // Dot centres on screen, to hover only where nothing else sits.
  await panel.getByTestId("frontier-chart").scrollIntoViewIfNeeded();
  const centres = await panel.getByTestId("frontier-chart-point").evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.getAttribute("data-model-id")!, x: r.x + r.width / 2, y: r.y + r.height / 2 };
    }),
  );
  const clearOf = (x: number, y: number, except?: string) =>
    centres.every((c) => c.id === except || Math.hypot(c.x - x, c.y - y) > 24);

  // A model off the frontier: its card names the top score at its price.
  const offId = centres.find(
    (c) => MEASURED.some((r) => r.m.id === c.id && leaderOf(r) !== r) && clearOf(c.x, c.y, c.id),
  )!.id;
  const off = MEASURED.find((r) => r.m.id === offId)!;
  await panel.locator(`[data-testid="frontier-chart-point"][data-model-id="${off.m.id}"]`).hover({ force: true });
  const card = page.getByTestId("frontier-card");
  await expect(card).toContainText(off.m.name);
  await expect(card.getByTestId("frontier-status")).toContainText(
    `Top score at this price or less: ${leaderOf(off).m.name}`,
  );
  await page.mouse.move(2, 2);
  await expect(card).toHaveCount(0);

  // The line: a point on a flat stretch, clear of every dot, names the ringed
  // model at that stretch's left end — the top score that price buys.
  const svgBox = (await panel.getByTestId("frontier-chart").locator("svg").boundingBox())!;
  let spot: { x: number; y: number; holder: string } | null = null;
  for (let i = 0; i < onFrontier.length && !spot; i += 1) {
    const from = centres.find((c) => c.id === onFrontier[i].m.id)!;
    const to =
      i + 1 < onFrontier.length
        ? centres.find((c) => c.id === onFrontier[i + 1].m.id)!.x
        : svgBox.x + svgBox.width - 30;
    for (let x = from.x + 14; x < to - 14 && !spot; x += 6) {
      if (clearOf(x, from.y)) spot = { x, y: from.y, holder: onFrontier[i].m.name };
    }
  }
  expect(spot).not.toBeNull();
  await page.mouse.move(spot!.x, spot!.y);
  await expect(card).toBeVisible();
  await expect(card.getByTestId("frontier-step-card")).toContainText(spot!.holder);
});

test("a superseded model is tagged with its successor and the day it leaves", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/models");
  const superseded = (catalog.models as (CatalogModel & {
    superseded_by?: string | null;
    retires_on?: string | null;
  })[]).filter((m) => m.superseded_by);
  await expect(page.getByTestId("superseded-tag")).toHaveCount(superseded.length);
  if (superseded.length === 0) return;
  const m = superseded[0];
  const successor = catalog.models.find((x) => x.id === m.superseded_by)!;
  const tag = page.locator(`[data-testid="model-row"][data-model-id="${m.id}"] [data-testid="superseded-tag"]`);
  await expect(tag).toHaveAttribute("data-superseded-by", successor.id);
  await expect(tag).toContainText(`Superseded by ${successor.name}`);
  await expect(tag).toContainText("leaves");
  await tag.getByTestId("superseded-trigger").hover();
  const card = page.getByTestId("superseded-card");
  await expect(card).toContainText(`Superseded by ${successor.name}.`);
  await expect(card).toContainText(`leaves the catalog on ${m.retires_on}`);
});

test("the expanded row carries the cited (mixed-source) benchmarks and pricing detail", async ({ page }) => {
  await page.goto("/models");

  // A row whose curation cited Terminal-Bench 2.1: expanding it reveals the
  // citation, linkified to its source leaderboard — evidence for the letters,
  // kept out of the main table because citations differ in source and scale.
  const tb = scored.find((m) => /Terminal-Bench 2\.1 (\d+(?:\.\d+)?)/.test(m.headline_benchmarks ?? ""))!;
  const tbScore = /Terminal-Bench 2\.1 (\d+(?:\.\d+)?)/.exec(tb.headline_benchmarks ?? "")![1];
  const row = page.getByTestId("model-row").filter({ hasText: tb.name }).first();
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
  const blended = blendedPrice(tb.input_price_per_1m, tb.output_price_per_1m);
  await expect(detail).toContainText(`Blended$${Number(blended.toFixed(2)).toString()}`);
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

  const claude = page.locator(`[data-testid="model-row"][data-model-id="${ANTHROPIC_MODEL.id}"]`);
  await expect(claude).toContainText("Anthropic");

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
  // value, then the seven categories — knowledge is the sixth category.
  const KNOWLEDGE_TD = 8 + 5;
  const rows = page.getByTestId("model-row");
  const count = await rows.count();
  const seen: { rating: string; aa: number | null }[] = [];
  const parse = (t: string) => (t.trim() === "—" ? null : Number.parseFloat(t));
  for (let i = 0; i < count; i += 1) {
    const r = rows.nth(i);
    const cell = r.locator("td").nth(KNOWLEDGE_TD);
    const rating = (await cell.locator("span").first().innerText()).trim();
    const aa = parse(await r.getByTestId("aa-index").innerText());
    seen.push({ rating, aa });
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

test("one Score chart per cost tier, every measured model plotted with the table's figure", async ({ page }) => {
  await page.goto("/models");
  const panel = page.getByTestId("score-charts");
  await expect(panel).toBeVisible(); // open by default: the charts are the explanation

  const fit = fitScoreModel(
    scored.map((m) => ({
      price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m),
      index: aaIndexFor(m),
      tier: m.tier_cost,
    })),
  );
  expect(fit).not.toBeNull();
  const tiers = Object.entries(fit!.tiers).filter(([, t]) => t.n >= 2).map(([tier]) => tier);
  await expect(panel.getByTestId("score-chart")).toHaveCount(tiers.length);

  for (const tier of tiers) {
    const chart = panel.locator(`[data-testid="score-chart"][data-tier="${tier}"]`);
    const inTier = scored.filter((m) => m.tier_cost === tier && aaIndexFor(m) !== null);
    await expect(chart.getByTestId("score-chart-point")).toHaveCount(inTier.length);
    for (const m of inTier) {
      const expected = formatScore(
        scoreFor(fit, m.tier_cost, blendedPrice(m.input_price_per_1m, m.output_price_per_1m), aaIndexFor(m)),
      );
      await expect(
        chart.locator(`[data-testid="score-chart-point"][data-model-id="${m.id}"]`),
      ).toHaveAttribute("aria-label", new RegExp(`Score ${expected.replace("+", "\\+")}`));
    }
  }

  // The footnote carries the live fit, not typed figures.
  await expect(panel).toContainText(`One least-squares fit over all ${fit!.n} AA-measured models`);
  await expect(panel).toContainText(`β = ${fit!.slope.toFixed(1)}`);
});

test("hovering a chart dot shows its model, Score, AA Index and prices; the line shows its equation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/models");
  const fit = fitScoreModel(
    scored.map((m) => ({
      price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m),
      index: aaIndexFor(m),
      tier: m.tier_cost,
    })),
  )!;
  // The charts draw once they have measured their width (after hydration).
  // A tier with a single measured model has no chart (no line to fit).
  const charted = Object.values(fit.tiers).reduce((sum, t) => sum + (t.n >= 2 ? t.n : 0), 0);
  await expect(page.getByTestId("score-chart-point")).toHaveCount(charted);
  // A dot no other dot overlaps, so the pointer lands on it and nothing else.
  const centres = await page.getByTestId("score-chart-point").evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.getAttribute("data-model-id")!, x: r.x + r.width / 2, y: r.y + r.height / 2 };
    }),
  );
  const clearId = centres.find((c) =>
    centres.every((o) => o === c || Math.hypot(o.x - c.x, o.y - c.y) > 28),
  )!.id;
  const m = scored.find((x) => x.id === clearId)!;
  const price = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const sc = scoreFor(fit, m.tier_cost, price, aaIndexFor(m));

  const dot = page.locator(`[data-testid="score-chart-point"][data-model-id="${m.id}"]`);
  await dot.scrollIntoViewIfNeeded();
  await dot.hover({ force: true });
  const card = page.getByTestId("chart-card");
  await expect(card).toBeVisible();
  await expect(card).toContainText(m.name);
  await expect(card.getByTestId("point-card-score")).toHaveText(formatScore(sc));
  await expect(card).toContainText(`$${m.input_price_per_1m.toFixed(2)} per 1M tokens`);
  await expect(card).toContainText(`$${m.output_price_per_1m.toFixed(2)} per 1M tokens`);
  // It sits inside the viewport, whatever the dot's position.
  const box = (await card.boundingBox())!;
  const vw = await page.evaluate(() => document.documentElement.clientWidth);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vw);

  // Leaving the dot closes the card.
  await page.mouse.move(2, 2);
  await expect(card).toHaveCount(0);

  // The line: its equation, with the tier's own intercept and the pooled slope.
  const tier = m.tier_cost;
  const line = page.locator(`[data-testid="score-chart"][data-tier="${tier}"] [data-testid="score-chart-line"]`);
  // A point ON the line, away from every dot (dots sit above the line's
  // hover target, so the pointer must be clear of them).
  const onLine = await line.evaluate((node) => {
    const el = node as unknown as SVGLineElement;
    const svg = el.ownerSVGElement!.getBoundingClientRect();
    const [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map((a) => Number(el.getAttribute(a)));
    const dots = [...el.ownerSVGElement!.querySelectorAll('[data-testid="score-chart-point"]')].map(
      (d) => {
        const r = d.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
      },
    );
    for (let f = 0.1; f <= 0.9; f += 0.05) {
      const x = svg.x + x1 + (x2 - x1) * f;
      const y = svg.y + y1 + (y2 - y1) * f;
      if (dots.every((d) => Math.hypot(d.x - x, d.y - y) > 20)) return { x, y };
    }
    return null;
  });
  expect(onLine).not.toBeNull();
  await page.mouse.move(onLine!.x, onLine!.y);
  await expect(card).toBeVisible();
  const t = fit.tiers[tier];
  const num = (v: number) => (Math.round(v * 10) / 10 < 0 ? "−" : "") + Math.abs(Math.round(v * 10) / 10).toFixed(1);
  await expect(card.getByTestId("line-equation")).toContainText(
    `Expected AA Index = ${num(t.intercept)} + ${num(fit.slope)} × log`,
  );
  await expect(card.getByTestId("line-readout")).toContainText("expected");
});

test("the Score cell opens a breakdown whose parts add up to the printed Score", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/models");
  const fit = fitScoreModel(
    scored.map((m) => ({
      price: blendedPrice(m.input_price_per_1m, m.output_price_per_1m),
      index: aaIndexFor(m),
      tier: m.tier_cost,
    })),
  )!;
  const parse = (t: string) => Number(t.replace("−", "-").replace("+", "").replace(/[^\d.-]/g, ""));
  for (const m of scored.filter((x) => aaIndexFor(x) !== null)) {
    const row = page.locator(`[data-testid="model-row"][data-model-id="${m.id}"]`);
    const trigger = row.getByTestId("score-trigger");
    await trigger.scrollIntoViewIfNeeded();
    await trigger.hover();
    const card = page.getByTestId("score-card");
    await expect(card).toBeVisible();
    await expect(card).toContainText(m.name);
    const total = card.getByTestId("score-breakdown-total");
    const printed = (await row.getByTestId("value-cell").innerText()).trim();
    await expect(total).toHaveText(printed);
    // The ledger's rows, read back from the card as a person would.
    const values = await card
      .locator('[data-testid="score-breakdown"] .tabular-nums')
      .allInnerTexts();
    const [index, subtracted, vsAvg, adj, score] = values.slice(0, 5).map(parse);
    const tierMean = Math.abs(subtracted); // printed "− 43.5": a subtraction, not a sign
    expect(Math.round((index - tierMean) * 10)).toBe(Math.round(vsAvg * 10));
    expect(Math.round((vsAvg + adj) * 10)).toBe(Math.round(score * 10));
    expect(formatScore(score)).toBe(
      formatScore(scoreFor(fit, m.tier_cost, blendedPrice(m.input_price_per_1m, m.output_price_per_1m), aaIndexFor(m))),
    );
    await page.mouse.move(2, 2);
    await expect(card).toHaveCount(0);
  }
});

test("the Score card opens from the keyboard, and an unmeasured model says why it has none", async ({ page }) => {
  await page.goto("/models");
  const trigger = page
    .locator(`[data-testid="model-row"][data-model-id="${WITH_AA.id}"]`)
    .getByTestId("score-trigger");
  await trigger.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(trigger).toBeFocused();
  await expect(page.getByTestId("score-card")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("score-card")).toHaveCount(0);

  if (WITHOUT_ANY) {
    const cell = page
      .locator(`[data-testid="model-row"][data-model-id="${WITHOUT_ANY.id}"]`)
      .getByTestId("value-cell");
    await cell.getByRole("button").hover();
    await expect(page.getByRole("tooltip")).toContainText(`No Score for ${WITHOUT_ANY.name}`);
  }
});

test("the page never scrolls sideways, from a phone to a desktop", async ({ page }) => {
  for (const width of [360, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/models");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `page overflow at ${width}px`).toBe(0);
  }
});
