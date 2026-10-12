import "./fixtures/seed-test-env";
import { expect, test } from "@playwright/test";
import { GenerateContentResponse, GoogleGenAI } from "@google/genai";
import { Redis } from "@upstash/redis";
import { GEMINI_REQUEST_TIMEOUT_MS, setTestGeminiClient, withGeminiRetry } from "../lib/gemini-client";
import { setTestRedisClient } from "../lib/llm-cache";
import { createRoadmapStream } from "../lib/roadmap-engine";

const chunk = 'data: {"candidates":[{"content":{"parts":[{"text":"Synthetic answer"}],"role":"model"}}]}\n\n';

for (const phase of ["cache-headers", "cache-body", "stream-headers", "stream-body"] as const) {
  test(`shared deadline aborts actual Google SDK ${phase}`, async () => {
    const saved = { fetch: globalThis.fetch, timeout: AbortSignal.timeout, warn: console.warn };
    const client = new GoogleGenAI({ apiKey: "synthetic-key", httpOptions: { timeout: GEMINI_REQUEST_TIMEOUT_MS, retryOptions: { attempts: 1 } } });
    const deadlines: number[] = [];
    const calls: string[] = [];
    const timers: ReturnType<typeof setTimeout>[] = [];
    let transportAborted = false;
    AbortSignal.timeout = (ms) => { deadlines.push(ms); return saved.timeout(80); };
    console.warn = () => {};
    globalThis.fetch = async (input, init) => {
      const url = new URL(String(input));
      if (url.origin === "https://redis.invalid") return Response.json([{ result: null }]);
      expect(url.origin).toBe("https://generativelanguage.googleapis.com");
      const cache = url.pathname.endsWith("/cachedContents");
      calls.push(cache ? "cache" : "stream");
      if (cache && phase.startsWith("stream")) return Response.json({ name: "cachedContents/synthetic" });
      if (!cache && phase.startsWith("cache")) return new Response(chunk, { headers: { "Content-Type": "text/event-stream" } });
      // Fetch's real abort contract covers both pending headers and a body
      // already returned to the SDK. A fallback timer makes the old code fail
      // deterministically instead of hanging the test process.
      if (phase.endsWith("headers")) return new Promise<Response>((_, reject) => {
        const abort = () => { transportAborted = true; reject(new DOMException("Aborted", "AbortError")); };
        init?.signal?.addEventListener("abort", abort, { once: true });
        timers.push(setTimeout(() => reject(new Error("Synthetic transport deadline missing")), 600));
      });
      return new Response(new ReadableStream({ start(controller) {
        init?.signal?.addEventListener("abort", () => {
          transportAborted = true; controller.error(new DOMException("Aborted", "AbortError"));
        }, { once: true });
        controller.enqueue(new TextEncoder().encode(cache ? "{" : chunk));
        timers.push(setTimeout(() => controller.error(new Error("Synthetic body deadline missing")), 600));
      } }), { headers: { "Content-Type": cache ? "application/json" : "text/event-stream" } });
    };
    setTestRedisClient(new Redis({ url: "https://redis.invalid", token: "synthetic-token", retry: false }));
    setTestGeminiClient(client);
    try {
      const work = async () => {
        for await (const event of createRoadmapStream({ model: "gemini-2.5-flash", profile: null, messages: [{ id: "fixture", created_at: "2000-01-01T00:00:00Z", role: "user", content: "Synthetic prompt" }] })) {
          expect(event.type).not.toBe("message_complete");
        }
      };
      await expect(work()).rejects.toBeInstanceOf(Error);
      expect(deadlines).toEqual([GEMINI_REQUEST_TIMEOUT_MS]);
      expect(transportAborted).toBe(true);
      expect(calls).toEqual(phase.startsWith("cache") ? ["cache"] : ["cache", "stream"]);
    } finally {
      for (const timer of timers) clearTimeout(timer);
      globalThis.fetch = saved.fetch; AbortSignal.timeout = saved.timeout; console.warn = saved.warn;
      setTestRedisClient(null); setTestGeminiClient(null);
    }
  });
}

test("already cancelled requests and cancelled retry delays start no further provider work", async () => {
  const saved = globalThis.fetch;
  let fetches = 0;
  globalThis.fetch = async () => { fetches++; return Response.json({ name: "cachedContents/synthetic" }); };
  const abort = new AbortController(); abort.abort();
  try {
    await expect((async () => {
      for await (const event of createRoadmapStream({ signal: abort.signal, model: "gemini-2.5-flash", profile: null, messages: [{ id: "fixture", created_at: "2000-01-01T00:00:00Z", role: "user", content: "Synthetic prompt" }] })) void event;
    })()).rejects.toBeInstanceOf(Error);
    expect(fetches).toBe(0);
    let attempts = 0;
    const retryAbort = new AbortController();
    const work = withGeminiRetry(async () => {
      attempts++; setTimeout(() => retryAbort.abort(), 5);
      throw new Error("503 unavailable");
    }, 2, retryAbort.signal);
    await expect(work).rejects.toBeInstanceOf(Error);
    expect(attempts).toBe(1);
  } finally { globalThis.fetch = saved; }
});

test("real SDK performs one cache attempt and at most two generation attempts", async () => {
  const saved = { fetch: globalThis.fetch, warn: console.warn };
  const client = new GoogleGenAI({ apiKey: "synthetic-key", httpOptions: { timeout: GEMINI_REQUEST_TIMEOUT_MS, retryOptions: { attempts: 1 } } });
  const calls: string[] = [];
  console.warn = () => {};
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    if (url.origin === "https://redis.invalid") return Response.json([{ result: null }]);
    expect(url.origin).toBe("https://generativelanguage.googleapis.com");
    calls.push(url.pathname.endsWith("/cachedContents") ? "cache" : "stream");
    return Response.json({ error: { code: 503, status: "UNAVAILABLE", message: "Synthetic unavailable" } }, { status: 503 });
  };
  setTestRedisClient(new Redis({ url: "https://redis.invalid", token: "synthetic-token", retry: false }));
  setTestGeminiClient(client);
  try {
    await expect((async () => {
      for await (const event of createRoadmapStream({ model: "gemini-2.5-flash", profile: null, messages: [{ id: "fixture", created_at: "2000-01-01T00:00:00Z", role: "user", content: "Synthetic prompt" }] })) void event;
    })()).rejects.toBeInstanceOf(Error);
    expect(calls).toEqual(["cache", "stream", "stream"]);
  } finally {
    globalThis.fetch = saved.fetch; console.warn = saved.warn;
    setTestRedisClient(null); setTestGeminiClient(null);
  }
});

test("cancellation at the SDK iterator completion boundary does not report success", async () => {
  const saved = globalThis.fetch;
  const client = new GoogleGenAI({ apiKey: "synthetic-key" });
  const abort = new AbortController();
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    if (url.origin === "https://redis.invalid") return Response.json([{ result: null }]);
    expect(url.origin).toBe("https://generativelanguage.googleapis.com");
    return Response.json({ name: "cachedContents/synthetic" });
  };
  // Assignment is checked against the installed SDK's actual callable and
  // returned iterator type; chunks are real SDK response instances.
  client.models.generateContentStream = async (args) => {
    expect(args.config?.abortSignal).toBeInstanceOf(AbortSignal);
    expect(Array.isArray(args.contents)).toBe(true);
    return (async function* () {
      const response = new GenerateContentResponse();
      response.candidates = [{ content: { role: "model", parts: [{ text: "Synthetic answer" }] } }];
      yield response;
      abort.abort();
    })();
  };
  setTestRedisClient(new Redis({ url: "https://redis.invalid", token: "synthetic-token", retry: false }));
  setTestGeminiClient(client);
  try {
    const events: string[] = [];
    await expect((async () => {
      for await (const event of createRoadmapStream({ signal: abort.signal, model: "gemini-2.5-flash", profile: null, messages: [] })) events.push(event.type);
    })()).rejects.toBeInstanceOf(Error);
    expect(events).toEqual(["message_delta"]);
  } finally {
    globalThis.fetch = saved; setTestRedisClient(null); setTestGeminiClient(null);
  }
});
