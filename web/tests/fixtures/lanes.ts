// web/tests/fixtures/lanes.ts
//
// /recommend shows a signed-out visitor the lane chooser first, on Quick pick
// (components/LaneChooser.tsx). The free-text specs choose a lane before they
// write a task. The click retries until the page has hydrated and the lane's
// view is up, since a click before hydration changes nothing.
import { expect, type Page } from "@playwright/test";

export async function chooseLane(page: Page, lane: "key" | "openrouter" | "agent" | "quick", shows: string): Promise<void> {
  await expect(async () => {
    await page.getByTestId(`lane-${lane}`).click();
    await expect(page.getByTestId(shows)).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
}

// The free-text composer with the key panel open: "Use your own API key".
export async function openFreeText(page: Page): Promise<void> {
  await page.goto("/recommend");
  await chooseLane(page, "key", "recommend-composer");
}
