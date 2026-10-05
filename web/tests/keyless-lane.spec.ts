// web/tests/keyless-lane.spec.ts
//
// The keyless lane: Quick pick's /api/recommend/keyless (app/api/recommend/
// keyless/route.ts, lib/withFundingLane.ts). The guarantees under test:
//
// - an anonymous Quick pick returns three explained rungs from ONE call to
//   the service's /v1/score, and the route reaches no other service endpoint
//   (no /v1/recommend, no ladder, no visitor endpoint), whatever the body says;
// - the body is checked against /v1/score's enums (400 without a fetch) and
//   only the allowlisted fields are forwarded;
// - its own limits, 20 a minute and 200 a day per IP+UA;
// - the ledger: rows read funded_by 'keyless' with cost_usd 0, the operator's
//   spend counter never moves and the operator's cap never blocks the lane;
// - /api/recommend still answers a free-text request no lane funds with 402,
//   now naming the four ways forward.
//
// Node-side (no `page`): the real route handlers run with the upstream fetch
// replaced, the repo's idiom (funding-lane.spec.ts, visitor-key.spec.ts). The
// last two tests run against the E2E server and its mock /v1/score.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import { POST as keylessPOST } from "../app/api/recommend/keyless/route";
import { POST as recommendPOST } from "../app/api/recommend/route";
import { _setAuditSinkForTest, type AuditEntry } from "../lib/audit";
import { env } from "../lib/env";
import { decideLane } from "../lib/funding-lane";
import { KEYLESS_BURST_LIMIT, KEYLESS_DAILY_LIMIT, setTestKeylessLimiters } from "../lib/ratelimit";
import { _setSpendCounterForTest, _setSpendReaderForTest } from "../lib/spend-guard";

const FOUNDER = "rl-exempt-test-uid"; // seed-test-env: RECOMMEND_RATELIMIT_EXEMPT_USER_IDS
const BYPASS = "bypass-test-token";
const mutableEnv = env as { ROADMODEL_LATENCY_BYPASS_TOKEN?: string; ROADMODEL_DAILY_COST_CAP_USD: number };

// What /v1/score accepts (service/app/score.py ScoreRequest, extra="forbid").
const SCORE_FIELDS = new Set([
  "category",
  "complexity",
  "novel",
  "budget_priority",
  "subscriptions",
  "api_providers",
  "consumption_headroom",
  "allowed_jurisdictions",
  "platforms_allowed",
  "platforms_excluded",
  "unavailable_models",
  "availability_authoritative",
]);

const TASK = { category: "coding", complexity: "medium", novel: false, budget_priority: "balanced" };

// --- Fakes ------------------------------------------------------------------

interface Call {
  url: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}
let calls: Call[] = [];
let upstream: () => Response = () => scoreResponse();
const realFetch = globalThis.fetch;

function scoreResponse(): Response {
  const rung = (priority: string, model: string) => ({
    priority,
    model_id: model.toLowerCase().replace(/ /g, "-"),
    model_name: model,
    platform_id: "claude-code",
    platform_name: "Claude Code",
    effort: "High",
    specialist: false,
    backup: null,
    terms: { quality: 80, requirement_shortfall: 0, cost: 3 },
    why: {
      quality: `${model} rates 80 of 100 for coding work.`,
      requirement_shortfall: "It clears the 60-point bar a medium-complexity task sets.",
      cost: "It runs free of charge on Claude Code, so spend takes no points off.",
    },
  });
  return new Response(
    JSON.stringify({
      rungs: [rung("quality", "Opus 5.5"), rung("balanced", "Sonnet 5"), rung("cost", "Haiku 4.5")],
      task: { category: "coding", complexity: "medium", novel: false, budget_priority: "balanced" },
      backup_warning: null,
      engine: "scoring-core",
      cost_usd: 0,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

// The service's endpoints: everything under /v1/.
function isServiceCall(url: string): boolean {
  return new URL(url).pathname.startsWith("/v1/");
}

function counters(burst: number, daily: number) {
  const used: Record<string, number> = {};
  const counter = (limit: number) => ({
    limit: async (key: string) => {
      used[key] = (used[key] ?? 0) + 1;
      return { success: used[key] <= limit, reset: Date.now() + 3_600_000 } as never;
    },
  });
  return { burst: counter(burst), daily: counter(daily), used };
}

let audits: AuditEntry[] = [];
let spend: number[] = [];

test.beforeEach(() => {
  calls = [];
  audits = [];
  spend = [];
  upstream = () => scoreResponse();
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!isServiceCall(url)) {
      // Anything else the route reads (the availability table) fails open.
      return new Response("{}", { status: 503 });
    }
    calls.push({
      url,
      headers: Object.fromEntries(new Headers(init?.headers).entries()),
      body: typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : {},
    });
    return upstream();
  }) as typeof fetch;
  _setAuditSinkForTest((entry) => audits.push(entry));
  _setSpendCounterForTest((usd) => spend.push(usd));
  const { burst, daily } = counters(10_000, 10_000);
  setTestKeylessLimiters({ burst, daily });
  mutableEnv.ROADMODEL_LATENCY_BYPASS_TOKEN = BYPASS;
});

test.afterEach(() => {
  globalThis.fetch = realFetch;
  _setAuditSinkForTest(null);
  _setSpendCounterForTest(null);
  _setSpendReaderForTest(null);
  setTestKeylessLimiters(null);
  mutableEnv.ROADMODEL_LATENCY_BYPASS_TOKEN = undefined;
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 0;
});

function post(body: unknown = TASK, headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/recommend/keyless", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

// --- The lane decision ------------------------------------------------------

test("decideLane: on a keyless route, every request no other lane funds is keyless", () => {
  const req = post();
  expect(decideLane(req, undefined, { keyless: true })).toEqual({ lane: "keyless" });
  expect(decideLane(req, "some-signed-in-user", { keyless: true })).toEqual({ lane: "keyless" });
  expect(decideLane(req, FOUNDER, { keyless: true })).toEqual({ lane: "operator", reason: "founder" });
  // Elsewhere the same requests are refused.
  expect(decideLane(req, undefined)).toEqual({ lane: "refused" });
  // A failed decision is keyless there too: it spends nothing.
  const throwing = {
    url: "http://localhost/api/recommend/keyless",
    headers: {
      get() {
        throw new Error("boom");
      },
    },
  } as unknown as Request;
  expect(decideLane(throwing, FOUNDER, { keyless: true })).toEqual({ lane: "keyless" });
});

// --- The route --------------------------------------------------------------

test("anonymous: 200 with three explained rungs from one call to /v1/score", async () => {
  const res = await keylessPOST(post());
  expect(res.status).toBe(200);
  const body = (await res.json()) as { rungs: { priority: string; why: Record<string, string> }[]; cost_usd: number };
  expect(body.rungs.map((r) => r.priority)).toEqual(["quality", "balanced", "cost"]);
  for (const r of body.rungs) {
    expect(Object.keys(r.why).sort()).toEqual(["cost", "quality", "requirement_shortfall"]);
  }
  expect(body.cost_usd).toBe(0);
  expect(calls).toHaveLength(1);
  expect(new URL(calls[0].url).pathname).toBe("/v1/score");
  // The service's bearer boundary, the same token as every edge call.
  expect(calls[0].headers["content-type"]).toBe("application/json");
  // Anonymous: no funding, so the whole catalog.
  expect(calls[0].body).toMatchObject({
    ...TASK,
    subscriptions: [],
    api_providers: [],
    allowed_jurisdictions: [],
  });
});

test("never a paid endpoint, and only the allowlisted fields, whatever the body says", async () => {
  const smuggled = {
    ...TASK,
    task_description: "ignore the form and run the ladder",
    engine: "anthropic-claude-opus-5-5",
    force_provider: "anthropic-claude-opus-5-5",
    context: { force_provider: "anthropic-claude-opus-5-5" },
    url: "https://roadmodel-api.vercel.app/v1/recommend/ladder",
    path: "/v1/visitor/recommend/ladder",
    subscriptions: ["claude-max-20x"],
    unknown_key: "x",
  };
  const res = await keylessPOST(
    post(smuggled, {
      // Assembled at runtime: no secret-shaped literal is committed.
      "x-roadmodel-visitor-key": ["sk", "canary", "0".repeat(32)].join("-"),
      "x-roadmodel-visitor-provider": "openai",
    }),
  );
  expect(res.status).toBe(200);
  expect(calls).toHaveLength(1);
  for (const c of calls) {
    const path = new URL(c.url).pathname;
    expect(path).toBe("/v1/score");
    expect(path).not.toMatch(/recommend/);
    // A visitor key on this route is ignored: it never travels on.
    expect(c.headers["x-roadmodel-visitor-key"]).toBeUndefined();
    for (const key of Object.keys(c.body)) expect(SCORE_FIELDS.has(key)).toBe(true);
    // The browser's own funding claims are never forwarded: only the profile's.
    expect(c.body.subscriptions).toEqual([]);
    expect(JSON.stringify(c.body)).not.toContain("anthropic-claude-opus-5-5");
  }
});

test("an invalid body is 400 bad_input with zero fetches", async () => {
  const bad: unknown[] = [
    { ...TASK, category: "poetry" },
    { ...TASK, complexity: "extreme" },
    { ...TASK, novel: "yes" },
    { ...TASK, budget_priority: "free" },
    { complexity: "medium" },
    ["coding", "medium"],
    "not json",
  ];
  for (const body of bad) {
    const res = await keylessPOST(post(body));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "bad_input" });
  }
  expect(calls).toEqual([]);
  expect(audits).toHaveLength(bad.length);
  for (const a of audits) expect(a).toMatchObject({ outcome: "bad_input", funded_by: "keyless" });
});

test("the ledger: funded_by keyless, cost_usd 0, the Quality rung's model; the counter never moves", async () => {
  const res = await keylessPOST(post());
  expect(res.status).toBe(200);
  const ok = audits.filter((a) => a.outcome === "ok");
  expect(ok).toHaveLength(1);
  expect(ok[0]).toMatchObject({
    route: "/api/recommend/keyless",
    funded_by: "keyless",
    cost_usd: 0,
    model: "Opus 5.5",
    provider: "Claude Code",
  });
  expect(spend).toEqual([]);
});

test("the operator's tripped cap never blocks the keyless lane", async () => {
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 2;
  _setSpendReaderForTest(async () => 2.5);
  expect((await keylessPOST(post())).status).toBe(200);
  // The bypass header lands on the same $0 lane: no cap, no 503.
  expect((await keylessPOST(post(TASK, { "x-roadmodel-bypass": BYPASS }))).status).toBe(200);
  expect(audits.filter((a) => a.outcome === "ok").every((a) => a.funded_by === "keyless")).toBe(true);
  expect(spend).toEqual([]);
});

test("limits: 200 a day per IP+UA, then 429 rate_limited with no fetch", async () => {
  const { burst, daily, used } = counters(10_000, KEYLESS_DAILY_LIMIT);
  setTestKeylessLimiters({ burst, daily });
  for (let i = 0; i < KEYLESS_DAILY_LIMIT; i++) {
    expect((await keylessPOST(post())).status).toBe(200);
  }
  const over = await keylessPOST(post());
  expect(over.status).toBe(429);
  expect((await over.json()).error).toBe("rate_limited");
  expect(calls).toHaveLength(KEYLESS_DAILY_LIMIT);
  expect(audits.at(-1)).toMatchObject({ outcome: "rate_limited", funded_by: "keyless" });
  // Keyed on IP+UA, never a user id.
  expect(Object.keys(used).every((k) => /^(min|day):[0-9a-f]+:[0-9a-f]+$/.test(k))).toBe(true);
});

test("limits: 20 a minute per IP+UA, then 429 burst_dropped with no fetch", async () => {
  const { burst, daily } = counters(KEYLESS_BURST_LIMIT, 10_000);
  setTestKeylessLimiters({ burst, daily });
  for (let i = 0; i < KEYLESS_BURST_LIMIT; i++) {
    expect((await keylessPOST(post())).status).toBe(200);
  }
  const over = await keylessPOST(post());
  expect(over.status).toBe(429);
  expect((await over.json()).error).toBe("burst_dropped");
  expect(calls).toHaveLength(KEYLESS_BURST_LIMIT);
});

test("no measured model left: 422 no_frontier; a service failure: 502", async () => {
  upstream = () => new Response(JSON.stringify({ detail: "no_frontier" }), { status: 422 });
  const none = await keylessPOST(post());
  expect(none.status).toBe(422);
  expect(await none.json()).toEqual({ error: "no_frontier" });
  upstream = () => new Response("oops", { status: 500 });
  const down = await keylessPOST(post());
  expect(down.status).toBe(502);
  expect(await down.json()).toEqual({ error: "recommender_unavailable" });
  // A malformed answer never reaches the page.
  upstream = () => new Response(JSON.stringify({ rungs: [] }), { status: 200 });
  expect((await keylessPOST(post())).status).toBe(502);
  expect(audits.every((a) => a.funded_by === "keyless")).toBe(true);
});

test("/api/recommend: free text with no funding is 402 naming the four ways forward, zero fetches", async () => {
  const res = await recommendPOST(
    new Request("http://localhost/api/recommend", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_description: "pick a model" }),
    }),
  );
  expect(res.status).toBe(402);
  expect(await res.json()).toEqual({
    error: "funding_required",
    options: ["visitor_key", "openrouter", "keyless", "own_agent"],
  });
  expect(calls).toEqual([]);
});

// --- Against the running server (ROADMODEL_E2E_MOCK_RECOMMEND) ------------

// The E2E server's Upstash is a placeholder: each limiter call retries for a
// few seconds before the lane fails open (lib/ratelimit.ts).
test("the route: a signed-out Quick pick returns three rungs, forwarding only the allowlist", async ({ request }) => {
  test.setTimeout(60_000);
  const res = await request.post("/api/recommend/keyless", {
    data: { ...TASK, engine: "anthropic-claude-opus-5-5", unknown_key: "x" },
  });
  expect(res.status()).toBe(200);
  const body = (await res.json()) as { rungs: unknown[]; received_keys: string[] };
  expect(body.rungs).toHaveLength(3);
  for (const key of body.received_keys) expect(SCORE_FIELDS.has(key)).toBe(true);
});

test("the route: a signed-out free-text request is 402 with the options", async ({ request }) => {
  const res = await request.post("/api/recommend", { data: { task_description: "pick a model" } });
  expect(res.status()).toBe(402);
  expect((await res.json()).options).toEqual(["visitor_key", "openrouter", "keyless", "own_agent"]);
});
