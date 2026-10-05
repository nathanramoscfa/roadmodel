// web/tests/visitor-key-ui.spec.ts
//
// "Use your own API key" on /recommend, end to end against the E2E mock
// recommender (app/api/test/mock-recommend/visitor). The page holds the key in
// React state only (lib/use-visitor-key.ts). The guarantees under test:
//
// - the key leaves the page only as the X-Roadmodel-Visitor-Key header of a
//   /api/recommend request, never in its body;
// - after a recommendation and a "Run again", the key is in no cookie, no
//   localStorage and no sessionStorage entry, nor in the page's responses;
// - the engine menu is the key's provider's, priced to the key;
// - "Forget key" clears it, and the next request carries no key.
//
// Signed out, so the key is the only thing that can fund the request.
//
// The E2E server's Upstash is a placeholder: each limiter call retries for a
// few seconds before the lane fails open (lib/ratelimit.ts), so a request here
// takes several seconds. RUN is the wait for one.
const RUN = { timeout: 30_000 };

import { randomBytes } from "node:crypto";

import { test, expect, type Page, type Request } from "@playwright/test";

import registry from "../data/engines.json";
import { chooseLane } from "./fixtures/lanes";

// Assembled at runtime: no secret-shaped literal is committed.
function fakeKey(prefix: string, marker = "canary-0411"): string {
  return [prefix, marker, randomBytes(12).toString("hex")].join("-");
}

const task = (page: Page) => page.getByPlaceholder(/Describe the task/i);
const submit = (page: Page) => page.getByRole("button", { name: /^Recommend/ });

// Signed out, "Use your own API key" in the lane chooser opens the key panel.
async function enterKey(page: Page, provider: string, key: string) {
  await chooseLane(page, "key", "visitor-key-panel");
  await page.getByTestId("visitor-key-provider").selectOption(provider);
  await page.getByTestId("visitor-key-input").fill(key);
}

// Every /api/recommend request the page sends, and every response body.
function watch(page: Page) {
  const requests: Request[] = [];
  const bodies: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/recommend")) requests.push(r);
  });
  page.on("response", async (r) => {
    if (r.url().endsWith("/api/recommend")) bodies.push(await r.text().catch(() => ""));
  });
  return { requests, bodies };
}

// Every place the page could keep a value: cookies, both storages.
async function storedText(page: Page): Promise<string> {
  return page.evaluate(() => {
    const dump = (s: Storage) =>
      Array.from({ length: s.length }, (_, i) => {
        const k = s.key(i) ?? "";
        return `${k}=${s.getItem(k) ?? ""}`;
      }).join("\n");
    return [document.cookie, dump(window.localStorage), dump(window.sessionStorage)].join("\n");
  });
}

test("a visitor's key runs the recommendation, travels only as a header and is stored nowhere", async ({
  page,
  context,
}) => {
  // Three runs at the placeholder limiter's pace (RUN above).
  test.setTimeout(120_000);
  const canary = fakeKey("sk");
  const { requests, bodies } = watch(page);
  await page.goto("/recommend");
  await enterKey(page, "openai", canary);
  await expect(page.getByTestId("visitor-key-toggle")).toHaveText(/Your OpenAI key/);

  // The menu is the key's provider's engines, priced to the key.
  await page.getByTestId("engine-picker").click();
  const options = page.locator("[data-engine]");
  await expect(options.first()).toBeVisible();
  for (const hint of await options.evaluateAll((els) => els.map((e) => e.getAttribute("data-engine") ?? ""))) {
    expect(hint.startsWith("openai-")).toBe(true);
  }
  await expect(page.locator(`[data-engine="${registry.visitor_defaults.openai}"]`)).toContainText(
    /≈ \$[\d.]+ per recommendation, billed to your key/,
  );
  await page.keyboard.press("Escape");

  await task(page).fill("refactor a data pipeline");
  await submit(page).click();
  await expect(page.getByTestId("engine-line")).toContainText("billed to your key", RUN);

  // "Run again" reuses the same key holder.
  await page.getByTestId("rerun").click();
  await expect.poll(() => requests.length, RUN).toBe(2);
  await expect(page.getByTestId("rerun")).toBeEnabled(RUN);

  for (const r of requests) {
    expect(r.headers()["x-roadmodel-visitor-key"]).toBe(canary);
    expect(r.headers()["x-roadmodel-visitor-provider"]).toBe("openai");
    expect(r.postData() ?? "").not.toContain(canary);
  }
  await expect.poll(() => bodies.length, RUN).toBe(2);
  for (const body of bodies) {
    expect(body).not.toContain(canary);
    // The mock saw the key in its header and nowhere in the body it was sent.
    const recs = (JSON.parse(body) as { recommendations: Record<string, unknown>[] }).recommendations;
    expect(recs[0]).toMatchObject({ visitor_key_header: true, visitor_key_in_body: false });
  }

  expect(await storedText(page)).not.toContain(canary);
  for (const cookie of await context.cookies()) {
    expect(cookie.value).not.toContain(canary);
  }
  // The recent-recommendations store kept the result, without the key.
  expect(await page.evaluate(() => window.localStorage.getItem("roadmodel:recommend-recent"))).toBeTruthy();

  // Forget key, from the result: the next request has no key, and the
  // composer's field is empty.
  await expect(page.getByTestId("visitor-key-status")).toContainText("OpenAI key");
  await page.getByTestId("visitor-key-status-forget").click();
  await expect(page.getByTestId("visitor-key-status")).toHaveCount(0);
  await page.getByTestId("rerun").click();
  await expect.poll(() => requests.length, RUN).toBe(3);
  expect(requests[2].headers()["x-roadmodel-visitor-key"]).toBeUndefined();
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByTestId("visitor-key-toggle")).toHaveText(/Use your own API key/);
  // The panel is still open from before.
  await expect(page.getByTestId("visitor-key-input")).toHaveValue("");

  // The composer's own "Forget key" clears a key too.
  await page.getByTestId("visitor-key-input").fill(canary);
  await page.getByTestId("visitor-key-forget").click();
  await expect(page.getByTestId("visitor-key-input")).toHaveValue("");

  // A reload keeps nothing either.
  await page.reload();
  await chooseLane(page, "key", "visitor-key-panel");
  await expect(page.getByTestId("visitor-key-input")).toHaveValue("");
  expect(await storedText(page)).not.toContain(canary);
});

test("a declined key reads as what to do about it", async ({ page }) => {
  await page.goto("/recommend");
  await enterKey(page, "openai", fakeKey("sk", "declined"));
  await task(page).fill("pick a model");
  await submit(page).click();
  await expect(
    page.getByRole("alert").filter({
      hasText: "Your provider declined this key. Check it in your provider's console and paste it again.",
    }),
  ).toBeVisible(RUN);
});

test("a key without its provider's shape is explained before any request", async ({ page }) => {
  const { requests } = watch(page);
  await page.goto("/recommend");
  await enterKey(page, "anthropic", fakeKey("sk"));
  await expect(page.getByTestId("visitor-key-shape")).toHaveText(
    "Anthropic API keys begin with sk-ant-. Paste the whole key.",
  );
  await task(page).fill("pick a model");
  await submit(page).click();
  await expect(page.getByRole("alert").filter({ hasText: "Anthropic API keys begin with sk-ant-." })).toBeVisible();
  expect(requests).toHaveLength(0);
});
