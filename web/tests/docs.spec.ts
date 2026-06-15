import { test, expect } from "@playwright/test";

test("/docs renders how-it-works, the rating scale, and linked benchmarks", async ({
  page,
}) => {
  await page.goto("/docs");
  await expect(
    page.getByRole("heading", { name: "Documentation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "How roadmodel works" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Rating scale" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Benchmarks" }),
  ).toBeVisible();
  // The #ratings anchor target exists — the rationale's tier links point here.
  await expect(page.locator("#ratings")).toBeVisible();
  // Each benchmark links to its verified source (new tab).
  const swebench = page
    .getByRole("link", { name: "SWE-bench Verified" })
    .first();
  await expect(swebench).toHaveAttribute("href", "https://www.swebench.com/");
  await expect(swebench).toHaveAttribute("target", "_blank");
});
