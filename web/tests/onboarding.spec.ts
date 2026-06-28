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
  await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
  await page.getByLabel(/Cursor Ultra/i).check();
  await page.getByRole("radio", { name: /^Quality$/i }).check();

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

  // /recommend now shows all three priority cards per submit, with the saved
  // emphasis (Quality = "best") highlighted. Mock the fan-out at the browser
  // level (the real route's 3 parallel upstream calls are verified in prod, and
  // the in-process E2E self-fetch is too slow to run 3× under CI). The mock
  // mirrors what the real edge emits: a per-card "Budget priority: X" rationale
  // and primary = the user's saved priority.
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        primary: "best",
        recommendations: [
          { priority: "cheap", model: "Claude 4.5 Haiku", platform: "Claude Code", settings: { rationale: "Budget priority: cheap." }, comparison_table: [] },
          { priority: "balanced", model: "GPT-5.4", platform: "Codex", settings: { rationale: "Budget priority: balanced." }, comparison_table: [] },
          { priority: "best", model: "Claude Opus 4.8", platform: "Claude Code", settings: { rationale: "Chosen for deep reasoning. Budget priority: best." }, comparison_table: [] },
        ],
      }),
    }),
  );
  await page.goto("/recommend");
  await page
    .getByPlaceholder(/Input the prompt/i)
    .fill("profile onboarding smoke");
  await page.getByRole("button", { name: /Submit/i }).click();
  // The saved emphasis (best) is the highlighted/default card; scope to it.
  const qualityCard = page.locator('[data-priority="best"]');
  await expect(qualityCard.getByText("Default")).toBeVisible();
  await expect(
    qualityCard.getByRole("heading", { name: /Claude Opus 4\.8/i }),
  ).toBeVisible();
  // The rationale renders prominently (T4 — an always-visible "Why this model?"
  // card, no longer a collapsed <details> behind a click), carrying the per-card
  // budget priority (#173).
  const why = qualityCard.getByRole("region", { name: /Why this model/i });
  await expect(why).toBeVisible();
  await expect(why.getByText(/Budget priority: best/i)).toBeVisible();
});

test("renders a consistent monthly price for every subscription tier", async ({
  page,
}) => {
  await signInViaCallback(page);
  // A unique-name tier shows its price...
  await expect(page.getByLabel(/Cursor Ultra.*\$200\/mo/i)).toBeVisible();
  // ...and the two duplicate-name "Claude Max" tiers are disambiguated by
  // the price column, not a parenthetical in the name.
  await expect(page.getByLabel(/Claude Max.*\$100\/mo/i)).toBeVisible();
  await expect(page.getByLabel(/Claude Max.*\$200\/mo/i)).toBeVisible();
  // No parenthetical "($NNN)" price leaks into any label anymore.
  await expect(page.getByText(/\(\$\d/)).toHaveCount(0);
  // The price column is monthly-only for every tier — even the seeded annual
  // plan (Claude Pro) shows just "$20/mo"; no "/yr" or "save Z%" leaks into any
  // label anymore (annual display was removed as inconsistent across tiers).
  await expect(page.getByLabel(/Claude Pro.*\$20\/mo/i)).toBeVisible();
  await expect(page.getByText(/\/yr/i)).toHaveCount(0);
  await expect(page.getByText(/save \d/i)).toHaveCount(0);
});

test("captures API-access providers and persists them (Phase 4.8)", async ({
  page,
}) => {
  await signInViaCallback(page);
  // The catalog-derived "API access" section renders...
  await expect(page.getByText("API access")).toBeVisible();
  await expect(page.getByLabel("DeepSeek")).toBeVisible();
  // ...and the selected providers persist on save.
  await page.getByLabel("DeepSeek").check();
  await page.getByLabel("Anthropic").check();

  const savePromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/api/profile") &&
      resp.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: /Save and continue/i }).click();
  const profile = await (await savePromise).json();
  expect([...profile.api_providers].sort()).toEqual(["anthropic", "deepseek"]);
  await expect(page).toHaveURL("/");
});

test("forwards held subscriptions + enabled API providers to the recommender (Phase 4.8 T2b)", async ({
  page,
}) => {
  await signInViaCallback(page);
  // Declare a held subscription AND an enabled API provider.
  await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
  await page.getByLabel("DeepSeek").check();
  await page.getByRole("button", { name: /Save and continue/i }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("forwarding smoke");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByRole("heading", { name: /Claude 4\.5 Haiku/i }),
  ).toBeVisible();
  // The edge now forwards the user's declared funding to the service; the E2E
  // mock echoes it back, proving subscriptions + api_providers reach the upstream
  // (where the real service builds the per-user user-context that biases model
  // SELECTION). The lowercase ids appear ONLY in the echo — the T2a edge note
  // uses the display label "Claude Max", so matching "claude-max"/"deepseek"
  // specifically confirms the forwarded payload.
  const why = page.getByRole("region", { name: /Why this model/i });
  await expect(why).toContainText("Forwarded funding");
  await expect(why).toContainText("claude-max");
  await expect(why).toContainText("deepseek");
});

test("cost table is personalized to the signed-in user's funding (Phase 4.8 T3)", async ({
  page,
}) => {
  await signInViaCallback(page);
  await page.getByLabel(/Claude Max.*\$200\/mo/i).check();
  await page.getByRole("button", { name: /Save and continue/i }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("personalized cost table");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByRole("heading", { name: /Claude 4\.5 Haiku/i }),
  ).toBeVisible();
  // The cost table reflects THIS user's funding, not the bundled founder
  // context: the column is "Your cost" and the Claude Code row is $0 via the
  // user's held Claude Max subscription.
  await expect(
    page.getByRole("columnheader", { name: "Your cost" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: /\$0 · Claude Max/i }),
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
  await page.getByPlaceholder(/Input the prompt/i).fill("restrict cn");
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
  await page.getByPlaceholder(/Input the prompt/i).fill("allow cn");
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
