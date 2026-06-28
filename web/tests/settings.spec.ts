// web/tests/settings.spec.ts
//
// Issue #154 — the /settings page lets a signed-in user edit the same
// preferences as onboarding, AFTER the one-shot onboarding has run. Uses
// the ROADMODEL_E2E_AUTH harness (see web/lib/auth.ts), like onboarding.spec.ts.

import { test, expect } from "@playwright/test";

import {
  resetE2eState,
  signInViaCallback,
} from "./fixtures/onboarding-auth";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetE2eState(page);
});

// Onboard first (subscriptions + budget), then settings must pre-fill them.
async function onboardWith(page: import("@playwright/test").Page) {
  await signInViaCallback(page);
  await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
  await page.getByLabel(/Cursor Ultra/i).check();
  await page.getByLabel("DeepSeek").check();
  await page.getByRole("radio", { name: /^Quality$/i }).check();
  await page.getByRole("button", { name: /Save and continue/i }).click();
  await expect(page).toHaveURL("/");
}

test("/settings pre-fills the saved preferences", async ({ page }) => {
  await onboardWith(page);
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: /^Settings$/i }),
  ).toBeVisible();
  await expect(page.getByLabel(/Claude Max.*\$200\/mo/i)).toBeChecked();
  await expect(page.getByLabel(/Cursor Ultra/i)).toBeChecked();
  await expect(page.getByLabel(/ChatGPT Pro.*\$200\/mo/i)).not.toBeChecked();
  // API-access selection (Phase 4.8) pre-fills too.
  await expect(page.getByLabel("DeepSeek")).toBeChecked();
  await expect(page.getByLabel("OpenAI")).not.toBeChecked();
  await expect(page.getByRole("radio", { name: /^Quality$/i })).toBeChecked();
});

test("/settings save PATCHes the profile and stays on the page", async ({
  page,
}) => {
  await onboardWith(page);
  await page.goto("/settings");

  // Drop one subscription, then save changes.
  await page.getByLabel(/Cursor Ultra/i).uncheck();
  const savePromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/api/profile") &&
      resp.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: /Save changes/i }).click();
  const profile = await (await savePromise).json();
  expect(profile.subscriptions).toEqual(["claude-max"]);
  // API-access selection survives a settings save untouched (Phase 4.8).
  expect(profile.api_providers).toEqual(["deepseek"]);
  expect(profile.budget_priority).toBe("best");

  // Settings stays put (no redirect) and confirms inline.
  await expect(page).toHaveURL(/\/settings/);
  await expect(page.getByText(/Preferences saved\./i)).toBeVisible();
});

test("pinning a priority as default on /recommend persists and Settings reflects it, without wiping subscriptions", async ({
  page,
}) => {
  // Onboard with a subscription + Balanced so we can prove the default-emphasis
  // change is a true MERGE (it must not reset subscriptions to defaults).
  await signInViaCallback(page);
  await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
  await page.getByRole("radio", { name: /^Balanced$/i }).check();
  await page.getByRole("button", { name: /Save and continue/i }).click();
  await expect(page).toHaveURL("/");

  // /recommend now shows all three priority cards per submit. Mock the recommend
  // fan-out at the browser level (so the REAL /api/profile merge below is still
  // exercised), submit, then pin Quality as the default via its card control.
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        primary: "balanced",
        recommendations: [
          { priority: "cheap", model: "Claude 4.5 Haiku", platform: "Claude Code", settings: {}, comparison_table: [] },
          { priority: "balanced", model: "GPT-5.4", platform: "Codex", settings: {}, comparison_table: [] },
          { priority: "best", model: "Claude Opus 4.8", platform: "Claude Code", settings: {}, comparison_table: [] },
        ],
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("build a SQL agent");
  await page.getByRole("button", { name: /Submit/i }).click();
  const qualityCard = page.locator('[data-priority="best"]');
  await expect(qualityCard).toBeVisible();

  const patchPromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/api/profile") &&
      resp.request().method() === "PATCH",
  );
  await qualityCard.getByRole("button", { name: /Set as default/i }).click();
  const profile = await (await patchPromise).json();
  expect(profile.budget_priority).toBe("best");
  // The merge preserves the subscription chosen at onboarding (issue: a
  // budget-only PATCH used to reset every other field to its default).
  expect(profile.subscriptions).toEqual(["claude-max"]);

  // The Quality card now leads with the Default badge (optimistic highlight).
  await expect(qualityCard.getByText("Default")).toBeVisible();

  // Settings reflects the change — no need to re-pick it there.
  await page.goto("/settings");
  await expect(page.getByRole("radio", { name: /^Quality$/i })).toBeChecked();
  await expect(page.getByLabel(/Claude Max.*\$200\/mo/i)).toBeChecked();
});
