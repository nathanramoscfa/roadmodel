import "./fixtures/seed-test-env";

import { expect, test } from "@playwright/test";
import { NextRequest } from "next/server";
import { withFundingLane } from "../lib/withFundingLane";
import { _setAuditSinkForTest } from "../lib/audit";
import { setTestKeylessLimiters } from "../lib/ratelimit";
import { GET as callback } from "../app/(auth)/callback/route";
import { sameOrigin, safeLocalPath, readJson, readForm, BodyError, noStore } from "../lib/http-boundaries";
import { env } from "../lib/env";
import { POST as recommend } from "../app/api/recommend/route";
import { POST as keyless } from "../app/api/recommend/keyless/route";
import { POST as roadmap } from "../app/api/roadmap/route";
import { PATCH as profile } from "../app/api/profile/route";
import { POST as gate } from "../app/api/gate/route";
import { POST as signout } from "../app/(auth)/signout/route";
import { POST as exchange } from "../app/api/openrouter/exchange/route";
import { recommendRequestSchema } from "../lib/recommend-context";
import { POST as reset } from "../app/api/test/e2e-reset/route";
import { POST as clearConversations } from "../app/api/test/clear-conversations/route";
import { POST as seedConversation } from "../app/api/test/seed-conversation/route";
import { POST as mockRecommend } from "../app/api/test/mock-recommend/route";
import { POST as mockLadder } from "../app/api/test/mock-recommend/ladder/route";
import { POST as mockVisitor } from "../app/api/test/mock-recommend/visitor/route";
import { POST as mockScore } from "../app/api/test/mock-recommend/score/route";
import { setTestGateBackend } from "../lib/gateGuard";

test.afterEach(() => {
  setTestKeylessLimiters(null);
  _setAuditSinkForTest(null);
});

test("funding mutations reject a foreign origin before resolving identity", async () => {
  let resolutions = 0;
  const route = withFundingLane(async () => new Response("ok"), async () => {
    resolutions++;
    return undefined;
  });
  _setAuditSinkForTest(() => {});
  const res = await route(new Request("http://localhost/api/recommend", {
    method: "POST", headers: { Origin: "https://outside.invalid" },
  }));
  expect(res.status).toBe(403);
  expect(resolutions).toBe(0);
  expect(res.headers.get("cache-control")).toContain("no-store");
});

test("a limiter timeout refuses dispatch even when the SDK reports success", async () => {
  const result = { success: true, limit: 0, remaining: 0, reset: 0, pending: Promise.resolve(), reason: "timeout" as const };
  setTestKeylessLimiters({ burst: { limit: async () => result }, daily: { limit: async () => result } });
  _setAuditSinkForTest(() => {});
  let calls = 0;
  const handler = async () => { calls++; return new Response("ok"); };
  const route = withFundingLane(handler, async () => undefined, { keyless: handler });
  const res = await route(new Request("http://localhost/api/recommend/keyless", {
    method: "POST", headers: { Origin: "http://localhost" },
  }));
  expect(res.status).toBe(503);
  expect(calls).toBe(0);
  expect(res.headers.get("cache-control")).toContain("no-store");
});

test("callback keeps an unsafe next out of the login flow", async () => {
  const response = await callback(new NextRequest("http://localhost/callback?next=%2F%2Foutside.invalid"));
  expect(new URL(response.headers.get("location")!).searchParams.get("next")).toBe("/");
  expect(response.headers.get("cache-control")).toContain("no-store");
});

test("all seven real mutation handlers reject foreign Origin before auth or body reads", async () => {
  const previous = env.ROADMAP_ENABLED;
  env.ROADMAP_ENABLED = true;
  try {
    for (const handler of [recommend, keyless, roadmap, profile, gate, signout, exchange]) {
      const response = await handler(new NextRequest("http://localhost/api/any", { method: "POST", headers: { origin: "https://outside.invalid" } }));
      expect(response.status).toBe(403);
      expect(response.headers.get("cache-control")).toContain("no-store");
    }
  } finally { env.ROADMAP_ENABLED = previous; }
});

test("origin exceptions require the configured bypass and no browser provenance", async () => {
  const request = (headers: HeadersInit) => new Request("https://local.invalid/path", { method: "POST", headers });
  for (const origin of ["null", "https://outside.invalid", "https://local.invalid.evil.invalid"]) {
    expect(sameOrigin(request({ origin }), true)).toBe(false);
  }
  expect(sameOrigin(request({}))).toBe(false);
  expect(sameOrigin(request({}), true)).toBe(true);
  for (const site of ["same-site", "cross-site", "none"]) expect(sameOrigin(request({ origin: "https://local.invalid", "sec-fetch-site": site }), true)).toBe(false);
  expect(sameOrigin(request({ "sec-fetch-site": "same-origin" }), true)).toBe(false);
  expect(sameOrigin(request({ origin: "https://local.invalid", "sec-fetch-site": "same-origin" }))).toBe(true);
  const previous = env.ROADMODEL_LATENCY_BYPASS_TOKEN;
  env.ROADMODEL_LATENCY_BYPASS_TOKEN = "synthetic-bypass";
  const route = withFundingLane(async () => new Response("ok"), async () => undefined);
  _setAuditSinkForTest(() => {});
  try {
    for (const token of ["wrong", "", "synthetic-bypass"]) {
      const res = await route(request({ "x-roadmodel-bypass": token }));
      expect(res.status).toBe(token === "synthetic-bypass" ? 200 : 403);
    }
  } finally { env.ROADMODEL_LATENCY_BYPASS_TOKEN = previous; }
});

test("disabled roadmap and all seven test endpoints return404 on Vercel before parsing", async () => {
  const prior = { vercel: process.env.VERCEL, e2e: process.env.ROADMODEL_E2E_AUTH, roadmap: env.ROADMAP_ENABLED };
  process.env.VERCEL = "1"; process.env.ROADMODEL_E2E_AUTH = "1"; env.ROADMAP_ENABLED = false;
  try {
    for (const handler of [roadmap, reset, clearConversations, seedConversation, mockRecommend, mockLadder, mockVisitor, mockScore]) {
      const response = await handler(new NextRequest("http://localhost/api/test/fixture", { method: "POST", body: "malformed" }));
      expect(response.status).toBe(404);
    }
  } finally {
    if (prior.vercel === undefined) delete process.env.VERCEL; else process.env.VERCEL = prior.vercel;
    if (prior.e2e === undefined) delete process.env.ROADMODEL_E2E_AUTH; else process.env.ROADMODEL_E2E_AUTH = prior.e2e;
    env.ROADMAP_ENABLED = prior.roadmap;
  }
});

test("redirect normalization stays on the fixed origin", () => {
  for (const raw of ["//outside.invalid", "/\\outside.invalid", "/a/..//outside.invalid", "/\t/outside.invalid", "https://outside.invalid", "javascript:alert(1)"]) {
    expect(safeLocalPath(raw)).toBe("/");
  }
  for (const raw of ["/recommend?x=1#part", "/ordinary%20path"]) {
    expect(safeLocalPath(raw)).toBe(raw);
    expect(new URL(safeLocalPath(raw), "https://local.invalid").origin).toBe("https://local.invalid");
  }
});

test("body readers count streamed bytes and cancel excess without trusting a header", async () => {
  for (const declared of [null, "1"]) {
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(33)); }, cancel() { cancelled = true; } });
    const request = new Request("https://local.invalid", { method: "POST", headers: { "content-type": "application/json", ...(declared ? { "content-length": declared } : {}) }, body, duplex: "half" } as RequestInit);
    await expect(readJson(request, 32)).rejects.toMatchObject({ status: 413 });
    expect(cancelled).toBe(true);
  }
  const valid = JSON.stringify({ task_description: "x".repeat(50000) }).replaceAll("x", "\\u0078");
  const body = await readJson(new Request("https://local.invalid", { method: "POST", headers: { "content-type": "application/json" }, body: valid }));
  expect(recommendRequestSchema.safeParse(body).success).toBe(true);
  for (const body of ["null", "[]", '{"task_description":"ok","surprise":true}']) {
    expect(recommendRequestSchema.safeParse(JSON.parse(body)).success).toBe(false);
  }
  await expect(readForm(new Request("https://local.invalid", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "password=" + "x".repeat(17000) }))).rejects.toBeInstanceOf(BodyError);
});

test("private cache headers preserve streaming bytes and multiple cookies", async () => {
  const response = new Response("data: {}\n\n", { headers: { "cache-control": "no-transform", "content-type": "text/event-stream" } });
  response.headers.append("Set-Cookie", "first=1; Path=/; HttpOnly");
  response.headers.append("Set-Cookie", "second=2; Path=/; Secure");
  expect(noStore(response)).toBe(response);
  expect(response.headers.getSetCookie()).toHaveLength(2);
  expect(response.headers.get("cache-control")).toContain("no-store, no-transform");
  expect(await response.text()).toBe("data: {}\n\n");
});

test("the gate normalizes its redirect and retains secure cookie options", async () => {
  const previous = process.env.SITE_PASSWORD;
  process.env.SITE_PASSWORD = "synthetic-gate-password";
  const unexpected = async (): Promise<never> => { throw new Error("unexpected fixture write"); };
  setTestGateBackend({
    limiter: { limit: unexpected, getRemaining: async () => ({ remaining: 3, limit: 3, reset: Date.now() + 60000 }) },
    redis: { set: unexpected, lpush: unexpected, ltrim: unexpected, expire: unexpected },
  });
  try {
    const response = await gate(new NextRequest("https://local.invalid/api/gate", {
      method: "POST", headers: { origin: "https://local.invalid", "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ password: "synthetic-gate-password", next: "/\\outside.invalid" }).toString(),
    }));
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("https://local.invalid/");
    for (const flag of ["HttpOnly", "Secure", "SameSite=lax"]) expect(response.headers.get("set-cookie")).toContain(flag);
    expect(response.headers.get("cache-control")).toContain("no-store");
  } finally {
    setTestGateBackend(null);
    if (previous === undefined) delete process.env.SITE_PASSWORD; else process.env.SITE_PASSWORD = previous;
  }
});

test("profile rejects unbounded lists and protected fields before saving", async ({ request, baseURL }) => {
  const headers = { Origin: baseURL!, Cookie: "rm-e2e-uid=00000000-0000-4000-8000-000000000063" };
  for (const data of [{ subscriptions: Array(5000).fill("claude-max") }, { frontier_override: true }, { created_at: new Date(0).toISOString() }]) {
    const response = await request.patch("/api/profile", { headers, data });
    expect([400, 413]).toContain(response.status());
    expect(await response.json()).toEqual({ error: "bad_input" });
    expect(response.headers()["cache-control"]).toContain("no-store");
  }
  const response = await request.patch("/api/profile", { headers, data: { budget_priority: "balanced" } });
  expect(response.status()).toBe(200);
  expect((await response.json()).subscriptions).toEqual([]);
});
