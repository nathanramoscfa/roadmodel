// web/tests/recommend.spec.ts
import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect, type Page } from "@playwright/test";

import registry from "../data/engines.json";
import { openFreeText } from "./fixtures/lanes";
import { E2E_AUTH_COOKIE, E2E_USER_ID, setE2eSessionCookie } from "./fixtures/onboarding-auth";

// The E2E server's invite list holds the E2E session's user (playwright.config).
const INVITED_COOKIE = { Cookie: `${E2E_AUTH_COOKIE}=${E2E_USER_ID}` };

type Pick = Record<string, unknown> & { priority?: string };

// A real /api/recommend answer (three picks, rationale sections, personalized
// cost rows), captured from production and stripped of personal detail, with
// the engine run the route now reports.
const FIXTURE = readFileSync(path.join(__dirname, "fixtures", "recommend-response.json"), "utf8");

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

test("a pick carries the catalog's facts: blended price, AA Index, Score, ratings", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page, "Refactor a 3,000-line Python data pipeline into typed modules with tests.");
  const quality = page.locator('[data-priority="best"]');
  await expect(quality.getByText("Sonnet 5.5")).toBeVisible();
  // One row each, read across the three picks. Sonnet 5.5: ($2 × 3 + $10) ÷ 4.
  const cell = (row: string) => page.locator(`[data-pick="best"][data-row="${row}"]`);
  await expect(cell("__price").getByTestId("pick-price")).toHaveText("$4.00");
  await expect(cell("__aa").getByTestId("pick-aa-index")).toHaveText(/^\d+\.\d$/);
  await expect(cell("__score").getByTestId("pick-score")).toHaveText(/^([+−]\d+\.\d|0\.0)$/);
  await expect(page.getByTestId("pick-price")).toHaveCount(3);
  await expect(page.getByTestId("pick-score")).toHaveCount(3);
  // Seven S→D letters per pick, each marked measured or estimated.
  await expect(page.getByTestId("pick-ratings")).toHaveCount(3);
  await expect(page.getByTestId("pick-ratings").first().locator("[data-basis]")).toHaveCount(7);
  // Hovering the AA Index opens the same card /models shows, and the Score
  // the card that shows how it adds up.
  await cell("__aa").getByTestId("pick-aa-index").hover();
  await expect(page.getByTestId("frontier-point-card")).toBeVisible();
  await cell("__score").getByTestId("pick-score").hover();
  await expect(page.getByTestId("score-breakdown")).toBeVisible();
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
  await expect(page.getByTestId("picks-chart")).toBeVisible();
  await expect(page.getByTestId("picks-chart-pick")).toHaveCount(3);
  // Signed out there are no saved Settings: the whole catalog's frontier.
  await expect(page.getByTestId("picks-chart-scope")).toContainText("measured models");
  await expect(page.getByTestId("picks-chart-outside")).toHaveCount(0);
});

test("renders the backup model row when the recommendation includes one", async ({ page }) => {
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
  await expect(page.getByText("Backup", { exact: true })).toBeVisible();
  await expect(page.getByText(/GPT-5\.5/)).toBeVisible();
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
        thinking: "High",
        budget_priority: "balanced",
        rationale: "Chosen for deep reasoning on a hard task.",
      },
      conversation: "New",
      comparison_table: [],
    }),
  );
  await openFreeText(page);
  await ask(page, "prove a theorem");
  await expect(page.getByText("Max Mode")).toBeVisible();
  await expect(page.getByText("Thinking")).toBeVisible();
  await expect(page.getByText("budget_priority")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Why Opus 4\.8\?/i })).toBeVisible();
  await expect(page.getByText(/Chosen for deep reasoning/i)).toBeVisible();
});

test("one Effort row carries Codex's Intelligence value", async ({ page }) => {
  await fulfill(page, FIXTURE);
  await openFreeText(page);
  await ask(page);
  const matrix = page.getByTestId("picks-matrix");
  await expect(matrix.getByText("Effort", { exact: true })).toBeVisible();
  await expect(matrix.getByText("Intelligence", { exact: true })).toHaveCount(1); // the Codex cell's note, not a row
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
  const tooltips = why.locator('[role="tooltip"]');
  await expect(tooltips).toHaveCount(2);
  await expect(tooltips.filter({ hasText: "Frontier-class" })).toHaveCount(1);
  await expect(tooltips.filter({ hasText: "gold standard for software-engineering" })).toHaveCount(1);
  const swebench = why.getByRole("link", { name: "SWE-bench Verified" });
  await expect(swebench).toHaveAttribute("href", "https://www.swebench.com/");
  await expect(swebench).toHaveAttribute("target", "_blank");
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
    headers: INVITED_COOKIE,
    data: { task_description: "pick a model", engine: founderOnly.hint },
  });
  expect(refused.status()).toBe(403);
  expect(["engine_not_allowed", "engine_not_evaluated"]).toContain((await refused.json()).error);

  const unknown = await request.post("/api/recommend", {
    headers: INVITED_COOKIE,
    data: { task_description: "pick a model", engine: "no-such-engine" },
  });
  expect(unknown.status()).toBe(400);
  expect(await unknown.json()).toMatchObject({ error: "unknown_engine" });
});

test("a recent result reopens from this browser without a new request", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/recommend", async (route) => {
    calls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: FIXTURE });
  });
  await openFreeText(page);
  await ask(page, "a task worth remembering");
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  await page.reload();
  const recent = page.getByTestId("recent-recommendations");
  await expect(recent).toContainText("a task worth remembering");
  await recent.getByRole("button", { name: /a task worth remembering/ }).click();
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
  await page.locator('input[type="file"]').setInputFiles({
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
  await page.locator('input[type="file"]').setInputFiles({
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
  const res = await request.post("/api/recommend", { headers: INVITED_COOKIE, data: { task_description: "   " } });
  expect(res.status()).toBe(400);
  expect(await res.json()).toMatchObject({ error: "bad_input" });
});

test("a signed-out request is refused before its input is read", async ({ request }) => {
  const res = await request.post("/api/recommend", { data: { task_description: "   " } });
  expect(res.status()).toBe(402);
  expect(await res.json()).toEqual({
    error: "funding_required",
    options: ["visitor_key", "openrouter", "keyless", "own_agent"],
  });
});
