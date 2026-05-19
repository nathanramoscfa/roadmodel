// web/tests/home.spec.ts
import { test, expect } from "@playwright/test";

test("home page renders hero + CTA", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1 }),
  ).toHaveText(/Pick the right model for the right job/i);
  await expect(
    page.getByRole("link", { name: /Try it free/i }),
  ).toBeVisible();
});

test("footer carries the GitHub link", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: /GitHub/i })).toHaveAttribute(
    "href",
    /github\.com\/nathanramoscfa\/roadmodel/,
  );
});
