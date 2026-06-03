// web/tests/onboarding.spec.ts
//
// Phase 4 Step 2 — profile onboarding flow. Uses the ROADMODEL_E2E_AUTH
// test harness (see web/lib/auth.ts) because CI runs against placeholder
// Supabase credentials and cannot drive a live magic-link round-trip.

import { test, expect } from "@playwright/test";

import {
  resetE2eState,
  signInViaCallback,
} from "./fixtures/onboarding-auth";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetE2eState(page);
});

test("first-time signed-in user lands on /onboarding", async ({ page }) => {
  await signInViaCallback(page);
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(
    page.getByRole("heading", { name: /Tell us about your setup/i }),
  ).toBeVisible();
});

test("save-and-continue persists prefs and surfaces budget priority", async ({
  page,
}) => {
  await signInViaCallback(page);
  await page.getByLabel(/Claude Max \(\$200\)/i).check();
  await page.getByLabel(/Cursor Ultra/i).check();
  await page.getByRole("radio", { name: /^Best$/i }).check();

  const savePromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/api/profile") &&
      resp.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: /Save and continue/i }).click();
  const saveResponse = await savePromise;
  const profile = await saveResponse.json();
  expect(profile.subscriptions).toEqual(["claude-max", "cursor-ultra"]);
  expect(profile.budget_priority).toBe("best");
  expect(profile.onboarded_at).toBeTruthy();
  await expect(page).toHaveURL("/");

  await page.goto("/recommend");
  await page
    .getByPlaceholder(/Describe the task/i)
    .fill("profile onboarding smoke");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByRole("heading", { name: /Claude 4\.5 Haiku/i }),
  ).toBeVisible();
  await page.getByText(/Why this model/i).click();
  await expect(
    page.locator("details p").filter({ hasText: /Budget priority: best/i }),
  ).toBeVisible();
});

test("skip persists defaults and sets onboarded_at", async ({ page }) => {
  await signInViaCallback(page);
  const savePromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/api/profile") &&
      resp.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: /Skip for now/i }).click();
  const saveResponse = await savePromise;
  const profile = await saveResponse.json();
  expect(profile.subscriptions).toEqual([]);
  expect(profile.budget_priority).toBe("balanced");
  expect(profile.allowed_jurisdictions).toEqual([
    "us",
    "eu",
    "uk",
    "ca",
    "au",
    "jp",
    "kr",
  ]);
  expect(profile.onboarded_at).toBeTruthy();
  await expect(page).toHaveURL("/");
});

test("already-onboarded user signing in again lands on /", async ({
  page,
}) => {
  await signInViaCallback(page);
  await page.getByRole("button", { name: /Skip for now/i }).click();
  await expect(page).toHaveURL("/");

  await page.context().clearCookies();
  await signInViaCallback(page);
  await expect(page).toHaveURL("/");
  await expect(page).not.toHaveURL(/\/onboarding/);
});

test("default-restrict path excludes Kimi K2.5 from recommendations", async ({
  page,
}) => {
  await signInViaCallback(page);
  await page.getByRole("button", { name: /Save and continue/i }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/recommend");
  await page.getByPlaceholder(/Describe the task/i).fill("restrict cn");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByRole("heading", { name: /Claude 4\.5 Haiku/i }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: /Kimi K2\.5/i })).toHaveCount(
    0,
  );
});

test("widen path includes cn and surfaces Kimi K2.5", async ({ page }) => {
  await signInViaCallback(page);
  await page.getByText(/Advanced: jurisdiction filter/i).click();
  await page
    .getByLabel(/Restrict to low-risk jurisdictions/i)
    .uncheck();
  await page.getByLabel(/China \(cn\)/i).check();
  await page.getByRole("button", { name: /Save and continue/i }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/recommend");
  await page.getByPlaceholder(/Describe the task/i).fill("allow cn");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByRole("heading", { name: /Kimi K2\.5/i }),
  ).toBeVisible();
});

test.describe("profile API", () => {
  test("signed-out PATCH /api/profile returns 401", async ({ request }) => {
    const response = await request.patch("/api/profile", {
      data: { skip: true },
      failOnStatusCode: false,
    });
    expect(response.status()).toBe(401);
  });
});
