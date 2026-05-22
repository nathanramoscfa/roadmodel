// web/tests/roadmap-shell.spec.ts
import { test, expect } from "@playwright/test";

import {
  resetE2eState,
  setE2eSessionCookie,
} from "./fixtures/onboarding-auth";

const COMPOSER_PLACEHOLDER =
  /Describe your project\. Paste, type, or attach anything\./i;

test("anonymous visitor can type without triggering the soft wall", async ({
  page,
}) => {
  await resetE2eState(page);
  await page.goto("/roadmap");
  await page.getByPlaceholder(COMPOSER_PLACEHOLDER).fill("my side project");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page).toHaveURL(/\/roadmap$/);
});

test(
  "anonymous send shows soft wall; Cancel keeps text; Sign in redirects",
  async ({ page }) => {
    await resetE2eState(page);
    await page.goto("/roadmap");
    const textarea = page.getByPlaceholder(COMPOSER_PLACEHOLDER);
    await textarea.fill("launch a SaaS MVP");
    await page.getByRole("button", { name: /Send/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText(
        /Sign in to send your message\. Your text stays right where you typed it\./i,
      ),
    ).toBeVisible();

    await dialog.getByRole("button", { name: /Cancel/i }).click();
    await expect(dialog).toHaveCount(0);
    await expect(textarea).toHaveValue("launch a SaaS MVP");

    await page.getByRole("button", { name: /Send/i }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("link", { name: /Sign in/i }).click();
    await expect(page).toHaveURL(/\/login\?next=(\/|%2F)roadmap/);
  },
);

test(
  "signed-in send passes through without triggering the soft wall",
  async ({ page }) => {
    await resetE2eState(page);
    await setE2eSessionCookie(page);
    // Mock /api/roadmap so the test doesn't depend on a live
    // Gemini call. The full streaming + draft contract is
    // covered by roadmap-flow.spec.ts; this test only asserts
    // the signed-in pass-through behavior (no SoftSignupWall).
    await page.route("**/api/roadmap", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
        },
        body:
          `data: ${JSON.stringify({
            type: "message_delta",
            delta: "Thanks — quick question first.",
          })}\n\n` +
          `data: ${JSON.stringify({
            type: "message_complete",
            content: "Thanks — quick question first.",
          })}\n\n`,
      }),
    );
    await page.goto("/roadmap");
    await page
      .getByPlaceholder(COMPOSER_PLACEHOLDER)
      .fill("build an analytics dashboard");
    await page.getByRole("button", { name: /Send/i }).click();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(
      page.getByText(/quick question first/i),
    ).toBeVisible({ timeout: 5_000 });
  },
);

test("narrow viewport tab switcher toggles chat and preview panels", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/roadmap");

  await expect(
    page.getByRole("tab", { name: /Chat/i }),
  ).toBeVisible();
  await expect(
    page.getByRole("tab", { name: /Preview/i }),
  ).toBeVisible();
  await expect(page.getByPlaceholder(COMPOSER_PLACEHOLDER)).toBeVisible();
  await expect(
    page.getByText(/Project overview will appear here/i),
  ).toBeHidden();

  await page.getByRole("tab", { name: /Preview/i }).click();
  await expect(page.getByPlaceholder(COMPOSER_PLACEHOLDER)).toBeHidden();
  await expect(
    page.getByText(/Project overview will appear here/i),
  ).toBeVisible();

  await page.getByRole("tab", { name: /Chat/i }).click();
  await expect(page.getByPlaceholder(COMPOSER_PLACEHOLDER)).toBeVisible();
  await expect(
    page.getByText(/Project overview will appear here/i),
  ).toBeHidden();
});
