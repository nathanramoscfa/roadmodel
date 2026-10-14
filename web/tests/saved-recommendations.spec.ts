// web/tests/saved-recommendations.spec.ts
//
// Saved recommendations live only in the browser (lib/saved-store.ts): one
// list per account, kept across sign-outs unless the visitor removes them,
// checked on every write, read and import, and carried between browsers only
// by an export file. The first tests check the entry and file formats without
// a browser; the rest drive /recommend.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  EXPORT_FORMAT,
  LEGACY_KEY,
  MAX_SAVED,
  exportFile,
  legacyRuns,
  parseImport,
  toSaved,
  type SavedRun,
} from "../lib/saved-recommendations";
import { chooseLane, openFreeText } from "./fixtures/lanes";
import { E2E_AUTH_COOKIE } from "./fixtures/onboarding-auth";
import { storedRows } from "./fixtures/saved";

const fixture = readFileSync(path.join(__dirname, "fixtures/recommend-response.json"), "utf8");
const engineRun = (id = "fixture-id", task = "synthetic remembered task"): SavedRun => ({
  kind: "engine", id, at: Date.now(), task, data: JSON.parse(fixture),
});
const rung = (priority: string, model: string) => ({
  priority, model_id: model.toLowerCase().replace(/ /g, "-"), model_name: model, platform_id: "synthetic-api",
  platform_name: "Synthetic API", effort: "medium", specialist: false, backup: null,
  terms: { quality: 0.8, requirement_shortfall: 0, cost: 0.2 },
  why: { quality: "Strong on the benchmarks.", requirement_shortfall: "Meets the task.", cost: "Cheap enough." },
});
const QUICK = {
  rungs: [rung("quality", "Synthetic Strong"), rung("balanced", "Synthetic Middle"), rung("cost", "Synthetic Cheap")],
  task: { category: "coding", complexity: "medium", novel: false, budget_priority: "balanced" },
  backup_warning: null, engine: "scoring-core", cost_usd: 0,
};
const quickRun = (id = "quick-id"): SavedRun =>
  ({ kind: "quick", id, at: Date.now(), task: "Coding · Medium difficulty", data: QUICK }) as SavedRun;

const ACCOUNT_A = "00000000-0000-4000-8000-000000000061";
const ACCOUNT_B = "00000000-0000-4000-8000-000000000062";

async function signIn(page: Page, id: string) {
  await page.context().addCookies([{ name: E2E_AUTH_COOKIE, value: id, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax" }]);
}

async function recommend(page: Page, task: string) {
  await page.getByPlaceholder(/Describe the task/i).fill(task);
  await page.getByRole("button", { name: /^Recommend/ }).click();
  await expect(page.getByTestId("recommend-result")).toBeVisible();
}

async function signOut(page: Page, removeSaved = false) {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  if (removeSaved) await page.getByLabel(/Remove all saved recommendations/).check();
  await page.getByRole("button", { name: "Sign out now" }).click();
  await expect(page).toHaveURL(/\/$/);
}

function fileFrom(content: string, name = "saved.json") {
  return { name, mimeType: "application/json", buffer: Buffer.from(content) };
}

// The import control, once the page has hydrated: retried until it reports.
async function importFile(page: Page, content: string, reports: string) {
  await expect(async () => {
    await page.getByTestId("saved-import-file").setInputFiles(fileFrom(content));
    await expect(page.getByTestId("saved-status")).toHaveText(reports, { timeout: 2_000 });
  }).toPass({ timeout: 15_000 });
}

test("saved entries keep only known fields and refuse malformed or oversized ones", () => {
  expect(toSaved(engineRun())).not.toBeNull();
  expect(toSaved(quickRun())).not.toBeNull();
  for (const invalid of [
    { ...engineRun(), at: "yesterday" },
    { ...engineRun(), id: null },
    { ...engineRun(), kind: undefined },
    { ...engineRun(), data: { primary: "balanced", recommendations: [null] } },
    { ...engineRun(), task: "x".repeat(60_000) },
    { ...quickRun(), data: { ...QUICK, rungs: [...QUICK.rungs].reverse() } },
  ]) {
    expect(toSaved(invalid)).toBeNull();
  }
  const sections = Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`s${i}`, "y".repeat(40_000)]));
  const big = engineRun();
  if (big.kind === "engine") big.data.recommendations[0].rationale_sections = sections;
  expect(toSaved(big)).toBeNull();
  const extended = { ...engineRun(), data: { ...engineRun().data, visitor_key: "synthetic-hidden-field" } };
  expect(JSON.stringify(toSaved(extended))).not.toContain("synthetic-hidden-field");
});

test("an export file reads back whole; anything else is refused", () => {
  const file = exportFile([engineRun("a"), quickRun("b")], new Date("2026-10-14T00:00:00Z"));
  expect(JSON.parse(file)).toMatchObject({ format: EXPORT_FORMAT, version: 1, exported_at: "2026-10-14T00:00:00.000Z" });
  const back = parseImport(file);
  expect(back?.runs.map((r) => [r.kind, r.id])).toEqual([["engine", "a"], ["quick", "b"]]);
  expect(back?.skipped).toBe(0);

  const withBad = JSON.parse(file) as { runs: unknown[] };
  withBad.runs.push({ kind: "engine", id: "bad" });
  expect(parseImport(JSON.stringify(withBad))?.skipped).toBe(1);

  for (const other of [
    "not json",
    "[]",
    JSON.stringify({ format: "something-else", version: 1, runs: [] }),
    JSON.stringify({ format: EXPORT_FORMAT, version: 2, runs: [] }),
    JSON.stringify({ format: EXPORT_FORMAT, version: 1, runs: Array.from({ length: MAX_SAVED + 1 }, () => engineRun()) }),
  ]) {
    expect(parseImport(other)).toBeNull();
  }
});

test("the old localStorage list is taken over by its own account, or by anyone when it had none", () => {
  const run = { id: "legacy", at: Date.now(), task: "legacy task", data: JSON.parse(fixture) };
  expect(legacyRuns(JSON.stringify([run]), "anyone")?.map((r) => [r.kind, r.id])).toEqual([["engine", "legacy"]]);
  const envelope = JSON.stringify({ version: 1, owner: ACCOUNT_A, runs: [run] });
  expect(legacyRuns(envelope, ACCOUNT_A)).toHaveLength(1);
  expect(legacyRuns(envelope, ACCOUNT_B)).toBeNull();
  expect(legacyRuns("garbage", ACCOUNT_A)).toEqual([]);
  expect(legacyRuns(null, ACCOUNT_A)).toBeNull();
});

test("each account sees only its own list; signing out keeps it unless the visitor removes it", async ({ page }) => {
  await page.route("**/api/recommend", (route) => route.fulfill({ status: 200, contentType: "application/json", body: fixture }));
  const saved = page.getByTestId("saved-recommendations");

  await signIn(page, ACCOUNT_A);
  await openFreeText(page);
  await recommend(page, "synthetic account A task");
  await expect(saved).toContainText("synthetic account A task");

  await signIn(page, ACCOUNT_B);
  await openFreeText(page);
  await expect(saved).not.toContainText("synthetic account A task");
  await recommend(page, "synthetic account B task");
  await expect(saved).toContainText("synthetic account B task");
  await expect.poll(async () => (await storedRows(page)).map((r) => r.owner).sort()).toEqual([ACCOUNT_A, ACCOUNT_B]);

  await signIn(page, ACCOUNT_A);
  await openFreeText(page);
  await expect(saved).toContainText("synthetic account A task");
  await expect(saved).not.toContainText("synthetic account B task");

  await signOut(page);
  expect((await page.context().cookies()).some((cookie) => cookie.name === E2E_AUTH_COOKIE)).toBe(false);
  expect(await storedRows(page)).toHaveLength(2);
  await signIn(page, ACCOUNT_A);
  await openFreeText(page);
  await expect(saved).toContainText("synthetic account A task");

  await signOut(page, true);
  expect(await storedRows(page)).toEqual([]);
});

test("entries delete one at a time or all at once, and an export imports back", async ({ page }) => {
  await page.goto("/recommend");
  const saved = page.getByTestId("saved-recommendations");
  const three = [engineRun("one", "first saved task"), engineRun("two", "second saved task"), quickRun("three")];
  await importFile(page, exportFile(three, new Date()), "Imported 3 recommendations.");
  await expect(saved.getByTestId("saved-delete")).toHaveCount(3);
  await expect(saved).toContainText("Quick pick");

  await saved.getByRole("button", { name: "Delete “first saved task”" }).click();
  await expect(saved).not.toContainText("first saved task");
  await expect.poll(async () => (await storedRows(page)).length).toBe(2);

  const downloading = page.waitForEvent("download");
  await page.getByTestId("saved-export").click();
  const exported = readFileSync(await (await downloading).path()).toString("utf8");
  expect(parseImport(exported)?.runs.map((r) => r.id).sort()).toEqual(["three", "two"]);

  await saved.getByRole("button", { name: "Clear" }).click();
  await saved.getByRole("button", { name: "Remove all" }).click();
  await expect(saved.getByTestId("saved-delete")).toHaveCount(0);
  await expect.poll(async () => (await storedRows(page)).length).toBe(0);

  await importFile(page, exported, "Imported 2 recommendations.");
  await expect(saved).toContainText("second saved task");
  await page.reload();
  await expect(saved).toContainText("second saved task");

  await importFile(page, "not a roadmodel export", "That file is not a roadmodel export.");
  await expect(saved).toContainText("second saved task");
});

test("a Quick pick is saved and reopens without a new request", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/recommend/keyless", async (route) => {
    calls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(QUICK) });
  });
  await page.goto("/recommend");
  await expect(async () => {
    await page.getByTestId("quick-pick-submit").click();
    await expect(page.getByTestId("keyless-result")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 15_000 });
  const saved = page.getByTestId("saved-recommendations");
  await expect(saved).toContainText("Coding · Medium difficulty");
  await expect(saved).toContainText("Synthetic Cheap · Synthetic Middle · Synthetic Strong");

  await page.reload();
  await expect(page.getByTestId("quick-pick-form")).toBeVisible();
  await expect(async () => {
    await saved.getByRole("button", { name: /^Coding · Medium difficulty/ }).click();
    await expect(page.getByTestId("keyless-result")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 15_000 });
  await expect(page.getByTestId("keyless-task")).toHaveText("Coding · Medium difficulty");
  expect(calls).toBe(1);
});

test("the old localStorage list carries over once; another account's stays for them", async ({ page }) => {
  await page.goto("/recommend");
  const legacy = { id: "legacy-id", at: Date.now(), task: "a task from the old list", data: JSON.parse(fixture) };
  await page.evaluate(({ key, value }) => localStorage.setItem(key, value), { key: LEGACY_KEY, value: JSON.stringify([legacy]) });
  await page.reload();
  await expect(page.getByTestId("saved-recommendations")).toContainText("a task from the old list");
  expect(await page.evaluate((key) => localStorage.getItem(key), LEGACY_KEY)).toBeNull();
  expect((await storedRows(page)).map((r) => [r.owner, r.id])).toEqual([["anonymous", "legacy-id"]]);

  const foreign = JSON.stringify({ version: 1, owner: ACCOUNT_A, runs: [{ ...legacy, id: "foreign-id", task: "account A's old task" }] });
  await page.evaluate(({ key, value }) => localStorage.setItem(key, value), { key: LEGACY_KEY, value: foreign });
  await page.reload();
  await expect(page.getByTestId("saved-recommendations")).toContainText("a task from the old list");
  await expect(page.getByTestId("saved-recommendations")).not.toContainText("account A's old task");
  expect(await page.evaluate((key) => localStorage.getItem(key), LEGACY_KEY)).toBe(foreign);
  await signIn(page, ACCOUNT_A);
  await openFreeText(page);
  await expect(page.getByTestId("saved-recommendations")).toContainText("account A's old task");
  expect(await page.evaluate((key) => localStorage.getItem(key), LEGACY_KEY)).toBeNull();
});

test("tabs share the list; signing out in one tab drops another tab's draft and pending answer", async ({ page, context }) => {
  await signIn(page, ACCOUNT_A);
  await page.route("**/api/recommend", (route) => route.fulfill({ status: 200, contentType: "application/json", body: fixture }));
  await openFreeText(page);
  const other = await context.newPage();
  await openFreeText(other);

  await recommend(page, "saved in the first tab");
  await expect(other.getByTestId("saved-recommendations")).toContainText("saved in the first tab");

  let release!: () => void;
  let received!: () => void;
  const requestStarted = new Promise<void>((resolve) => { received = resolve; });
  const paused = new Promise<void>((resolve) => { release = resolve; });
  await other.route("**/api/recommend", async (route) => {
    received(); await paused;
    await route.fulfill({ status: 200, contentType: "application/json", body: fixture }).catch(() => {});
  });
  await other.getByPlaceholder(/Describe the task/i).fill("a pending task in the second tab");
  await other.getByRole("button", { name: /^Recommend/ }).click();
  await requestStarted;

  await signOut(page);
  // Reloaded as signed out: the chooser back on Quick pick, the draft gone.
  await expect(other.getByTestId("quick-pick-form")).toBeVisible();
  await expect(other.getByTestId("saved-recommendations")).not.toContainText("saved in the first tab");
  release();
  await expect(other.getByTestId("recommend-result")).toHaveCount(0);
  expect((await storedRows(other)).map((r) => r.task)).toEqual(["saved in the first tab"]);
  await other.close();
});

test("a saved free-text result opens from the Quick pick lane in its own lane", async ({ page }) => {
  await page.goto("/recommend");
  await importFile(page, exportFile([engineRun("e", "a written task")], new Date()), "Imported 1 recommendation.");
  await page.getByTestId("saved-recommendations").getByRole("button", { name: /^a written task/ }).click();
  await expect(page.getByTestId("recommend-result")).toBeVisible();
  await chooseLane(page, "quick", "quick-pick-form");
});
