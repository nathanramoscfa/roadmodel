// web/tests/home.spec.ts
import { test, expect } from "@playwright/test";

test("home page renders hero + both surface CTAs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /Pick the right model for the right job/i,
  );
  // Two entry points — recommend + catalog — and no inline task form; that
  // lives on /recommend now.
  await expect(
    page.getByRole("link", { name: /Get a recommendation/i }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Browse the catalog/i }).first(),
  ).toBeVisible();
  await expect(page.locator("textarea")).toHaveCount(0);
});

test("hero CTAs link to the recommend and models surfaces", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: /Get a recommendation/i }).first(),
  ).toHaveAttribute("href", "/recommend");
  await expect(
    page.getByRole("link", { name: /Browse the catalog/i }).first(),
  ).toHaveAttribute("href", "/models");
});

test("footer carries the GitHub link", async ({ page }) => {
  await page.goto("/");
  // Two GitHub links now exist (the open-source section + the footer); scope to
  // the <footer> element so the assertion stays unambiguous.
  await expect(
    page.locator("footer").getByRole("link", { name: /GitHub/i }),
  ).toHaveAttribute("href", /github\.com\/nathanramoscfa\/roadmodel/);
});
