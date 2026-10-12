import "./fixtures/seed-test-env";
import { expect, test } from "@playwright/test";
import { GoogleGenAI } from "@google/genai";
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";
import { fireGateAlert, gateLockState, recordGateFailure, setTestGateBackend } from "../lib/gateGuard";
import { getOrCreateCachedPrefix, setTestRedisClient } from "../lib/llm-cache";
import { setTestGeminiClient } from "../lib/gemini-client";
import { createRoadmapStream } from "../lib/roadmap-engine";

test("actual Redis failures preserve gate behavior without logging command data", async () => {
  const saved = { fetch: globalThis.fetch, warn: console.warn };
  const logs: unknown[][] = [];
  const commands: string[] = [];
  console.warn = (...args) => { logs.push(args); };
  globalThis.fetch = async (input, init) => {
    expect(new URL(String(input)).origin).toBe("https://redis.invalid");
    const body = JSON.parse(String(init?.body)) as unknown[];
    const batch = Array.isArray(body[0]) ? body as unknown[][] : [body];
    const names = batch.map((command) => String(command[0]).toLowerCase());
    commands.push(...names);
    if (names.every((name) => name === "set")) {
      return Response.json(Array.isArray(body[0]) ? batch.map(() => ({ result: "OK" })) : { result: "OK" });
    }
    return Response.json({ error: "SYNTHETIC_UPSTREAM_DIAGNOSTIC" }, { status: 400 });
  };
  const redis = new Redis({ url: "https://redis.invalid", token: "synthetic-credential", retry: false });
  const limiter = new Ratelimit({ redis, limiter: Ratelimit.slidingWindow(3, "5 m"), timeout: 0 });
  setTestGateBackend({ redis, limiter });
  try {
    expect(await gateLockState("192.0.2.91")).toMatchObject({ locked: false, remaining: 3 });
    expect(await recordGateFailure("192.0.2.91")).toMatchObject({ locked: false, remaining: 3 });
    await fireGateAlert("192.0.2.91", "SYNTHETIC_VISITOR_USER_AGENT");
    expect(commands).toContain("lpush");
    expect(logs).toEqual([
      ["[gate] lock-state check failed — failing open"],
      ["[gate] failure record failed — failing open"],
      ["[gate] alert push failed — non-fatal"],
    ]);
  } finally {
    setTestGateBackend(null); globalThis.fetch = saved.fetch; console.warn = saved.warn;
  }
});

test("actual Redis memo errors log fixed events and retain the Google cache result", async () => {
  const saved = { fetch: globalThis.fetch, warn: console.warn, vercel: process.env.VERCEL };
  const google = new GoogleGenAI({ apiKey: "synthetic-google-credential" });
  const logs: unknown[][] = [];
  const calls: string[] = [];
  process.env.VERCEL = "1";
  console.warn = (...args) => { logs.push(args); };
  globalThis.fetch = async (input) => {
    const url = new URL(String(input)); calls.push(url.hostname);
    if (url.origin === "https://redis.invalid") return Response.json({ error: "SYNTHETIC_MEMO_DIAGNOSTIC" }, { status: 400 });
    expect(url.origin).toBe("https://generativelanguage.googleapis.com");
    expect(url.pathname).toMatch(/\/cachedContents$/);
    return Response.json({ name: "cachedContents/synthetic-resource" });
  };
  const redis = new Redis({ url: "https://redis.invalid", token: "synthetic-credential", retry: false });
  setTestRedisClient(redis);
  try {
    const name = await getOrCreateCachedPrefix({
      provider: "google", model: "gemini-2.5-flash",
      segments: { systemInstruction: "Public orientation".repeat(300), contents: ["Public template"] },
      client: { async create(args) {
        const result = await google.caches.create({ model: args.model, config: {
          contents: args.contents, systemInstruction: args.systemInstruction, ttl: `${args.ttl_seconds}s`,
        } });
        expect(result.name).toBe("cachedContents/synthetic-resource");
        return { name: result.name! };
      } },
    });
    expect(name).toBe("cachedContents/synthetic-resource");
    expect(calls).toEqual(["redis.invalid", "generativelanguage.googleapis.com", "redis.invalid"]);
    expect(logs).toEqual([["[llm-cache] redis memo read failed"], ["[llm-cache] redis memo write failed"]]);
  } finally {
    setTestRedisClient(null); globalThis.fetch = saved.fetch; console.warn = saved.warn;
    if (saved.vercel === undefined) delete process.env.VERCEL; else process.env.VERCEL = saved.vercel;
  }
});

test("actual Google cache errors stay private while roadmap generation falls back", async () => {
  const saved = { fetch: globalThis.fetch, warn: console.warn };
  const logs: unknown[][] = [];
  const google = new GoogleGenAI({ apiKey: "synthetic-google-credential" });
  let cacheCalls = 0; let generationCalls = 0;
  console.warn = (...args) => { logs.push(args); };
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    if (url.origin === "https://redis.invalid") return Response.json([{ result: null }]);
    expect(url.origin).toBe("https://generativelanguage.googleapis.com");
    if (url.pathname.endsWith("/cachedContents")) {
      cacheCalls++;
      return Response.json({ error: { code: 400, status: "INVALID_ARGUMENT", message: "SYNTHETIC_UPSTREAM_DIAGNOSTIC" } }, { status: 400 });
    }
    expect(url.pathname).toMatch(/:streamGenerateContent$/);
    generationCalls++;
    return new Response('data: {"candidates":[{"content":{"parts":[{"text":"Synthetic answer"}],"role":"model"}}],"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":1}}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  };
  setTestRedisClient(new Redis({ url: "https://redis.invalid", token: "synthetic-credential", retry: false }));
  setTestGeminiClient(google);
  try {
    const events = [];
    for await (const event of createRoadmapStream({ model: "gemini-2.5-flash", profile: null, messages: [{ id: "fixture", created_at: "2000-01-01T00:00:00Z", role: "user", content: "Synthetic prompt" }] })) events.push(event);
    expect(events.some((event) => event.type === "message_complete")).toBe(true);
    expect(cacheCalls).toBe(1); expect(generationCalls).toBe(1);
    expect(logs).toEqual([["[roadmap-engine] cachedContent setup failed"]]);
  } finally {
    setTestRedisClient(null); setTestGeminiClient(null); globalThis.fetch = saved.fetch; console.warn = saved.warn;
  }
});
