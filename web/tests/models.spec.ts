// web/tests/models.spec.ts
//
// The /models catalog reference page (public): renders the full model table,
// the "how to read this" legend, sortable columns, the jurisdiction filter, the
// ratings/benchmarks view toggle, and benchmark + provider-doc links.

import { test, expect } from "@playwright/test";

test("renders the catalog table, legend, and model links", async ({ page }) => {
  await page.goto("/models");

  await expect(page.getByRole("heading", { name: "Model catalog" })).toBeVisible();
  await expect(page.getByText("How to read this table")).toBeVisible();
  await expect(page.getByTestId("model-catalog")).toBeVisible();

  // Every catalog model renders as a row.
  await expect(page.getByTestId("model-row")).toHaveCount(40);

  // Model names link to their provider's docs in a new tab.
  const fable = page.getByRole("link", { name: /^Fable 5$/ });
  await expect(fable).toHaveAttribute("href", /docs\.claude\.com/);
  await expect(fable).toHaveAttribute("target", "_blank");
});

test("default sort is output price descending; the header toggles ascending", async ({ page }) => {
  await page.goto("/models");

  // Highest output price first (Fable 5, $50/1M).
  await expect(page.getByTestId("model-row").first()).toContainText("Fable 5");

  await page.getByRole("button", { name: /Output/ }).click();
  // Cheapest output first (DeepSeek-V4-Flash, $0.28/1M).
  await expect(page.getByTestId("model-row").first()).toContainText("DeepSeek-V4-Flash");
});

test("the jurisdiction filter narrows the rows", async ({ page }) => {
  await page.goto("/models");

  await page.getByLabel("Filter by jurisdiction").selectOption("cn");
  // The six cn-jurisdiction models: 2× DeepSeek, 3× GLM, Kimi K2.7 Code
  // (Kimi K2.5 was delisted from Cursor 2026-07-15 and replaced by K2.7 Code).
  await expect(page.getByTestId("model-row")).toHaveCount(6);
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
