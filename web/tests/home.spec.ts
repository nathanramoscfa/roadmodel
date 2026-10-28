// web/tests/home.spec.ts
import { test, expect } from "@playwright/test";

test("home page leads with the model benchmark dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /Model catalog/i,
  );
  await expect(page.getByTestId("frontier-panel")).toBeVisible();
  await expect(page.getByTestId("model-catalog")).toBeVisible();
  await expect(page.getByTestId("catalog-legend")).toBeVisible();
  await expect(page.locator("#benchmarks")).toBeVisible();
});

test("home page links to /recommend and /models redirects to /", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: /get a recommendation/i }),
  ).toHaveAttribute("href", "/recommend");

  await page.goto("/models");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Model catalog/i);
});

test("footer carries the GitHub link", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.locator("footer").getByRole("link", { name: /GitHub/i }),
  ).toHaveAttribute("href", "https://github.com/nathanramoscfa/roadmodel");
});
