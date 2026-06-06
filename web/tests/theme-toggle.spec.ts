// web/tests/theme-toggle.spec.ts
//
// T4 dark-mode mechanism. The visual palette is refined separately, but the
// mechanism is verifiable: the toggle flips the `dark` class on <html> and
// persists the choice, and the no-flash init script re-applies it on load.
// Default is light (no `dark` class) so the existing experience is unchanged.

import { test, expect } from "@playwright/test";

const isDark = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.documentElement.classList.contains("dark"));
const stored = (page: import("@playwright/test").Page) =>
  page.evaluate(() => localStorage.getItem("theme"));

test("theme toggle flips the <html> dark class and persists the choice", async ({
  page,
}) => {
  await page.goto("/recommend");
  // Default light.
  expect(await isDark(page)).toBe(false);

  await page.getByRole("button", { name: /Switch to dark theme/i }).click();
  expect(await isDark(page)).toBe(true);
  expect(await stored(page)).toBe("dark");

  await page.getByRole("button", { name: /Switch to light theme/i }).click();
  expect(await isDark(page)).toBe(false);
  expect(await stored(page)).toBe("light");
});

test("persisted dark theme is re-applied on next load (no-flash script)", async ({
  page,
}) => {
  await page.goto("/recommend");
  await page.evaluate(() => localStorage.setItem("theme", "dark"));
  await page.reload();
  expect(await isDark(page)).toBe(true);
});
