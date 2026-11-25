import { ORIGIN_HEADERS } from "./fixtures/origin";
// web/tests/recommend.spec.ts
import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect, type Page } from "@playwright/test";

import registry from "../data/engines.json";
import type { MultiRecommendResponse } from "../lib/api";
import { getModelRows } from "../lib/catalog-models";
import { effortPrice } from "../lib/pick-effort";
import { openFreeText } from "./fixtures/lanes";
import { E2E_AUTH_COOKIE, E2E_USER_ID, setE2eSessionCookie } from "./fixtures/onboarding-auth";

// The E2E server's invite list holds the E2E session's user (playwright.config).
const INVITED_COOKIE = { Cookie: `${E2E_AUTH_COOKIE}=${E2E_USER_ID}` };

type Pick = Record<string, unknown> & { priority?: string };

// A real /api/recommend answer (three picks, rationale sections, personalized
// cost rows), captured from production and stripped of personal detail, with
// the engine run the route now reports.
const FIXTURE = readFileSync(path.join(__dirname, "fixtures", "recommend-response.json"), "utf8");

// An answer as the service sends it now, captured from a local copy of the
// service for a three-plan profile (Claude Max, ChatGPT Pro, Google AI Pro):
// each pick ranked three deep (`ranks`), what the task was read as (`task`)
// and the settings its ladder weighed (`points`), which the chart is drawn
// over.
const RANKED = readFileSync(path.join(__dirname, "fixtures", "recommend-ranked.json"), "utf8");
const ranked = (): MultiRecommendResponse => JSON.parse(RANKED) as MultiRecommendResponse;
const card = (page: Page, priority: "cheap" | "balanced" | "best") => page.locator(`[data-priority="${priority}"]`);

// `mk` wraps a single legacy pick into the multi-pick response shape.
function mk(pick: Pick, primary = "balanced", engine?: Record<string, unknown>) {
  return JSON.stringify({ recommendations: [{ priority: primary, ...pick }], primary, engine });
}

const task = (page: Page) => page.getByPlaceholder(/Describe the task/i);
const submit = (page: Page) => page.getByRole("button", { name: /^Recommend/ });

async function ask(page: Page, text = "build a SQL agent") {
  await task(page).fill(text);
  await submit(page).click();
}

async function fulfill(page: Page, body: string, status = 200) {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({ status, contentType: "application/json", body }),
  );
}

test("/recommend renders the composer, the engine menu and how it works", async ({ page }) => {
  await openFreeText(page);
  await expect(page.getByRole("heading", { level: 1, name: "Recommend a model" })).toBeVisible();
  await expect(task(page)).toBeVisible();
  // Nothing to send yet.
  await expect(submit(page)).toBeDisabled();
  await expect(page.getByTestId("engine-picker")).toBeVisible();
  await expect(page.getByTestId("recommend-intro")).toBeVisible();
  await expect(page.getByRole("heading", { name: "How a recommendation is made" })).toBeVisible();
  // The frontier the picks will be read from is already drawn, with no pick on it.
  const chart = page.getByTestId("picks-chart");
  await expect(chart).toContainText("The cost/quality frontier");
  await expect(chart.getByTestId("picks-chart-point").first()).toBeAttached();
  await expect(chart.getByTestId("picks-chart-pick")).toHaveCount(0);
  // No pre-submit budget toggle: all three priorities come back together.
  await expect(page.getByRole("radiogroup", { name: /Budget priority/i })).toHaveCount(0);
});

test("an example fills the task", async ({ page }) => {
  await openFreeText(page);
  await page.getByRole("button", { name: "Bulk-classify tickets" }).click();
  await expect(task(page)).toHaveValue(/Classify 10,000 support tickets/);
  await expect(submit(page)).toBeEnabled();
});

test("a single submit renders all three priority picks (Cost / Balanced / Quality)", async ({ page }) => {
  await fulfill(
    page,
    JSON.stringify({
      primary: "balanced",
      recommendations: [
        { priority: "cheap", model: "Claude 4.5 Haiku", platform: "Claude Code", settings: {}, comparison_table: [] },
        { priority: "balanced", model: "GPT-5.4", platform: "Codex", settings: {}, comparison_table: [] },
        { priority: "best", model: "Claude Opus 4.8", platform: "Claude Code", settings: {}, comparison_table: [] },
      ],
    }),
  );
  await openFreeText(page);
  await ask(page);

  await expect(page.locator("[data-priority]")).toHaveCount(3);
  await expect(page.locator('[data-priority="cheap"]').getByText(/Claude 4.5 Haiku/i)).toBeVisible();
  await expect(page.locator('[data-priority="balanced"]').getByText(/GPT-5\.4/)).toBeVisible();
  await expect(page.locator('[data-priority="best"]').getByText(/Claude Opus 4\.8/i)).toBeVisible();
  // The saved-preference priority (Balanced) leads with the Default badge.
  await expect(page.locator('[data-priority="balanced"]').getByText("Default")).toBeVisible();
});

test("a pick carries its figures at the level it runs: AA Index, price, Score, ratings", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page, "Refactor a 3,000-line Python data pipeline into typed modules with tests.");
  const quality = card(page, "best");
  await expect(quality.getByTestId("pick-model")).toHaveText("Sonnet 5.5");
  await expect(quality.getByTestId("pick-platform")).toHaveText("Claude Code");
  await expect(quality.getByTestId("pick-level")).toHaveText("High");
  // The price is the list price with its output part scaled by the tokens
  // Sonnet 5.5 writes at High: the figure a roadmap's ladder prints.
  const sonnet = getModelRows().find((m) => m.name === "Sonnet 5.5")!;
  await expect(quality.getByTestId("pick-price")).toHaveText(`$${effortPrice(sonnet, "high").toFixed(2)}`);
  await expect(quality.getByTestId("pick-aa-index")).toHaveText(/^\d+\.\d$/);
  await expect(quality.getByTestId("pick-score")).toHaveText(/^([+−]\d+\.\d|0\.0)$/);
  await expect(page.getByTestId("pick-price")).toHaveCount(3);
  await expect(page.getByTestId("pick-score")).toHaveCount(3);
  // Seven S→D letters per pick, each marked measured or estimated.
  await expect(page.getByTestId("pick-ratings")).toHaveCount(3);
  await expect(page.getByTestId("pick-ratings").first().locator("[data-basis]")).toHaveCount(7);
  // Hovering the AA Index opens the same card /models shows, the price how
  // it is read, and the Score the card that shows how it adds up.
  await quality.getByTestId("pick-aa-index").hover();
  await expect(page.getByTestId("frontier-point-card")).toBeVisible();
  await page.mouse.move(2, 2);
  await expect(page.getByTestId("frontier-point-card")).toHaveCount(0);
  await quality.getByTestId("pick-price").hover();
  await expect(page.getByTestId("price-card")).toContainText(/at High this one writes \d+\.\d\d× the tokens a typical model writes at High/);
  await page.mouse.move(2, 2);
  await quality.getByTestId("pick-score").hover();
  await expect(page.getByTestId("score-breakdown")).toBeVisible();
  // The pick runs at High: its Score prices the tokens it draws there, as the
  // chart places it, not the bare list price.
  await expect(page.getByTestId("score-breakdown-effort")).toContainText(
    /At High effort, this model writes \d+\.\d\d× the output tokens of a typical model at High/,
  );
});

test("the result names the engine that wrote it, with time and cost", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page);
  const line = page.getByTestId("engine-line");
  await expect(line).toContainText("Picked by GPT-6 Luna");
  await expect(line).toContainText("0.15¢");
  await expect(page.getByTestId("engine-fell-back")).toHaveCount(0);
});

test("a fallback answer says which engine answered instead", async ({ page }) => {
  await fulfill(
    page,
    mk({ model: "Opus 4.8", platform: "Claude Code", settings: {}, comparison_table: [] }, "balanced", {
      hint: "openai-gpt-6-luna",
      name: "GPT-6 Luna",
      maker: "OpenAI",
      requested: "openai-gpt-6.1-sol",
      requested_name: "GPT-6.1 Sol",
      fell_back: true,
      latency_ms: 21000,
      cost_usd: 0.004,
      cost_source: "measured",
      cached_share: 0.9,
    }),
  );
  await openFreeText(page);
  await ask(page);
  await expect(page.getByTestId("engine-fell-back")).toHaveText(/GPT-6\.1 Sol did not answer, so GPT-6 Luna wrote these picks/);
});

test("the chart plots the picks among the catalog", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page);
  const chart = page.getByTestId("picks-chart");
  await expect(chart).toBeVisible();
  await expect(chart.getByTestId("picks-chart-pick")).toHaveCount(3);
  // Signed out there are no saved Settings: the whole catalog's frontier.
  await expect(page.getByTestId("picks-chart-scope")).toContainText("measured models");
  // Each pick at the effort it runs.
  await expect(page.getByRole("button", { name: /^Cost pick: Gemini 3\.8 Flash · Medium,/ })).toHaveCount(1);
  // A model's efforts are joined for the selected pick alone, until a point is hovered.
  const selectedPath = chart.locator('[data-testid="picks-chart-effort-path"][data-path="selected"]');
  await expect(selectedPath).toHaveCount(1);
  await expect(chart.locator('[data-testid="picks-chart-effort-path"][data-path="active"]')).toHaveCount(0);
  // The key says what that line is, by the model's name.
  const pathKey = chart.getByTestId("picks-chart-path-legend");
  const selectedModel = await page.locator('[data-priority][data-selected="1"]').getByTestId("pick-model").innerText();
  await expect(pathKey).toHaveText(`Selected pick: ${selectedModel} at each effort`);
  // Clicking a pick's marker selects its card.
  await chart.locator('[data-testid="picks-chart-pick"][data-pick="cheap"]').click();
  await expect(card(page, "cheap")).toHaveAttribute("data-selected", "1");
  await expect(page.getByTestId("pick-detail")).toHaveAttribute("data-pick", "cheap");
  // The line and its key follow the selection: there while the selected
  // pick's model is plotted at more than one effort.
  const drawn = await selectedPath.count();
  await expect(pathKey).toHaveCount(drawn);
  if (drawn > 0) {
    await expect(pathKey).toHaveText(`Selected pick: ${await card(page, "cheap").getByTestId("pick-model").innerText()} at each effort`);
  }
});

// What made the old chart unreadable: a name beside every other dot. Every
// point on the cost/quality frontier is named, with its effort. So is every
// point of the selected pick's model (the blue line) while that pick is
// selected. No other point is named, and no name covers a dot or another name.
async function expectFrontierNamed(page: Page) {
  const chart = page.getByTestId("picks-chart");
  await expect(chart.getByTestId("picks-chart-label").first()).toBeAttached();
  // The selected pick, where an answer is shown: its card says so.
  const selectedCard = page.locator('[data-priority][data-selected="1"]');
  const selected = (await selectedCard.count()) > 0 ? await selectedCard.first().getAttribute("data-priority") : null;
  const report = await chart.evaluate((el, selected) => {
    const targets = [...el.querySelectorAll<SVGCircleElement>('[data-testid="picks-chart-point"], [data-testid="picks-chart-pick"]')].map((c) => ({
      key: c.getAttribute("data-key")!,
      model: c.getAttribute("data-model-id")!,
      pick: c.getAttribute("data-pick"),
      frontier: c.getAttribute("data-frontier") === "1",
      cx: Number(c.getAttribute("cx")),
      cy: Number(c.getAttribute("cy")),
    }));
    const byKey = new Map(targets.map((t) => [t.key, t]));
    const labels = [...el.querySelectorAll('[data-testid="picks-chart-label"]')].map((g) => {
      const rect = g.querySelector("rect")!;
      return {
        key: g.getAttribute("data-key")!,
        path: g.getAttribute("data-path") === "1",
        text: g.querySelector("text")!.textContent ?? "",
        x: Number(rect.getAttribute("x")),
        y: Number(rect.getAttribute("y")),
        w: Number(rect.getAttribute("width")),
        h: Number(rect.getAttribute("height")),
      };
    });
    // The selected pick's model at every effort the chart plots it at.
    const model = selected ? (targets.find((t) => t.pick === selected)?.model ?? null) : null;
    return {
      labels: labels.map((l) => ({ ...l, frontier: byKey.get(l.key)?.frontier ?? false, model: byKey.get(l.key)?.model ?? null })),
      frontier: [...new Set(targets.filter((t) => t.frontier).map((t) => t.key))],
      line: model ? [...new Set(targets.filter((t) => t.model === model).map((t) => t.key))] : [],
      model,
      covered: labels.flatMap((l) =>
        targets
          .filter((t) => t.key !== l.key && t.cx > l.x && t.cx < l.x + l.w && t.cy > l.y && t.cy < l.y + l.h)
          .map((t) => `${l.text} covers ${t.key}`),
      ),
      stacked: labels.flatMap((a, i) =>
        labels
          .slice(i + 1)
          .filter((b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h)
          .map((b) => `${a.text} overlaps ${b.text}`),
      ),
    };
  }, selected);
  expect(report.frontier.length).toBeGreaterThan(1);
  // A name is a frontier point's, or a point's on the selected pick's line,
  for (const label of report.labels) {
    expect(label.frontier || label.model === report.model, `${label.text} names a frontier point or the selected pick's model`).toBe(true);
    // and it is marked as the line's when it is off the frontier.
    expect(label.path, `${label.text} is marked as the selected line's`).toBe(!label.frontier);
  }
  // and every one of those points is named, once.
  expect(report.labels.map((l) => l.key).sort()).toEqual([...new Set([...report.frontier, ...report.line])].sort());
  expect(report.covered).toEqual([]);
  expect(report.stacked).toEqual([]);
  return report;
}

test("every point on the frontier is named on the chart, and off it only the selected pick's line", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  // Before an answer: the frontier alone.
  await expectFrontierNamed(page);
  await ask(page);
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  await expectFrontierNamed(page);
  // Narrower, the rule holds: a name with no room by its point sits off it,
  // joined by a line.
  await page.setViewportSize({ width: 820, height: 900 });
  await expectFrontierNamed(page);
  // The chart fits its box at these widths: nothing to pan.
  await expect(page.getByTestId("picks-chart-pan-hint")).toHaveCount(0);
  await expect(page.getByTestId("picks-chart-pinned-axis")).toHaveCount(0);
});

test("the selected pick's model is named at each effort while it is selected, and the frontier's names stay put", async ({ page }) => {
  await fulfill(page, RANKED);
  await openFreeText(page);
  await ask(page);
  const chart = page.getByTestId("picks-chart");
  const frontierPlates = () =>
    chart.locator('[data-testid="picks-chart-label"][data-path="0"]').evaluateAll((els) =>
      Object.fromEntries(
        els.map((g) => {
          const r = g.querySelector("rect")!;
          return [g.getAttribute("data-key"), `${r.getAttribute("x")},${r.getAttribute("y")}`];
        }),
      ),
    );
  let before: Record<string, string> | null = null;
  let onLines = 0;
  for (const priority of ["cheap", "balanced", "best"] as const) {
    await card(page, priority).click();
    await expect(card(page, priority)).toHaveAttribute("data-selected", "1");
    const report = await expectFrontierNamed(page);
    // The names along the line are the selected pick's model at an effort.
    const model = await card(page, priority).getByTestId("pick-model").innerText();
    const along = report.labels.filter((l) => l.path);
    for (const label of along) expect(label.text.startsWith(`${model} · `), `${label.text} is ${model} at an effort`).toBe(true);
    // Every point the blue line passes through carries a name.
    const drawn = await chart.locator('[data-testid="picks-chart-effort-path"][data-path="selected"]').count();
    if (drawn > 0) expect(report.line.length).toBeGreaterThan(1);
    onLines += along.length;
    // The frontier's names are where they were under the last selection.
    const now = await frontierPlates();
    if (before) expect(now).toEqual(before);
    before = now;
  }
  // The fixture's picks include a model with an effort off the frontier.
  expect(onLines).toBeGreaterThan(0);
});

test("renders the backup row with its platform and effort", async ({ page }) => {
  await fulfill(
    page,
    mk({
      model: "Opus 4.8",
      platform: "Claude Code",
      settings: { max_mode: "OFF", thinking: "High" },
      backup: { model: "GPT-5.5", platform: "Codex", settings: { intelligence: "High" } },
      comparison_table: [],
    }),
  );
  await openFreeText(page);
  await ask(page);
  const backup = page.getByTestId("rank-backup");
  await expect(backup).toContainText("Backup");
  await expect(backup).toContainText("GPT-5.5");
  // Running the backup needs where and at what level, not just its name.
  await expect(page.getByTestId("backup-detail").first()).toHaveText("Codex · High");
  // An answer from before the ranks carries no Runner-up, so no such row.
  await expect(page.getByTestId("rank-runner_up")).toHaveCount(0);
  // It carried the pick's level as `thinking`: the card reads it as the level.
  await expect(page.getByTestId("pick-level").first()).toHaveText("High");
  await expect(page.locator('[data-setting="thinking"]')).toHaveCount(0);
  await expect(page.getByTestId("ladder-note")).toContainText("Each Pick names a Backup from another maker.");
});

test("each pick's AA Index is read at the effort it runs", async ({ page }) => {
  // AA measures a reasoning model at each effort; a pick run below its
  // headline effort reads that effort's figure, not the headline's.
  const bench = JSON.parse(readFileSync(path.join(__dirname, "..", "data", "benchmarks.json"), "utf8"));
  const at = (id: string, level: string): string =>
    bench.models[id].effort_variants[level].evaluations.artificial_analysis_intelligence_index.toFixed(1);
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page);
  // Gemini 3.8 Flash at Medium (its headline row is High); GPT-6 Luna at
  // High on Codex's Intelligence dial (headline Max).
  await expect(card(page, "cheap").getByTestId("pick-aa-index")).toHaveText(at("gemini-3.8-flash", "medium"));
  await expect(card(page, "cheap").getByTestId("pick-aa-effort")).toHaveText("at Medium");
  await expect(card(page, "balanced").getByTestId("pick-aa-index")).toHaveText(at("gpt-6-luna", "high"));
  await expect(card(page, "balanced").getByTestId("pick-aa-effort")).toHaveText("at High");
});

test("humanizes settings labels and renders the rationale prominently", async ({ page }) => {
  await fulfill(
    page,
    mk({
      model: "Opus 4.8",
      platform: "Claude Code",
      settings: {
        // Max Mode ON so the row renders — an all-OFF dial is hidden.
        max_mode: "ON",
        thinking: "On",
        effort: "High",
        budget_priority: "balanced",
        rationale: "Chosen for deep reasoning on a hard task.",
      },
      conversation: "New",
      comparison_table: [],
    }),
  );
  await openFreeText(page);
  await ask(page, "prove a theorem");
  const card = page.locator('[data-priority="balanced"]');
  await expect(card.getByText("Max Mode")).toBeVisible();
  await expect(card.getByTestId("pick-level")).toHaveText("High");
  // Thinking has no row, as in a roadmap's ladder: there is nothing to set.
  await expect(card.locator('[data-setting="thinking"]')).toHaveCount(0);
  await expect(card.getByTestId("pick-settings")).not.toContainText("Thinking");
  await expect(page.getByText("budget_priority")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Why Opus 4\.8\?/i })).toBeVisible();
  await expect(page.getByText(/Chosen for deep reasoning/i)).toBeVisible();
});

test("each pick names its level by its platform's own dial: Intelligence on Codex", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page);
  const ladder = page.getByTestId("picks-ladder");
  // Codex calls its level dial Intelligence; every other surface calls it Effort.
  await expect(ladder.getByText("Intelligence", { exact: true })).toHaveCount(1);
  const codex = card(page, "balanced").getByTestId("pick-settings");
  await expect(codex).toContainText("Intelligence");
  await expect(card(page, "balanced").getByTestId("pick-level")).toHaveText("High");
  await expect(card(page, "best").getByTestId("pick-settings")).toContainText("Effort");
  await expect(card(page, "cheap").getByTestId("pick-level")).toHaveText("Medium");
});

test("renders the rationale as readable lines with glossary popovers (#270, #269)", async ({ page }) => {
  await fulfill(
    page,
    mk({
      model: "Opus 4.8",
      platform: "Claude Code",
      settings: {
        rationale:
          "Opus 4.8 is S-tier for coding. It leads on SWE-bench Verified. THINKING is set to XHigh for the required rigor.",
      },
      comparison_table: [],
    }),
  );
  await openFreeText(page);
  await ask(page, "split + glossary");
  const why = page.getByRole("region", { name: /Why this model/i });
  await expect(why).toBeVisible();
  await expect(why.locator("p")).toHaveCount(3);
  const sTier = why.getByRole("link", { name: "S-tier" });
  await expect(sTier).toHaveAttribute("href", "/docs#ratings");
  await sTier.hover();
  const glossary = page.getByTestId("glossary-card");
  await expect(glossary).toBeVisible();
  await expect(glossary).toContainText("Frontier-class");
  await page.mouse.move(2, 2);
  await expect(glossary).toHaveCount(0);

  const swebench = why.getByRole("link", { name: "SWE-bench Verified" });
  await expect(swebench).toHaveAttribute("href", "https://www.swebench.com/");
  await expect(swebench).toHaveAttribute("target", "_blank");
  await swebench.hover();
  await expect(glossary).toBeVisible();
  await expect(glossary).toContainText("gold standard for software-engineering");
  await expect(glossary).toContainText("View source");
  await page.mouse.move(2, 2);
  await expect(glossary).toHaveCount(0);
});

test("renders sub-headed rationale sections when the service supplies them", async ({ page }) => {
  await fulfill(
    page,
    mk({
      model: "Opus 4.8",
      platform: "Claude Code",
      settings: {
        rationale: "TASK: Ship a report. PICK: Opus 4.8 is S-tier. EFFORT: Max fits the deep reasoning.",
      },
      rationale_sections: {
        task: "Ship an institutional-grade equity research report.",
        pick: "Opus 4.8 is S-tier for coding.",
        effort: "Max thinking fits the deep, long-context reasoning this audit demands.",
      },
      comparison_table: [],
    }),
  );
  await openFreeText(page);
  await ask(page, "structured why");
  const why = page.getByRole("region", { name: /Why this model/i });
  await expect(why.getByRole("heading", { name: "The task" })).toBeVisible();
  await expect(why.getByRole("heading", { name: "Why this pick" })).toBeVisible();
  await expect(why.getByRole("heading", { name: "Why this effort" })).toBeVisible();
  await expect(why.getByRole("heading", { name: "How to run it" })).toHaveCount(0);
  await expect(why.getByText(/Max thinking fits the deep, long-context reasoning/i)).toBeVisible();
});

// --- The ranked ladder: what a roadmap's Settings show, on the page -----------

// A level as the cards word it: the ladder's XHigh is the dials' "Extra high".
const levelWord = (level: string) => (level === "XHigh" ? "Extra high" : level);
const usd = (price: number | null) => `$${price!.toFixed(2)}`;

test("each pick is ranked three deep: a Runner-up and a Backup with platform, level, AA Index and price", async ({ page }) => {
  await fulfill(page, RANKED);
  await openFreeText(page);
  await ask(page, "Refactor a 3,000-line Python data pipeline into typed modules with tests.");
  await expect(page.getByRole("heading", { name: "Your three picks, each with a runner-up and a backup" })).toBeVisible();
  for (const rec of ranked().recommendations) {
    const ranks = rec.ranks!;
    const c = card(page, rec.priority);
    await expect(c.getByTestId("pick-model")).toHaveText(ranks.pick.model);
    await expect(c.getByTestId("pick-platform")).toHaveText(ranks.pick.platform);
    await expect(c.getByTestId("pick-level")).toHaveText(levelWord(ranks.pick.level));
    await expect(c.getByTestId("pick-price")).toHaveText(usd(ranks.pick.price_usd_per_1m));
    for (const [rank, option] of [["runner_up", ranks.runner_up!], ["backup", ranks.backup!]] as const) {
      const row = c.getByTestId(`rank-${rank}`);
      await expect(row).toContainText(rank === "backup" ? "Backup" : "Runner-up");
      await expect(row).toContainText(option.model);
      await expect(row.getByTestId(`${rank}-detail`)).toHaveText(`${option.platform} · ${levelWord(option.level)}`);
      await expect(row.getByTestId("rank-aa-index")).toHaveText(/^≈?\d+(\.\d)?$/);
      await expect(row.getByTestId("rank-price")).toHaveText(usd(option.price_usd_per_1m));
    }
    // Three makers: the three ranks name three models.
    expect(new Set([ranks.pick.model, ranks.runner_up!.model, ranks.backup!.model]).size).toBe(3);
  }
  // The engine's older single backup is not shown beside the ranks.
  await expect(page.getByTestId("rank-backup")).toHaveCount(3);
  await expect(page.getByTestId("rank-runner_up")).toHaveCount(3);
});

test("the result says what the task was read as, and the ladder what it was ranked for", async ({ page }) => {
  await fulfill(page, RANKED);
  await openFreeText(page);
  await ask(page);
  await expect(page.getByTestId("ladder-task-category")).toHaveText("Coding");
  await expect(page.getByTestId("ladder-task-complexity")).toHaveText("High complexity");
  await expect(page.getByTestId("ladder-task-novel")).toHaveCount(0);
  const note = page.getByTestId("ladder-note");
  await expect(note).toContainText("Ranked for coding, high complexity.");
  await expect(note).toContainText("the Pick, a Runner-up with the Pick’s maker left out, and a Backup with both left out");
  await expect(note).toContainText("≈ marks an estimate");
  // An answer from before the field says neither.
  await page.unroute("**/api/recommend");
  await fulfill(page, FIXTURE);
  await page.getByRole("button", { name: "Run again" }).click();
  await expect(card(page, "best").getByTestId("pick-model")).toHaveText("Sonnet 5.5");
  await expect(page.getByTestId("ladder-task")).toHaveCount(0);
  await expect(page.getByTestId("ladder-note")).not.toContainText("Ranked for");
});

test("a novel task is named as one", async ({ page }) => {
  const answer = ranked();
  answer.task = { category: "planning", complexity: "high", novel: true };
  await fulfill(page, JSON.stringify(answer));
  await openFreeText(page);
  await ask(page);
  await expect(page.getByTestId("ladder-task-category")).toHaveText("Planning");
  await expect(page.getByTestId("ladder-task-novel")).toHaveText("A new kind of problem");
  await expect(page.getByTestId("ladder-note")).toContainText("Ranked for planning, high complexity, a new kind of problem.");
});

test("the chart is drawn over the answer's own frontier, and every pick sits on it", async ({ page }) => {
  await fulfill(page, RANKED);
  await openFreeText(page);
  await ask(page);
  const chart = page.getByTestId("picks-chart");
  // The settings the answer's ladder weighed, not the page's own reading of the catalog.
  await expect(chart).toHaveAttribute("data-served", "1");
  await expect(page.getByTestId("picks-chart-scope")).toContainText(/\d+ effort settings · \d+ on the frontier/);
  const picks = chart.getByTestId("picks-chart-pick");
  await expect(picks).toHaveCount(3);
  for (const priority of ["cheap", "balanced", "best"] as const) {
    // Read from the line, plotted on the line, and said to be on it.
    await expect(chart.locator(`[data-testid="picks-chart-pick"][data-pick="${priority}"]`)).toHaveAttribute("data-frontier", "1");
    await expect(chart.locator(`[data-testid="picks-chart-pick"][data-pick="${priority}"]`)).toHaveAttribute("data-adequate", "1");
    await expect(card(page, priority).getByTestId("pick-frontier")).toHaveText("On the frontier");
  }
  // A setting below the task's bar is hollow, and the key says so.
  expect(await chart.locator('[data-adequate="0"]').count()).toBeGreaterThan(0);
  await expect(chart.getByTestId("picks-chart-bar-legend")).toContainText("below this task’s bar");
  // Each frontier point is named with the effort it stands at; a pick's name
  // is the one its card carries.
  const named = await expectFrontierNamed(page);
  for (const priority of ["cheap", "balanced", "best"] as const) {
    const key = await chart.locator(`[data-testid="picks-chart-pick"][data-pick="${priority}"]`).getAttribute("data-key");
    const model = await card(page, priority).getByTestId("pick-model").innerText();
    const level = await card(page, priority).getByTestId("pick-level").innerText();
    expect(named.labels.find((l) => l.key === key)?.text).toBe(`${model} · ${level}`);
    await expect(chart.locator(`[data-testid="picks-chart-label"][data-key="${key}"]`)).toHaveAttribute("data-pick", "1");
  }
  // The Cost pick is the cheapest point on the line that meets the bar.
  const line = await chart.locator('[data-frontier="1"]').evaluateAll((els) =>
    els.map((e) => ({ x: Number(e.getAttribute("cx")), adequate: e.getAttribute("data-adequate") === "1", pick: e.getAttribute("data-pick") })),
  );
  const cheapest = line.filter((p) => p.adequate).sort((a, b) => a.x - b.x)[0];
  expect(cheapest.pick).toBe("cheap");
});

test("an estimate is plotted where the recommender counts it, and its card says so", async ({ page }) => {
  // The Cost pick's AA Index is roadmodel's estimate: the frontier counts it a
  // margin lower, and the point's card shows both figures.
  const answer = ranked();
  const cost = answer.recommendations.find((r) => r.priority === "cheap")!.ranks!.pick;
  const point = answer.points!.find((p) => p.model_id === cost.model_id && p.effort === cost.effort)!;
  expect(point.estimated && point.margin > 0).toBe(true);
  await fulfill(page, RANKED);
  await openFreeText(page);
  await ask(page);
  await page.locator('[data-testid="picks-chart-pick"][data-pick="cheap"]').hover();
  const shown = page.getByTestId("picks-chart-card");
  await expect(shown.getByTestId("frontier-point-counted")).toHaveText((point.aa_index - point.margin).toFixed(1));
  await expect(shown).toContainText(`counts it ${point.margin.toFixed(1)} points lower for its uncertainty`);
});

test("a rank no other maker fills is the Pick a level lower, and the note says why", async ({ page }) => {
  // One maker in reach: the Runner-up is the Pick's own model one level
  // lower (↓), and the Backup has nothing to name.
  const answer = ranked();
  for (const rec of answer.recommendations) {
    const pick = rec.ranks!.pick;
    rec.ranks!.runner_up = { ...pick, effort: "low", level: "Low", stepped_down: true };
    rec.ranks!.backup = null;
  }
  await fulfill(page, JSON.stringify(answer));
  await openFreeText(page);
  await ask(page);
  const quality = card(page, "best");
  const runner = quality.getByTestId("rank-runner_up");
  await expect(runner).toContainText(answer.recommendations.find((r) => r.priority === "best")!.model);
  await expect(runner.getByTestId("rank-stepped-down")).toHaveText("↓");
  await expect(quality.getByTestId("rank-backup")).toContainText("No other maker’s model in reach");
  const note = page.getByTestId("ladder-note-stepped");
  await expect(note).toContainText("↓ is the Pick’s own model one level lower");
  await expect(note.getByRole("link", { name: /Add another maker’s plan or API key/ })).toHaveAttribute("href", "/settings");
  await expect(page.getByTestId("ladder-note")).not.toContainText("a Runner-up with the Pick’s maker left out");
});

test("selecting a pick shows its reasoning and its cost by platform", async ({ page }) => {
  await fulfill(page, RANKED);
  await openFreeText(page);
  await ask(page);
  const answer = ranked();
  const detail = page.getByTestId("pick-detail");
  // The answer leads with the viewer's default tier.
  await expect(detail).toHaveAttribute("data-pick", answer.primary);
  await expect(card(page, answer.primary)).toHaveAttribute("data-selected", "1");
  for (const rec of answer.recommendations) {
    await card(page, rec.priority).click();
    await expect(detail).toHaveAttribute("data-pick", rec.priority);
    await expect(detail.getByRole("heading", { name: `Why ${rec.model}?` })).toBeVisible();
    await expect(detail.getByText(rec.rationale_sections!.pick)).toBeVisible();
    // Its list prices, stated once, then what it costs on each platform.
    await expect(detail.getByTestId("cost-list-price")).toContainText(`${rec.model} lists at`);
    await expect(detail.getByRole("columnheader", { name: "Your cost" })).toBeVisible();
  }
  // The detail's own tabs switch the pick too.
  await detail.getByRole("tab", { name: "Cost" }).click();
  await expect(card(page, "cheap")).toHaveAttribute("data-selected", "1");
});

test("a ranked answer reopens from this browser with its ranks and its frontier", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/recommend", async (route) => {
    calls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: RANKED });
  });
  await openFreeText(page);
  await ask(page, "a ranked task worth remembering");
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  await page.reload();
  await page.getByTestId("saved-recommendations").getByRole("button", { name: /^a ranked task worth remembering/ }).click();
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  // What a saved entry keeps is enough to draw the whole answer again.
  await expect(page.getByTestId("rank-runner_up")).toHaveCount(3);
  await expect(page.getByTestId("ladder-task-category")).toHaveText("Coding");
  await expect(page.getByTestId("picks-chart")).toHaveAttribute("data-served", "1");
  expect(calls).toBe(1);
});

test("the engine menu offers the evaluated engines an invited member may use, and remembers the choice", async ({
  page,
}) => {
  let sentEngine: unknown;
  await page.route("**/api/recommend", async (route) => {
    sentEngine = (JSON.parse(route.request().postData() ?? "{}") as { engine?: unknown }).engine;
    await route.fulfill({ status: 200, contentType: "application/json", body: FIXTURE });
  });
  await setE2eSessionCookie(page);
  await page.goto("/recommend");
  await page.getByTestId("engine-picker").click();
  const options = page.getByTestId("engine-options").getByRole("option");
  await expect(options).toHaveCount(registry.engines.filter((e) => e.menu !== null).length);
  // Invited: the invited engines can be chosen; the founder's are listed locked.
  const invitedHints = registry.engines.filter((e) => e.menu === "invited").map((e) => e.hint);
  for (const hint of invitedHints) {
    await expect(page.locator(`[data-engine="${hint}"]`)).toHaveAttribute("data-allowed", "1");
  }
  for (const e of registry.engines.filter((e) => e.menu === "founder")) {
    await expect(page.locator(`[data-engine="${e.hint}"]`)).toHaveAttribute("data-allowed", "0");
  }
  // Choose an invited engine other than the default.
  const other = invitedHints.find((h) => h !== registry.default)!;
  await page.locator(`[data-engine="${other}"]`).click();
  await ask(page);
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  expect(sentEngine).toBe(other);
  // The choice survives a reload (cookie, read by the server).
  await page.reload();
  await page.getByTestId("engine-picker").click();
  await expect(page.locator(`[data-engine="${other}"]`)).toHaveAttribute("aria-selected", "true");
});

test("signed out, every engine on the menu is locked", async ({ page }) => {
  await openFreeText(page);
  await page.getByTestId("engine-picker").click();
  await expect(page.locator('[data-engine][data-allowed="1"]')).toHaveCount(0);
  await expect(page.locator(`[data-engine="${registry.default}"]`)).toContainText(/Invited members/);
});

test("a 402 reads as what the visitor can do, in plain words", async ({ page }) => {
  await fulfill(page, JSON.stringify({ error: "funding_required" }), 402);
  await openFreeText(page);
  await ask(page, "pick a model");
  await expect(page.getByTestId("funding-notice")).toHaveText(
    "Recommend runs on roadmodel's account for invited members. Add your own API key below to run it on yours.",
  );
  // The key panel opens beside the notice.
  await expect(page.getByTestId("visitor-key-panel")).toBeVisible();
  await expect(page.getByText(/unavailable|try again/i)).toHaveCount(0);
});

test("the API refuses an engine the visitor may not use, before any upstream call", async ({ request }) => {
  // The E2E session's user is invited, so a founder-only or unknown engine is
  // refused at the edge (lib/recommend-engines), never forwarded.
  const founderOnly = registry.engines.find((e) => e.menu === "founder")!;
  const refused = await request.post("/api/recommend", {
    headers: { ...ORIGIN_HEADERS, ...INVITED_COOKIE },
    data: { task_description: "pick a model", engine: founderOnly.hint },
  });
  expect(refused.status()).toBe(403);
  expect(["engine_not_allowed", "engine_not_evaluated"]).toContain((await refused.json()).error);

  const unknown = await request.post("/api/recommend", {
    headers: { ...ORIGIN_HEADERS, ...INVITED_COOKIE },
    data: { task_description: "pick a model", engine: "no-such-engine" },
  });
  expect(unknown.status()).toBe(400);
  expect(await unknown.json()).toMatchObject({ error: "unknown_engine" });
});

test("a saved result reopens from this browser without a new request", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/recommend", async (route) => {
    calls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: FIXTURE });
  });
  await openFreeText(page);
  await ask(page, "a task worth remembering");
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  await page.reload();
  const saved = page.getByTestId("saved-recommendations");
  await expect(saved).toContainText("a task worth remembering");
  await saved.getByRole("button", { name: /^a task worth remembering/ }).click();
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  expect(calls).toBe(1);
});

test("attached text file content is prepended to the request body (file-input Phase A)", async ({ page }) => {
  let sentTask = "";
  await page.route("**/api/recommend", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}") as { task_description?: string };
    sentTask = body.task_description ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: mk({ model: "Opus 4.8", platform: "Claude Code", settings: {}, comparison_table: [] }),
    });
  });
  await openFreeText(page);
  await page.getByTestId("recommend-composer").locator('input[type="file"]').setInputFiles({
    name: "my-prompt.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Summarize this quarterly earnings report."),
  });
  await expect(page.getByText("my-prompt.txt")).toBeVisible();
  await ask(page, "which model should I use?");
  await expect(page.getByText(/Opus 4.8/i).first()).toBeVisible();
  expect(sentTask).toContain("Attached file my-prompt.txt:");
  expect(sentTask).toContain("Summarize this quarterly earnings report.");
  expect(sentTask).toContain("which model should I use?");
  expect(sentTask.indexOf("Summarize this quarterly")).toBeLessThan(sentTask.indexOf("which model should I use?"));
});

test("non-text files are skipped with a hint (file-input Phase A)", async ({ page }) => {
  await openFreeText(page);
  await page.getByTestId("recommend-composer").locator('input[type="file"]').setInputFiles({
    name: "diagram.png",
    mimeType: "image/png",
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
  });
  await expect(page.getByText(/only text files \(\.txt, \.md, \.json\) are supported/i)).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "diagram.png" })).toHaveCount(0);
});

test("502 error renders friendly message", async ({ page }) => {
  await fulfill(page, JSON.stringify({ error: "recommender_unavailable" }), 502);
  await openFreeText(page);
  await ask(page, "hello");
  await expect(page.getByText(/try again in a moment/i)).toBeVisible();
});

// The rate-limit decision itself is covered by @upstash/ratelimit and
// ratelimit.spec; these pin the user-visible contract for its 429 bodies.
test("burst_limit burst-drop 429 renders slow-down message", async ({ page }) => {
  await fulfill(page, JSON.stringify({ error: "burst_dropped", retry_after: 60 }), 429);
  await openFreeText(page);
  await ask(page, "burst test");
  await expect(page.getByText(/Slow down/i)).toBeVisible();
});

test("daily_limit daily-cap 429 renders daily-cap message", async ({ page }) => {
  await fulfill(page, JSON.stringify({ error: "rate_limited", retry_after: 3600 }), 429);
  await openFreeText(page);
  await ask(page, "daily test");
  await expect(page.getByText(/daily recommendation limit/i)).toBeVisible();
});

test("blank task_description returns 400 bad_input (no upstream call)", async ({ request }) => {
  const res = await request.post("/api/recommend", { headers: { ...ORIGIN_HEADERS, ...INVITED_COOKIE }, data: { task_description: "   " } });
  expect(res.status()).toBe(400);
  expect(await res.json()).toMatchObject({ error: "bad_input" });
});

test("a signed-out request is refused before its input is read", async ({ request }) => {
  const res = await request.post("/api/recommend", { headers: ORIGIN_HEADERS,  data: { task_description: "   " } });
  expect(res.status()).toBe(402);
  expect(await res.json()).toEqual({
    error: "funding_required",
    options: ["visitor_key", "openrouter", "keyless", "own_agent"],
  });
});
