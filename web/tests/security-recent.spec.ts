import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { loadRecent, saveRecent, RECENT_KEY, type RecentRun } from "../lib/recent-recommendations";
import { openFreeText } from "./fixtures/lanes";
import { E2E_AUTH_COOKIE } from "./fixtures/onboarding-auth";

const fixture = readFileSync(path.join(__dirname, "fixtures/recommend-response.json"), "utf8");
const run = (): RecentRun => ({ id: "fixture-id", at: Date.now(), task: "synthetic remembered task", data: JSON.parse(fixture) });

test("recent storage validates a real cost response and refuses malformed, oversized or foreign data", () => {
  let raw: string | null = null;
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    getItem: () => raw, setItem: (_key: string, value: string) => { raw = value; }, removeItem: () => { raw = null; },
  } } });
  try {
    expect(saveRecent("owner-a", [run()])).toHaveLength(1);
    expect(loadRecent("owner-a")).toHaveLength(1);
    expect(loadRecent("owner-b")).toEqual([]); expect(raw).toBeNull();
    for (const invalid of [
      { ...run(), at: "yesterday" }, { ...run(), id: null },
      { ...run(), data: { primary: "balanced", recommendations: [null] } },
      { ...run(), task: "x".repeat(600000) },
    ]) {
      raw = JSON.stringify({ version: 1, owner: "owner-a", runs: [invalid] });
      expect(loadRecent("owner-a")).toEqual([]);
    }
    raw = JSON.stringify({ version: 1, owner: "owner-a", runs: Array.from({ length: 9 }, run) });
    expect(loadRecent("owner-a")).toEqual([]);
    raw = JSON.stringify([run()]); expect(loadRecent("owner-a")).toEqual([]);
    const extended = { ...run(), data: { ...run().data, visitor_key: "synthetic-hidden-field" } };
    saveRecent("owner-a", [extended]); expect(raw).not.toContain("synthetic-hidden-field");
    Object.defineProperty(window.localStorage, "setItem", { value: () => { throw new Error("quota"); } });
    expect(saveRecent("owner-a", [run()])).toHaveLength(1);
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous); else Reflect.deleteProperty(globalThis, "window");
  }
});

test("account switches and signout clear recent history even between two signed-in users", async ({ page }) => {
  const account = async (value: string) => page.context().addCookies([{ name: E2E_AUTH_COOKIE, value, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await account("00000000-0000-4000-8000-000000000061");
  await page.route("**/api/recommend", (route) => route.fulfill({ status: 200, contentType: "application/json", body: fixture }));
  await openFreeText(page);
  await page.getByPlaceholder(/Describe the task/i).fill("synthetic account A task");
  await page.getByRole("button", { name: /^Recommend/ }).click();
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  await account("00000000-0000-4000-8000-000000000062"); await page.reload();
  await expect(page.getByTestId("recent-recommendations")).toHaveCount(0);
  expect(await page.evaluate((key) => localStorage.getItem(key), RECENT_KEY)).toBeNull();
  await openFreeText(page);
  await page.getByPlaceholder(/Describe the task/i).fill("synthetic account B task");
  await page.getByRole("button", { name: /^Recommend/ }).click();
  await expect(page.getByTestId("recent-recommendations")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate((key) => localStorage.getItem(key), RECENT_KEY)).toBeNull();
  expect((await page.context().cookies()).some((cookie) => cookie.name === E2E_AUTH_COOKIE)).toBe(false);
});

test("cross-tab saves preserve drafts; clearing invalidates a delayed result", async ({ page, context }) => {
  await openFreeText(page);
  const other = await context.newPage(); await openFreeText(other);
  await other.getByPlaceholder(/Describe the task/i).fill("keep this draft");
  await page.evaluate(({ key, data }) => {
    localStorage.setItem(key, JSON.stringify({ version: 1, owner: "anonymous", runs: [data] }));
  }, { key: RECENT_KEY, data: run() });
  await expect(other.getByTestId("recent-recommendations")).toBeVisible();
  await expect(other.getByPlaceholder(/Describe the task/i)).toHaveValue("keep this draft");
  let release!: () => void;
  let received!: () => void;
  const requestStarted = new Promise<void>((resolve) => { received = resolve; });
  const paused = new Promise<void>((resolve) => { release = resolve; });
  await other.route("**/api/recommend", async (route) => {
    received(); await paused;
    await route.fulfill({ status: 200, contentType: "application/json", body: fixture }).catch(() => {});
  });
  await other.getByRole("button", { name: /^Recommend/ }).click(); await requestStarted;
  await page.evaluate((key) => localStorage.removeItem(key), RECENT_KEY);
  await expect(other.getByTestId("recent-recommendations")).toHaveCount(0);
  release();
  await expect(other.getByPlaceholder(/Describe the task/i)).toHaveValue("");
  await expect(other.getByTestId("recommend-result")).toHaveCount(0);
  expect(await other.evaluate((key) => localStorage.getItem(key), RECENT_KEY)).toBeNull();
  await other.close();
});
