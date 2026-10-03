// web/tests/funding-lane.spec.ts
//
// Who pays for a request (lib/funding-lane.ts) and the gate in front of the
// paid routes (lib/withFundingLane.ts). The guarantee under test: only the
// founder list, the invite list and the bypass header reach an operator-funded
// call; everything else is refused with 402 before the handler runs, so it
// makes zero upstream fetches. The cap and the limits bind the operator lane
// only. Node-side unit tests (no `page`), the repo's idiom; the route-level
// checks against the running server are at the bottom.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import { _setAuditSinkForTest, type AuditEntry } from "../lib/audit";
import { env } from "../lib/env";
import { decideLane, type OperatorLane } from "../lib/funding-lane";
import { setTestLaneLimiters, INVITED_DAILY_LIMIT } from "../lib/ratelimit";
import { clientContext } from "../lib/recommend-context";
import { _setSpendReaderForTest } from "../lib/spend-guard";
import { withFundingLane } from "../lib/withFundingLane";
import { E2E_AUTH_COOKIE, E2E_USER_ID } from "./fixtures/onboarding-auth";

const FOUNDER = "rl-exempt-test-uid"; // seed-test-env: RECOMMEND_RATELIMIT_EXEMPT_USER_IDS
const INVITED = "invited-test-uid"; // seed-test-env: RECOMMEND_INVITED_USER_IDS
const BYPASS = "bypass-test-token";

// env is parsed once at module load; these tests set the two values the gate
// reads per request and restore them after.
const mutableEnv = env as { ROADMODEL_LATENCY_BYPASS_TOKEN?: string; ROADMODEL_DAILY_COST_CAP_USD: number };

function post(headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/recommend", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify({ task_description: "pick a model" }),
  });
}

// A handler that does what the real ones do first: call upstream.
let fetches = 0;
let lanes: OperatorLane[] = [];
const upstreamHandler = async (_req: Request, lane: OperatorLane): Promise<Response> => {
  lanes.push(lane);
  await fetch("https://upstream.invalid/v1/recommend/ladder", { method: "POST" });
  return new Response("{}", { status: 200 });
};

function gate(userId: string | undefined, enabled?: () => boolean) {
  return withFundingLane(upstreamHandler, async () => userId, enabled ? { enabled } : {});
}

let audits: AuditEntry[] = [];
const realFetch = globalThis.fetch;

test.beforeEach(() => {
  fetches = 0;
  lanes = [];
  audits = [];
  globalThis.fetch = (async () => {
    fetches += 1;
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  _setAuditSinkForTest((entry) => audits.push(entry));
  mutableEnv.ROADMODEL_LATENCY_BYPASS_TOKEN = BYPASS;
});

test.afterEach(() => {
  globalThis.fetch = realFetch;
  _setAuditSinkForTest(null);
  _setSpendReaderForTest(null);
  setTestLaneLimiters(null);
  mutableEnv.ROADMODEL_LATENCY_BYPASS_TOKEN = undefined;
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 0;
});

test("decideLane: bypass, then founder, then invited; everyone else is refused", () => {
  expect(decideLane(post({ "x-roadmodel-bypass": BYPASS }), undefined)).toEqual({ lane: "operator", reason: "bypass" });
  expect(decideLane(post({ "x-roadmodel-bypass": BYPASS }), INVITED)).toEqual({ lane: "operator", reason: "bypass" });
  expect(decideLane(post(), FOUNDER)).toEqual({ lane: "operator", reason: "founder" });
  expect(decideLane(post(), INVITED)).toEqual({ lane: "operator", reason: "invited" });
  expect(decideLane(post(), undefined)).toEqual({ lane: "refused" });
  expect(decideLane(post(), "some-signed-in-user")).toEqual({ lane: "refused" });
  // A wrong, empty or near-miss bypass header is no bypass.
  expect(decideLane(post({ "x-roadmodel-bypass": "wrong" }), undefined)).toEqual({ lane: "refused" });
  expect(decideLane(post({ "x-roadmodel-bypass": `${BYPASS}x` }), undefined)).toEqual({ lane: "refused" });
  expect(decideLane(post({ "x-roadmodel-bypass": "" }), undefined)).toEqual({ lane: "refused" });
});

test("decideLane: the bypass header counts for nothing while the token is unset", () => {
  mutableEnv.ROADMODEL_LATENCY_BYPASS_TOKEN = undefined;
  expect(decideLane(post({ "x-roadmodel-bypass": "" }), undefined)).toEqual({ lane: "refused" });
  expect(decideLane(post({ "x-roadmodel-bypass": BYPASS }), undefined)).toEqual({ lane: "refused" });
});

test("decideLane: an exception inside the decision is a refusal", () => {
  const throwing = {
    url: "http://localhost/api/recommend",
    headers: {
      get() {
        throw new Error("boom");
      },
    },
  } as unknown as Request;
  // Even for the founder: the decision failed, so nobody is funded.
  expect(decideLane(throwing, FOUNDER)).toEqual({ lane: "refused" });
});

test("signed out: 402 funding_required, the handler never runs, zero fetches", async () => {
  const res = await gate(undefined)(post());
  expect(res.status).toBe(402);
  expect(await res.json()).toEqual({ error: "funding_required" });
  expect(lanes).toEqual([]);
  expect(fetches).toBe(0);
  expect(audits).toHaveLength(1);
  expect(audits[0]).toMatchObject({ outcome: "funding_required", route: "/api/recommend" });
  expect(audits[0].funded_by).toBeUndefined();
});

test("signed in, uninvited: 402 funding_required, zero fetches", async () => {
  const res = await gate("some-signed-in-user")(post());
  expect(res.status).toBe(402);
  expect(fetches).toBe(0);
  expect(audits[0]).toMatchObject({ outcome: "funding_required", user_id: "some-signed-in-user" });
});

test("an unreadable session is a signed-out caller: 402", async () => {
  const res = await withFundingLane(upstreamHandler, async () => {
    throw new Error("cookie store unavailable");
  })(post());
  expect(res.status).toBe(402);
  expect(fetches).toBe(0);
});

test("invited: the operator lane, 20 a day per user id; the 21st is 429", async () => {
  const used: Record<string, number> = {};
  const keys: string[] = [];
  setTestLaneLimiters({
    burst: { limit: async () => ({ success: true }) as never },
    invitedDaily: {
      limit: async (key: string) => {
        keys.push(key);
        used[key] = (used[key] ?? 0) + 1;
        return { success: used[key] <= INVITED_DAILY_LIMIT, reset: Date.now() + 3_600_000 } as never;
      },
    },
  });
  const run = gate(INVITED);
  for (let i = 0; i < INVITED_DAILY_LIMIT; i++) {
    expect((await run(post())).status).toBe(200);
  }
  const over = await run(post());
  expect(over.status).toBe(429);
  expect((await over.json()).error).toBe("rate_limited");
  expect(fetches).toBe(INVITED_DAILY_LIMIT);
  expect(lanes[0]).toEqual({ lane: "operator", reason: "invited" });
  // Keyed on the user, never the IP.
  expect(new Set(keys)).toEqual(new Set([`user:${INVITED}`]));
  expect(audits.at(-1)).toMatchObject({ outcome: "rate_limited", funded_by: "operator" });
});

test("invited: the 10-a-minute burst still applies", async () => {
  setTestLaneLimiters({
    burst: { limit: async () => ({ success: false }) as never },
    invitedDaily: { limit: async () => ({ success: true, reset: Date.now() }) as never },
  });
  const res = await gate(INVITED)(post());
  expect(res.status).toBe(429);
  expect((await res.json()).error).toBe("burst_dropped");
  expect(fetches).toBe(0);
});

test("founder and bypass: unlimited", async () => {
  let limited = 0;
  setTestLaneLimiters({
    burst: { limit: async () => ((limited += 1), { success: false }) as never },
    invitedDaily: { limit: async () => ((limited += 1), { success: false, reset: 0 }) as never },
  });
  for (let i = 0; i < 25; i++) {
    expect((await gate(FOUNDER)(post())).status).toBe(200);
  }
  const bypass = await gate(undefined)(post({ "x-roadmodel-bypass": BYPASS }));
  expect(bypass.status).toBe(200);
  expect(limited).toBe(0);
  expect(lanes.at(0)).toEqual({ lane: "operator", reason: "founder" });
  expect(lanes.at(-1)).toEqual({ lane: "operator", reason: "bypass" });
  expect(audits.at(-1)).toMatchObject({ outcome: "bypassed_rate_limit", funded_by: "operator" });
});

test("cap tripped: the operator lane gets 503; a refused request still gets 402", async () => {
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 2;
  _setSpendReaderForTest(async () => 2.5);
  const founder = await gate(FOUNDER)(post());
  expect(founder.status).toBe(503);
  expect((await founder.json()).error).toBe("daily_cost_cap");
  const anon = await gate(undefined)(post());
  expect(anon.status).toBe(402);
  expect((await anon.json()).error).toBe("funding_required");
  expect(fetches).toBe(0);
});

test("cap under the line: the operator lane runs", async () => {
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 2;
  _setSpendReaderForTest(async () => 0.25);
  expect((await gate(FOUNDER)(post())).status).toBe(200);
});

test("disabled route: 404 for the founder and anonymous alike, before the lane", async () => {
  let resolved = 0;
  const off = (userId: string | undefined) =>
    withFundingLane(
      upstreamHandler,
      async () => ((resolved += 1), userId),
      { enabled: () => false },
    );
  for (const res of [await off(FOUNDER)(post()), await off(undefined)(post())]) {
    expect(res.status).toBe(404);
  }
  expect(resolved).toBe(0);
  expect(fetches).toBe(0);
  expect(audits).toEqual([]);
});

test("client context: only the allowlisted keys survive", () => {
  expect(
    clientContext({
      force_provider: "anthropic-claude-opus-5-5",
      subscriptions: ["claude-max-20x"],
      api_providers: ["anthropic"],
      unknown_key: "x",
      platforms_allowed: ["Claude Code", 5, "", "x".repeat(101)],
      platforms_excluded: "Cursor",
    }),
  ).toEqual({ platforms_allowed: ["Claude Code"] });
  expect(clientContext(null)).toEqual({});
  expect(clientContext(["platforms_allowed"])).toEqual({});
  expect(clientContext("force_provider")).toEqual({});
});

// --- Against the running server (ROADMODEL_E2E_MOCK_RECOMMEND) ------------

test("the route: a signed-out POST to /api/recommend is refused with 402", async ({ request }) => {
  const res = await request.post("/api/recommend", { data: { task_description: "pick a model" } });
  expect(res.status()).toBe(402);
  expect(await res.json()).toEqual({ error: "funding_required" });
});

test("the route: an unknown context key and a spoofed force_provider never reach the service", async ({
  request,
}) => {
  const res = await request.post("/api/recommend", {
    headers: { Cookie: `${E2E_AUTH_COOKIE}=${E2E_USER_ID}` },
    data: {
      task_description: "pick a model",
      context: {
        unknown_key: "smuggled",
        force_provider: "anthropic-claude-opus-5-5",
        subscriptions: ["claude-max-20x"],
        platforms_allowed: ["Claude Code"],
      },
    },
  });
  expect(res.status()).toBe(200);
  const body = (await res.json()) as {
    recommendations: { received_context_keys?: string[] }[];
    engine: { requested: string; hint: string };
  };
  for (const rec of body.recommendations) {
    const keys = rec.received_context_keys ?? [];
    expect(keys).not.toContain("unknown_key");
    expect(keys).toContain("platforms_allowed");
  }
  // The engine is the menu's choice (the default), never the smuggled pin.
  expect(body.engine.requested).not.toBe("anthropic-claude-opus-5-5");
});
