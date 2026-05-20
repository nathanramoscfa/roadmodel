// web/tests/recommend.spec.ts
import { test, expect } from "@playwright/test";

test("/recommend renders form + empty output", async ({ page }) => {
  await page.goto("/recommend");
  await expect(
    page.getByPlaceholder(/Describe the task/i),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Submit/i }),
  ).toBeVisible();
  await expect(
    page.getByText(/Your recommendation will appear here/i),
  ).toBeVisible();
});

test(
  "successful submit renders model, platform, cost table, free-tier label",
  async ({ page }) => {
    await page.route("**/api/recommend", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          model: "Claude 4.5 Haiku",
          platform: "Anthropic API",
          settings: {
            max_tokens: 4096,
          },
          session_cost_estimate: {
            total_usd: 0.0042,
          },
          comparison_table: [
            {
              model: "Claude 4.5 Haiku",
              platform: "Anthropic API",
              total_usd: 0.0042,
            },
          ],
        }),
      }),
    );
    await page.goto("/recommend");
    await page
      .getByPlaceholder(/Describe the task/i)
      .fill("build a SQL agent");
    await page.getByRole("button", { name: /Submit/i }).click();
    await expect(page.getByText(/Claude 4.5 Haiku/i)).toBeVisible();
    await expect(page.getByText(/Free tier/i)).toBeVisible();
  },
);

test("502 error renders friendly message", async ({ page }) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        error: "recommender_unavailable",
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Describe the task/i).fill("hello");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByText(/try again in a moment/i),
  ).toBeVisible();
});
