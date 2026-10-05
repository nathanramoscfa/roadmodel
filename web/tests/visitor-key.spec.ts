// web/tests/visitor-key.spec.ts
//
// The visitor lane at the edge: a visitor pays for one recommendation with
// their own API key (lib/funding-lane.ts, lib/withFundingLane.ts,
// app/api/recommend/route.ts). The guarantees under test:
//
// - the lane decision: a well-formed key + provider is the visitor lane (even
//   for an invited member); a malformed one is 400 without a fetch;
// - transport: the key reaches the service ONLY as X-Roadmodel-Visitor-Key, on
//   the visitor endpoint, in exactly one call; never in the body or context;
// - the ledger: audit rows read funded_by 'visitor' with cost_usd null and the
//   visitor's cost in cache_stats.visitor_cost_usd; the operator's spend
//   counter never moves, and the operator's cap never blocks the lane;
// - the limits, the declined-key limiter among them;
// - a canary key appears in no console output, audit insert or response.
//
// Node-side (no `page`): the real route handler runs with the upstream fetch
// replaced, the repo's idiom for the lane gate (funding-lane.spec.ts).

import "./fixtures/seed-test-env";

import { randomBytes } from "node:crypto";

import { test, expect } from "@playwright/test";

import { POST } from "../app/api/recommend/route";
import { _setAuditSinkForTest, type AuditEntry } from "../lib/audit";
import { env } from "../lib/env";
import { decideLane } from "../lib/funding-lane";
import { VISITOR_DAILY_LIMIT, VISITOR_REJECTED_LIMIT, setTestVisitorLimiters } from "../lib/ratelimit";
import registry from "../data/engines.json";
import { _setSpendCounterForTest, _setSpendReaderForTest } from "../lib/spend-guard";

const INVITED = "invited-test-uid"; // seed-test-env: RECOMMEND_INVITED_USER_IDS

// Fixture keys are fake and assembled at runtime from parts, so no
// secret-shaped literal is committed.
function fakeKey(prefix: string, marker = "canary-0411"): string {
  return [prefix, marker, randomBytes(12).toString("hex")].join("-");
}
const CANARY = fakeKey("sk");
const KEYS = {
  openai: CANARY,
  google: "AIza" + randomBytes(16).toString("hex"),
  anthropic: fakeKey("sk-ant"),
} as const;

const VISITOR_URL = "/v1/visitor/recommend/ladder";
const mutableEnv = env as { ROADMODEL_DAILY_COST_CAP_USD: number };

// --- Fakes ------------------------------------------------------------------

interface Call {
  url: string;
  headers: Record<string, string>;
  body: string;
}
let calls: Call[] = [];
let upstream: () => Response = () => ladderResponse();
const realFetch = globalThis.fetch;

function ladderResponse(): Response {
  const pick = (model: string, effort: string) => ({
    model,
    platform: "Claude Code",
    settings: { effort, thinking: "On" },
    rationale: `TASK: Coding. PICK: ${model}.`,
    comparison_table: [],
  });
  return new Response(
    JSON.stringify({
      picks: {
        quality: pick("Claude Opus 4.8", "Max"),
        balanced: pick("Claude Sonnet 4.6", "High"),
        cost: pick("Claude 4.5 Haiku", "Low"),
      },
      // A collapsed ladder is still the visitor's answer: no fan-out.
      guard: { healthy: false },
      engine: "openai-gpt-6-luna",
      usage: { input_tokens: 61000, cached_input_tokens: 56000, cache_write_tokens: 0, output_tokens: 900 },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function status(code: number, body: unknown): () => Response {
  return () => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
}

// Daily, burst and declined-key limiters with real counters, keyed like Upstash.
function fakeLimiters() {
  const used: Record<string, number> = {};
  const counter = (limit: number) => ({
    limit: async (key: string) => {
      used[key] = (used[key] ?? 0) + 1;
      return { success: used[key] <= limit, reset: Date.now() + 3_600_000 } as never;
    },
    getRemaining: async (key: string) => ({ remaining: limit - (used[key] ?? 0), reset: Date.now() + 3_600_000 }) as never,
  });
  const limiters = {
    burst: counter(10_000),
    daily: counter(VISITOR_DAILY_LIMIT),
    rejected: counter(VISITOR_REJECTED_LIMIT),
  };
  return { limiters, used };
}

let audits: AuditEntry[] = [];
let spend: number[] = [];
let consoleOut: string[] = [];
const CONSOLE = ["log", "info", "warn", "error", "debug"] as const;
const realConsole = Object.fromEntries(CONSOLE.map((m) => [m, console[m]]));

test.beforeEach(() => {
  calls = [];
  audits = [];
  spend = [];
  consoleOut = [];
  upstream = () => ladderResponse();
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!/\/v1\/(visitor\/)?recommend/.test(new URL(url).pathname)) {
      // Anything else the route reads (the availability table) fails open.
      return new Response("{}", { status: 503 });
    }
    calls.push({
      url,
      headers: Object.fromEntries(new Headers(init?.headers).entries()),
      body: typeof init?.body === "string" ? init.body : "",
    });
    return upstream();
  }) as typeof fetch;
  _setAuditSinkForTest((entry) => audits.push(entry));
  _setSpendCounterForTest((usd) => spend.push(usd));
  setTestVisitorLimiters(fakeLimiters().limiters);
  for (const m of CONSOLE) {
    console[m] = (...args: unknown[]) => {
      consoleOut.push(args.map((a) => (a instanceof Error ? `${a.message} ${a.stack}` : String(a))).join(" "));
    };
  }
});

test.afterEach(() => {
  globalThis.fetch = realFetch;
  _setAuditSinkForTest(null);
  _setSpendCounterForTest(null);
  _setSpendReaderForTest(null);
  setTestVisitorLimiters(null);
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 0;
  for (const m of CONSOLE) console[m] = realConsole[m] as typeof console.log;
});

function post(
  headers: Record<string, string> = {},
  body: Record<string, unknown> = { task_description: "refactor a data pipeline" },
): Request {
  return new Request("http://localhost/api/recommend", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

function keyed(provider: keyof typeof KEYS, key: string = KEYS[provider]): Record<string, string> {
  return { "x-roadmodel-visitor-key": key, "x-roadmodel-visitor-provider": provider };
}

// The canary appears nowhere the edge writes: the response, the audit rows,
// the console.
async function expectNoKey(res: Response, key: string = CANARY): Promise<string> {
  const text = await res.text();
  expect(text).not.toContain(key);
  for (const [name, value] of res.headers.entries()) {
    expect(`${name}: ${value}`).not.toContain(key);
  }
  expect(JSON.stringify(audits)).not.toContain(key);
  expect(consoleOut.join("\n")).not.toContain(key);
  return text;
}

// --- The lane decision ------------------------------------------------------

test("decideLane: a well-formed key and provider is the visitor lane, even for an invited member", () => {
  for (const provider of ["openai", "google", "anthropic"] as const) {
    expect(decideLane(post(keyed(provider)), undefined, { visitor: true })).toEqual({ lane: "visitor", provider });
  }
  expect(decideLane(post(keyed("openai")), INVITED, { visitor: true })).toEqual({
    lane: "visitor",
    provider: "openai",
  });
  // Provider names are case-insensitive.
  expect(
    decideLane(post({ ...keyed("openai"), "x-roadmodel-visitor-provider": "OpenAI" }), undefined, { visitor: true }),
  ).toEqual({ lane: "visitor", provider: "openai" });
});

test("decideLane: a key that cannot be one is the invalid lane", () => {
  const malformed: Record<string, string>[] = [
    { "x-roadmodel-visitor-key": CANARY }, // no provider
    { "x-roadmodel-visitor-provider": "openai" }, // no key
    keyed("openai", KEYS.anthropic), // an Anthropic key named OpenAI
    keyed("anthropic", CANARY), // an OpenAI key named Anthropic
    keyed("google", CANARY),
    keyed("openai", "sk-short"),
    keyed("openai", `${CANARY} spaced`),
    keyed("openai", `${CANARY}"quote`),
    keyed("openai", `sk-${"a".repeat(260)}`),
    { ...keyed("openai"), "x-roadmodel-visitor-provider": "openrouter" },
  ];
  for (const headers of malformed) {
    expect(decideLane(post(headers), undefined, { visitor: true })).toEqual({
      lane: "invalid",
      error: "visitor_key_malformed",
    });
  }
});

test("decideLane: a route without a visitor lane ignores the headers", () => {
  expect(decideLane(post(keyed("openai")), undefined)).toEqual({ lane: "refused" });
  expect(decideLane(post(keyed("openai")), INVITED)).toEqual({ lane: "operator", reason: "invited" });
});

// --- The route: transport, ledger, canary -----------------------------------

test("malformed key: 400 visitor_key_malformed, zero fetches, a bad_input row", async () => {
  const res = await POST(post(keyed("anthropic", CANARY)));
  expect(res.status).toBe(400);
  expect(JSON.parse(await expectNoKey(res))).toEqual({ error: "visitor_key_malformed" });
  expect(calls).toEqual([]);
  expect(audits).toHaveLength(1);
  expect(audits[0]).toMatchObject({
    outcome: "bad_input",
    error_class: "visitor_key_malformed",
    funded_by: "visitor",
  });
});

test("one call to the visitor endpoint, the key in its header only, the context clean", async () => {
  const res = await POST(post(keyed("openai"), { task_description: "refactor a data pipeline", context: { force_provider: "x", platforms_allowed: ["Claude Code"] } }));
  expect(res.status).toBe(200);
  const text = await expectNoKey(res);

  expect(calls).toHaveLength(1);
  const [call] = calls;
  expect(new URL(call.url).pathname).toBe(VISITOR_URL);
  expect(call.headers["x-roadmodel-visitor-key"]).toBe(CANARY);
  expect(call.headers["x-roadmodel-visitor-provider"]).toBe("openai");
  // The key is in no other header and nowhere in the body.
  for (const [name, value] of Object.entries(call.headers)) {
    if (name !== "x-roadmodel-visitor-key") expect(value).not.toContain(CANARY);
  }
  expect(call.body).not.toContain(CANARY);
  const sent = JSON.parse(call.body) as { context: Record<string, unknown> };
  // The browser's context is cut to the allowlist; the engine is the menu's.
  expect(Object.keys(sent.context)).not.toContain("visitor_key");
  expect(sent.context.platforms_allowed).toEqual(["Claude Code"]);
  expect(sent.context.force_provider).toBe(registry.visitor_defaults.openai);

  // A collapsed ladder still answers: no fan-out on the visitor's key.
  const body = JSON.parse(text) as {
    recommendations: { priority: string }[];
    engine: { funded_by: string; cost_usd: number; fell_back: boolean };
  };
  expect(body.recommendations.map((r) => r.priority)).toEqual(["cheap", "balanced", "best"]);
  expect(body.engine).toMatchObject({ funded_by: "visitor", fell_back: false });
  expect(body.engine.cost_usd).toBeGreaterThan(0);
});

test("the ledger: funded_by visitor, cost_usd null, visitor_cost_usd set, the operator counter untouched", async () => {
  const res = await POST(post(keyed("openai")));
  expect(res.status).toBe(200);
  await expectNoKey(res);
  const ok = audits.filter((a) => a.outcome === "ok");
  expect(ok).toHaveLength(1);
  expect(ok[0].funded_by).toBe("visitor");
  expect(ok[0].cost_usd).toBeUndefined();
  expect(ok[0].cache_stats).toMatchObject({
    provider: "recommend-engine",
    engine: "openai-gpt-6-luna",
    visitor_provider: "openai",
    cost_source: "measured",
  });
  const stats = ok[0].cache_stats as { visitor_cost_usd?: number; funding_reason?: string };
  expect(stats.visitor_cost_usd).toBeGreaterThan(0);
  expect(stats.funding_reason).toBeUndefined();
  expect(spend).toEqual([]);
});

test("the operator's tripped cap never blocks a visitor's own key", async () => {
  mutableEnv.ROADMODEL_DAILY_COST_CAP_USD = 2;
  _setSpendReaderForTest(async () => 2.5);
  expect((await POST(post(keyed("openai")))).status).toBe(200);
  // ...while a request with no key is still refused before any fetch.
  const anon = await POST(post());
  expect(anon.status).toBe(402);
  expect(calls).toHaveLength(1);
});

test("engine: any evaluated engine of the key's provider, founder tier included; else its default", async () => {
  await POST(post(keyed("anthropic"), { task_description: "t", engine: "anthropic-claude-opus-5-5" }));
  await POST(post(keyed("google"), { task_description: "t", engine: "openai-gpt-6-luna" }));
  await POST(post(keyed("openai"), { task_description: "t", engine: "openai-nope" }));
  const engines = calls.map((c) => (JSON.parse(c.body) as { context: { force_provider: string } }).context.force_provider);
  expect(engines).toEqual([
    "anthropic-claude-opus-5-5",
    registry.visitor_defaults.google,
    registry.visitor_defaults.openai,
  ]);
  expect(calls.map((c) => c.headers["x-roadmodel-visitor-provider"])).toEqual(["anthropic", "google", "openai"]);
});

test("failures relay the code alone, from exactly one call", async () => {
  const cases: [() => Response, number, string][] = [
    [status(401, { error: "visitor_key_rejected", provider: "openai" }), 401, "visitor_key_rejected"],
    [status(429, { error: "visitor_quota", provider: "openai" }), 429, "visitor_quota"],
    [status(502, { error: "provider_error", provider: "openai", detail: `echo ${CANARY}` }), 502, "provider_error"],
    // An older service has no visitor endpoint.
    [status(404, { detail: "Not Found" }), 502, "provider_error"],
    // The service refusing the edge's bearer is not the visitor's key.
    [status(401, { detail: "invalid_or_missing_bearer" }), 502, "provider_error"],
    [() => new Response("not json", { status: 200 }), 502, "provider_error"],
    [
      () => {
        throw new Error(`network down for ${CANARY}`);
      },
      502,
      "provider_error",
    ],
  ];
  for (const [answer, code, error] of cases) {
    calls = [];
    audits = [];
    upstream = answer;
    const res = await POST(post(keyed("openai")));
    expect(res.status).toBe(code);
    expect(JSON.parse(await expectNoKey(res))).toEqual({ error });
    expect(calls).toHaveLength(1);
    expect(audits).toHaveLength(1);
    expect(audits[0]).toMatchObject({ outcome: error, funded_by: "visitor", provider: "openai" });
    expect(audits[0].cost_usd).toBeUndefined();
  }
  expect(spend).toEqual([]);
});

test("limits: 50 a day per IP+UA, then 429 rate_limited with no fetch", async () => {
  for (let i = 0; i < VISITOR_DAILY_LIMIT; i++) {
    expect((await POST(post(keyed("openai")))).status).toBe(200);
  }
  const over = await POST(post(keyed("openai")));
  expect(over.status).toBe(429);
  expect((await over.json()).error).toBe("rate_limited");
  expect(calls).toHaveLength(VISITOR_DAILY_LIMIT);
  expect(audits.at(-1)).toMatchObject({ outcome: "rate_limited", funded_by: "visitor" });
});

test("limits: the burst still applies", async () => {
  const { limiters } = fakeLimiters();
  setTestVisitorLimiters({ ...limiters, burst: { limit: async () => ({ success: false }) as never } });
  const res = await POST(post(keyed("openai")));
  expect(res.status).toBe(429);
  expect((await res.json()).error).toBe("burst_dropped");
  expect(calls).toEqual([]);
});

test("the declined-key limiter: five declined keys a day, the sixth attempt is 429 before any call", async () => {
  upstream = status(401, { error: "visitor_key_rejected", provider: "openai" });
  for (let i = 0; i < VISITOR_REJECTED_LIMIT; i++) {
    const res = await POST(post(keyed("openai", fakeKey("sk", "declined"))));
    expect(res.status).toBe(401);
  }
  expect(calls).toHaveLength(VISITOR_REJECTED_LIMIT);
  const sixth = await POST(post(keyed("openai", fakeKey("sk", "declined"))));
  expect(sixth.status).toBe(429);
  expect((await sixth.json()).error).toBe("too_many_rejected_keys");
  // Refused at the edge: no sixth call reaches a provider, even with a good key.
  upstream = () => ladderResponse();
  expect((await POST(post(keyed("openai")))).status).toBe(429);
  expect(calls).toHaveLength(VISITOR_REJECTED_LIMIT);
  expect(audits.at(-1)).toMatchObject({
    outcome: "rate_limited",
    error_class: "too_many_rejected_keys",
    funded_by: "visitor",
  });
});

test("a declined bearer or a provider error never counts as a declined key", async () => {
  upstream = status(401, { detail: "invalid_or_missing_bearer" });
  for (let i = 0; i < VISITOR_REJECTED_LIMIT + 2; i++) {
    expect((await POST(post(keyed("openai")))).status).toBe(502);
  }
  upstream = () => ladderResponse();
  expect((await POST(post(keyed("openai")))).status).toBe(200);
});

test("no key at all: still 402 funding_required for a signed-out caller", async () => {
  const res = await POST(post());
  expect(res.status).toBe(402);
  expect(calls).toEqual([]);
});
