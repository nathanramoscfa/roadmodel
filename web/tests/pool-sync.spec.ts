import "./fixtures/seed-test-env";
import { test, expect } from "@playwright/test";
import { personalizeComparison } from "../lib/funding";
import { mergePools, normalizePools, poolState } from "../lib/pools";
import { resetE2eState, setE2eSessionCookie } from "./fixtures/onboarding-auth";

function weekly(state: "headroom" | "tight" | "exhausted", age = 0) {
  const now = Date.now() / 1000;
  return { pool: "claude:weekly" as const, state, observed_at: now-age,
    resets_at: now+3600, used_percent: state === "exhausted" ? 98 : 42, window_minutes: 10080 };
}

test("saved stale exhaustion survives, a passed reset clears, and credits never reset", () => {
  const now = Date.now()/1000;
  const saved = weekly("exhausted", 86400);
  expect(mergePools([saved], [{...saved, state: "headroom"}])[0].state).toBe("exhausted");
  expect(mergePools([saved], [weekly("headroom", 21601)])[0].state).toBe("exhausted");
  expect(poolState([saved], "claude-code")).toBe("exhausted");
  expect(poolState([{...saved, resets_at: now-1}], "claude-code")).toBe("headroom");
  const credits = {...saved, pool: "openrouter:credits", window_minutes: 0, resets_at: null};
  expect(poolState([credits], "openrouter")).toBe("exhausted");
  expect(normalizePools([{...saved, transcript: "private"}])).toEqual([]);
  expect(poolState([{...saved, observed_at: now+60}], "claude-code")).toBe("headroom");
});

test("cost annotations disclose exhausted pools and keep other funding independent", () => {
  const rows = [{platform_id: "claude-code"}, {platform_id: "openrouter"}, {platform_id: "openai-api"}];
  const pools = normalizePools([weekly("exhausted"), {...weekly("exhausted"), pool: "openrouter:credits", window_minutes: 0, resets_at: null}]);
  const result = personalizeComparison(rows, ["claude-max"], ["openrouter", "openai"], pools);
  expect(result.find(r => r.platform_id === "claude-code")?.your_cost).toContain("usage credits at list price");
  expect(result.find(r => r.platform_id === "claude-code")?.funded).toBe(false);
  expect(result.find(r => r.platform_id === "openrouter")?.your_cost).toContain("reserve exhausted");
  expect(result.find(r => r.platform_id === "openai-api")?.your_cost).toContain("your OpenAI API");
});

test("profile roundtrip retains pools across settings saves and forwards only saved states", async ({ page }) => {
  await resetE2eState(page);
  await setE2eSessionCookie(page);
  const observation = weekly("exhausted");
  const save = await page.request.patch("/api/profile", { data: {
    subscriptions: ["claude-max"], allowed_jurisdictions: ["us"], pool_states: [observation],
  }});
  expect(save.status()).toBe(200);
  expect((await save.json()).pool_states[0].state).toBe("exhausted");
  const settings = await page.request.patch("/api/profile", {data: {budget_priority: "cheap"}});
  expect((await settings.json()).pool_states[0].state).toBe("exhausted");
  const stale = await page.request.patch("/api/profile", {data: {pool_states: [weekly("headroom", 21601)]}});
  expect((await stale.json()).pool_states[0].state).toBe("exhausted");
  const bad = await page.request.patch("/api/profile", {data: {pool_states: [{...observation, used_percent: 101}]}});
  expect(bad.status()).toBe(400);
  const quick = await page.request.post("/api/recommend/keyless", {data: {
    category: "coding", complexity: "low", pool_states: [weekly("headroom")],
  }});
  expect(quick.status()).toBe(200);
  expect((await quick.json()).received_pool_states[0].state).toBe("exhausted");
  const engine = await page.request.post("/api/recommend", {data: {
    task_description: "pool forwarding smoke", context: {pool_states: [weekly("headroom")]},
  }});
  expect(engine.status()).toBe(200);
  expect(await engine.text()).toContain("claude:weekly");
});
