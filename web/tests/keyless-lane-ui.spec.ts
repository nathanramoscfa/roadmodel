// web/tests/keyless-lane-ui.spec.ts
//
// The lanes on /recommend, end to end against the E2E mock /v1/score
// (app/api/test/mock-recommend/score). Signed out, a visitor holding no key
// sees the lane chooser on Quick pick: the form, then three explained picks
// with the measured agreement read from the build's keyless-eval.json; "Run it
// in your own agent" shows the two commands; "Use your own API key" opens the
// free-text composer. The invited member sees the free-text flow as before.
//
// The E2E server's Upstash is a placeholder: each limiter call retries for a
// few seconds before the lane fails open (lib/ratelimit.ts). RUN is the wait.
const RUN = { timeout: 30_000 };

import { test, expect } from "@playwright/test";

import keylessEval from "../data/keyless-eval.json";
import { chooseLane } from "./fixtures/lanes";
import { setE2eSessionCookie } from "./fixtures/onboarding-auth";

test("signed out: the chooser opens on Quick pick, and its form returns three explained picks", async ({ page }) => {
  test.setTimeout(60_000);
  const sent: unknown[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/recommend/keyless")) sent.push(r.postDataJSON());
  });
  await page.goto("/recommend");
  const chooser = page.getByTestId("lane-chooser");
  await expect(chooser).toBeVisible();
  for (const label of ["Quick pick", "Use your own API key", "Connect OpenRouter", "Run it in your own agent"]) {
    await expect(chooser).toContainText(label);
  }
  await expect(page.getByTestId("lane-quick")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("lane-quick")).toContainText("Free, computed from published benchmarks and prices");

  const form = page.getByTestId("quick-pick-form");
  await expect(form).toBeVisible();
  // The seven task types, each with its one-line description.
  await expect(form.getByRole("radio", { name: /Coding/ })).toBeChecked();
  await expect(form).toContainText("Writing, refactoring, and debugging code across languages.");
  await expect(form.locator('input[name="category"]')).toHaveCount(7);

  await expect(async () => {
    await form.getByRole("radio", { name: /^Planning/ }).check();
    await expect(form.getByRole("radio", { name: /^Planning/ })).toBeChecked({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
  await form.getByRole("radio", { name: /^High/ }).check();
  await page.getByTestId("quick-pick-novel").check();
  await form.getByRole("radio", { name: /^Quality/ }).check();
  await page.getByTestId("quick-pick-submit").click();

  const result = page.getByTestId("keyless-result");
  await expect(result).toBeVisible(RUN);
  expect(sent).toEqual([{ category: "planning", complexity: "high", novel: true, budget_priority: "best" }]);
  for (const rung of ["quality", "balanced", "cost"]) {
    const card = page.getByTestId(`keyless-rung-${rung}`);
    await expect(card).toBeVisible();
    await expect(card).toContainText("Strength");
    await expect(card).toContainText("Fit to the task");
  }
  await expect(page.getByTestId("keyless-rung-quality")).toContainText("Your priority");
  await expect(page.getByTestId("keyless-task")).toHaveText("Planning · High difficulty · a new kind of problem");

  // The agreement, from the synced record.
  await expect(page.getByTestId("keyless-agreement")).toHaveText(
    "These picks are computed from published benchmarks and prices. " +
      `On our ${keylessEval.probes.length} test tasks they matched the AI recommender on ` +
      `${keylessEval.agree} of ${keylessEval.total} picks.`,
  );
  await expect(page.getByTestId("keyless-agreement-date")).toContainText(`Measured ${keylessEval.evaluated_on}`);

  // Back to the form, the last task kept.
  await page.getByRole("button", { name: "Change the task" }).click();
  await expect(form.getByRole("radio", { name: /^Planning/ })).toBeChecked();
});

test("signed out: the own-agent panel shows the two commands and the guide, nothing of the viewer's", async ({
  page,
}) => {
  await page.goto("/recommend");
  await chooseLane(page, "agent", "own-agent-panel");
  await expect(page.getByTestId("own-agent-command")).toHaveText(['pip install "roadmodel[mcp]"', "roadmodel setup-mcp"]);
  await expect(page.getByTestId("own-agent-guide")).toHaveAttribute(
    "href",
    "https://github.com/nathanramoscfa/roadmodel/blob/main/docs/mcp-setup.md",
  );
  const text = (await page.getByTestId("own-agent-panel").innerText()).toLowerCase();
  expect(text).not.toMatch(/sk-|bearer|token=/);
});

test("signed out: \"Use your own API key\" opens the free-text composer with the key panel", async ({ page }) => {
  await page.goto("/recommend");
  await chooseLane(page, "key", "recommend-composer");
  await expect(page.getByTestId("visitor-key-panel")).toBeVisible();
  await expect(page.getByTestId("lane-key")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("quick-pick-form")).toHaveCount(0);
  // "Connect OpenRouter" is the same composer, on OpenRouter.
  await chooseLane(page, "openrouter", "openrouter-connect");
  await expect(page.getByTestId("lane-openrouter")).toHaveAttribute("aria-pressed", "true");
});

test("invited: the free-text flow as before, no chooser", async ({ page }) => {
  await setE2eSessionCookie(page);
  await page.goto("/recommend");
  await expect(page.getByTestId("recommend-composer")).toBeVisible();
  await expect(page.getByPlaceholder(/Describe the task/i)).toBeVisible();
  await expect(page.getByTestId("lane-chooser")).toHaveCount(0);
  await expect(page.getByTestId("quick-pick-form")).toHaveCount(0);
});
