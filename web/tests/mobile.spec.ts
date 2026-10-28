// web/tests/mobile.spec.ts
//
// The phone pass, run by the `iphone` project (WebKit at an iPhone 15's
// viewport; playwright.config.ts). No route scrolls sideways at any phone
// width; the nav folds behind a Menu button; the models table scrolls sideways
// in its own box with the model column pinned; the comparison matrix becomes
// one card per pick; fields read 16px, so iOS Safari doesn't zoom on focus.

import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect, type Page } from "@playwright/test";

import { openFreeText } from "./fixtures/lanes";
import { resetE2eState, signInViaCallback } from "./fixtures/onboarding-auth";

const PUBLIC_ROUTES = ["/", "/recommend", "/recommend/openrouter", "/docs", "/login", "/gate", "/privacy", "/terms"];
const SIGNED_IN_ROUTES = ["/onboarding", "/settings", "/history", "/roadmap"];
// The narrowest and widest iPhones in use, around the project's own 393.
const WIDTHS = [375, 430];
const FIXTURE = readFileSync(path.join(__dirname, "fixtures", "recommend-response.json"), "utf8");

async function pageWidths(page: Page) {
  return page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
}

async function expectNoSidewaysScroll(page: Page, where: string) {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 812 });
    const w = await pageWidths(page);
    expect(w.scroll, `${where} at ${width}px`).toBeLessThanOrEqual(w.client);
  }
}

async function heightOf(page: Page, selector: ReturnType<Page["locator"]>) {
  return (await selector.boundingBox())!.height;
}

for (const route of PUBLIC_ROUTES) {
  test(`${route} never scrolls sideways on a phone`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await expectNoSidewaysScroll(page, route);
  });
}

test("signed-in pages never scroll sideways on a phone", async ({ page }) => {
  await resetE2eState(page);
  await signInViaCallback(page);
  for (const route of SIGNED_IN_ROUTES) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await expectNoSidewaysScroll(page, route);
  }
});

test("the nav folds behind a Menu button and opens as full-width rows", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: /Primary/i });
  const toggle = nav.getByTestId("nav-menu-toggle");
  const links = nav.getByTestId("nav-links");
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(links).toBeHidden();
  expect(await heightOf(page, toggle)).toBeGreaterThanOrEqual(44);
  // The closed nav is one row: brand, theme, sign-out, menu.
  expect(await heightOf(page, nav)).toBeLessThan(80);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(links).toBeVisible();
  const items = links.getByRole("link");
  const navBox = (await nav.boundingBox())!;
  for (const link of await items.all()) {
    const box = (await link.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.width).toBeGreaterThan(navBox.width * 0.8);
  }
  const w = await pageWidths(page);
  expect(w.scroll).toBeLessThanOrEqual(w.client);

  // Following a link closes the menu.
  await links.getByRole("link", { name: /^Docs$/ }).click();
  await expect(page).toHaveURL(/\/docs$/);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(links).toBeHidden();
});

test("the models table scrolls sideways in its own box with the model column pinned", async ({ page }) => {
  await page.goto("/");
  const box = page.getByTestId("catalog-scroll");
  await box.scrollIntoViewIfNeeded();
  const sizes = await box.evaluate((el) => ({
    scrollW: el.scrollWidth,
    clientW: el.clientWidth,
    scrollH: el.scrollHeight,
    clientH: el.clientHeight,
  }));
  // Wider than the phone: it scrolls sideways inside the box…
  expect(sizes.scrollW).toBeGreaterThan(sizes.clientW);
  // …but not up and down: the page scrolls the rows, so no box traps the thumb.
  expect(sizes.scrollH).toBeLessThanOrEqual(sizes.clientH + 1);

  // Scrolled to the far right, the model column stays at the box's left edge.
  const firstName = page.getByTestId("model-row").first().locator("td").nth(1);
  await firstName.scrollIntoViewIfNeeded();
  const boxLeft = (await box.boundingBox())!.x;
  await box.evaluate((el) => el.scrollTo({ left: el.scrollWidth }));
  await expect.poll(async () => Math.abs((await firstName.boundingBox())!.x - boxLeft)).toBeLessThanOrEqual(2);
  await expect(firstName).toBeInViewport();
  const w = await pageWidths(page);
  expect(w.scroll).toBeLessThanOrEqual(w.client);
});

test("a recommendation reads as one card per pick, switched by tabs", async ({ page }) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: FIXTURE }),
  );
  await openFreeText(page);
  await page.getByPlaceholder(/Describe the task/i).fill("build a SQL agent");
  await page.getByRole("button", { name: /^Recommend/ }).click();
  const tabs = page.getByTestId("picks-segmented").getByRole("tab");
  await expect(tabs).toHaveCount(3);
  await expect(page.getByTestId("picks-matrix")).toBeHidden();
  for (const tab of await tabs.all()) {
    expect(await heightOf(page, tab)).toBeGreaterThanOrEqual(44);
  }
  await tabs.first().click();
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
  await expectNoSidewaysScroll(page, "/recommend with a result");
});

test("fields read 16px so iOS Safari doesn't zoom on focus", async ({ page }) => {
  for (const [route, field] of [
    ["/", page.getByRole("searchbox", { name: /Search models/i })],
    ["/login", page.locator('input[type="email"]')],
    ["/gate", page.locator('input[type="password"]')],
  ] as const) {
    await page.goto(route);
    const size = await field.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(size, route).toBeGreaterThanOrEqual(16);
    const box = (await field.boundingBox())!;
    expect(box.height, route).toBeGreaterThanOrEqual(44);
  }
});
