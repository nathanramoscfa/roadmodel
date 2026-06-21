// web/tests/nav.spec.ts
//
// Issue #153 — global navigation on the signed-in app surfaces. The nav is
// a client component gated on the route (usePathname), so it appears on the
// app surfaces and is absent on marketing/auth chrome.

import { test, expect } from "@playwright/test";

import {
  resetE2eState,
  signInViaCallback,
} from "./fixtures/onboarding-auth";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetE2eState(page);
});

test("app nav appears on /recommend and links between surfaces", async ({
  page,
}) => {
  await signInViaCallback(page);
  await page.goto("/recommend");

  const nav = page.getByRole("navigation", { name: /Primary/i });
  await expect(nav).toBeVisible();
  await expect(nav.getByRole("link", { name: /^Recommend$/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /^Models$/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /^Roadmap$/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: /^History$/ })).toBeVisible();
  await expect(nav.getByRole("button", { name: /Sign out/i })).toBeVisible();

  // Cross-surface navigation (the dead-end this fixes).
  await nav.getByRole("link", { name: /^Settings$/ }).click();
  await expect(page).toHaveURL(/\/settings/);
  await expect(
    page.getByRole("heading", { name: /^Settings$/i }),
  ).toBeVisible();
});

test("app nav is absent on the marketing home page", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("navigation", { name: /Primary/i }),
  ).toHaveCount(0);
});
