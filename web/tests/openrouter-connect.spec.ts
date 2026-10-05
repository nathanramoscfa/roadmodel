// web/tests/openrouter-connect.spec.ts
//
// "Connect OpenRouter" (Phase 4.11 Step 3): the OAuth PKCE flow that returns
// an OpenRouter key to /recommend. Two halves:
//
// - the exchange route (app/api/openrouter/exchange/route.ts), node-side with
//   OpenRouter's key endpoint replaced: the key comes back once with
//   Cache-Control: no-store; only a same-origin POST is served; a refused
//   code is 400 openrouter_exchange_failed; 10 exchanges a minute per IP+UA;
//   and no code, verifier or key reaches the console or an error body;
// - the browser flow against the E2E server, with openrouter.ai and the
//   exchange stubbed by page.route: the authorization URL carries an S256
//   challenge of the stored verifier; the callback clears `code` from the
//   address bar and the history, deletes the verifier, and hands the key to
//   /recommend in memory, where it pays as an OpenRouter key and sits in no
//   browser storage.
//
// Fixture keys and codes are fake and assembled at runtime.

import "./fixtures/seed-test-env";

import { createHash, randomBytes } from "node:crypto";

import { test, expect, type Page } from "@playwright/test";

import { GET, POST } from "../app/api/openrouter/exchange/route";
import { OPENROUTER_KEYS_URL, VERIFIER_STORAGE_KEY } from "../lib/openrouter-connect";
import { OPENROUTER_EXCHANGE_LIMIT, setTestExchangeLimiter } from "../lib/ratelimit";
import { chooseLane } from "./fixtures/lanes";

const RUN = { timeout: 30_000 };

function fakeKey(marker = "canary-0411"): string {
  return ["sk-or-v1", marker, randomBytes(16).toString("hex")].join("-");
}
const CODE = "code-canary-" + randomBytes(12).toString("hex");
const VERIFIER = randomBytes(48).toString("base64url");
const ORIGIN = "http://localhost";
const ROUTE_URL = `${ORIGIN}/api/openrouter/exchange`;

// --- The exchange route (node-side) -----------------------------------------

test.describe("the exchange route", () => {
  let calls: { url: string; body: string }[] = [];
  let upstream: () => Response;
  let consoleOut: string[] = [];
  const realFetch = globalThis.fetch;
  const CONSOLE = ["log", "info", "warn", "error", "debug"] as const;
  const realConsole = Object.fromEntries(CONSOLE.map((m) => [m, console[m]]));
  const KEY = fakeKey();

  test.beforeEach(() => {
    calls = [];
    consoleOut = [];
    upstream = () => Response.json({ key: KEY });
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      calls.push({ url, body: typeof init?.body === "string" ? init.body : "" });
      return upstream();
    }) as typeof fetch;
    const used: Record<string, number> = {};
    setTestExchangeLimiter({
      limit: async (key: string) => {
        used[key] = (used[key] ?? 0) + 1;
        return { success: used[key] <= OPENROUTER_EXCHANGE_LIMIT } as never;
      },
    });
    for (const m of CONSOLE) {
      console[m] = (...args: unknown[]) => {
        consoleOut.push(args.map((a) => (a instanceof Error ? `${a.message} ${a.stack}` : String(a))).join(" "));
      };
    }
  });

  test.afterEach(() => {
    globalThis.fetch = realFetch;
    setTestExchangeLimiter(null);
    for (const m of CONSOLE) console[m] = realConsole[m] as typeof console.log;
  });

  function post(
    body: unknown = { code: CODE, code_verifier: VERIFIER },
    headers: Record<string, string> = { origin: ORIGIN, "sec-fetch-site": "same-origin" },
  ): Request {
    return new Request(ROUTE_URL, {
      method: "POST",
      headers: { "content-type": "application/json", "user-agent": "spec", ...headers },
      body: JSON.stringify(body),
    });
  }

  // Nothing secret anywhere the route writes: the console, the error body.
  function expectNothingLogged(...secrets: string[]) {
    const out = consoleOut.join("\n");
    for (const s of secrets) expect(out).not.toContain(s);
  }

  test("a good code: the key once, no-store, one exchange at OpenRouter's key endpoint", async () => {
    const res = await POST(post());
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ key: KEY });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(OPENROUTER_KEYS_URL);
    expect(JSON.parse(calls[0].body)).toEqual({
      code: CODE,
      code_verifier: VERIFIER,
      code_challenge_method: "S256",
    });
    expectNothingLogged(CODE, VERIFIER, KEY);
  });

  test("a bad code: 400 openrouter_exchange_failed, no-store, nothing logged but the status", async () => {
    for (const status of [400, 403]) {
      consoleOut = [];
      upstream = () => Response.json({ error: { message: `Invalid code ${CODE}` } }, { status });
      const res = await POST(post());
      expect(res.status).toBe(400);
      expect(res.headers.get("cache-control")).toBe("no-store");
      const text = await res.text();
      expect(JSON.parse(text)).toEqual({ error: "openrouter_exchange_failed" });
      for (const s of [CODE, VERIFIER]) expect(text).not.toContain(s);
      expect(consoleOut.join("\n")).toContain(String(status));
      expectNothingLogged(CODE, VERIFIER);
    }
  });

  test("OpenRouter unreachable, or answering without a key: 502, the key never logged", async () => {
    const answers: (() => Response)[] = [
      () => {
        throw new Error(`connect ECONNRESET while sending ${CODE}`);
      },
      () => Response.json({ key: "not-a-key" }),
      () => new Response("<html>", { status: 200 }),
    ];
    for (const answer of answers) {
      upstream = answer;
      const res = await POST(post());
      expect(res.status).toBe(502);
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(await res.json()).toEqual({ error: "openrouter_exchange_failed" });
    }
    expectNothingLogged(CODE, VERIFIER, KEY);
  });

  test("same-origin only: another Origin, none, or a cross-site fetch is 403 with no exchange", async () => {
    const refused: Record<string, string>[] = [
      { origin: "https://evil.example" },
      {},
      { origin: ORIGIN, "sec-fetch-site": "cross-site" },
      { origin: ORIGIN, "sec-fetch-site": "same-site" },
    ];
    for (const headers of refused) {
      const res = await POST(post(undefined, headers));
      expect(res.status).toBe(403);
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(await res.json()).toEqual({ error: "cross_origin" });
    }
    expect(calls).toEqual([]);
  });

  test("POST only: any other method is 405 with Allow: POST", async () => {
    const res = await GET();
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("POST");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(calls).toEqual([]);
  });

  test("a malformed body is 400 bad_request with no exchange", async () => {
    const bodies: unknown[] = [
      {},
      { code: CODE },
      { code_verifier: VERIFIER },
      { code: CODE, code_verifier: "too-short" },
      { code: `${CODE} spaced`, code_verifier: VERIFIER },
      { code: 1, code_verifier: VERIFIER },
    ];
    for (const body of bodies) {
      const res = await POST(post(body));
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: "bad_request" });
    }
    const form = new Request(ROUTE_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", origin: ORIGIN },
      body: `code=${CODE}&code_verifier=${VERIFIER}`,
    });
    expect((await POST(form)).status).toBe(400);
    expect(calls).toEqual([]);
  });

  test("rate limit: 10 exchanges a minute per IP+UA, then 429 before OpenRouter", async () => {
    for (let i = 0; i < OPENROUTER_EXCHANGE_LIMIT; i++) {
      expect((await POST(post())).status).toBe(200);
    }
    const over = await POST(post());
    expect(over.status).toBe(429);
    expect(over.headers.get("retry-after")).toBe("60");
    expect(await over.json()).toEqual({ error: "burst_dropped" });
    expect(calls).toHaveLength(OPENROUTER_EXCHANGE_LIMIT);
    // Another browser (UA) has its own allowance.
    expect((await POST(post(undefined, { origin: ORIGIN, "user-agent": "other" }))).status).toBe(200);
  });
});

// --- The browser flow --------------------------------------------------------

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

// Click "Connect OpenRouter" with openrouter.ai stubbed; the authorization URL
// the browser went to, this site's origin, and the verifier the site stored
// (read after stepping back: sessionStorage is per origin, and the tab is on
// openrouter.ai until then).
async function connect(page: Page): Promise<{ auth: URL; origin: string; verifier: string | null }> {
  await page.route("https://openrouter.ai/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<p>OpenRouter consent (stub)</p>" }),
  );
  await page.goto("/recommend");
  await chooseLane(page, "openrouter", "visitor-key-panel");
  await expect(page.getByTestId("visitor-key-panel")).toContainText(
    "OpenRouter is a prepaid account that pays for many AI models; connecting it lets roadmodel bill your recommendations to your OpenRouter credits.",
  );
  const origin = new URL(page.url()).origin;
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().startsWith("https://openrouter.ai/auth"), RUN),
    page.getByTestId("openrouter-connect").click(),
  ]);
  await expect(page).toHaveURL(/^https:\/\/openrouter\.ai\/auth/, RUN);
  await page.goBack();
  await expect(page).toHaveURL(/\/recommend$/, RUN);
  const verifier = await page.evaluate((k) => window.sessionStorage.getItem(k), VERIFIER_STORAGE_KEY);
  return { auth: new URL(request.url()), origin, verifier };
}

function stubExchange(page: Page, answer: { status: number; body: unknown }) {
  const posted: unknown[] = [];
  void page.route("**/api/openrouter/exchange", async (route) => {
    posted.push(route.request().postDataJSON());
    await route.fulfill({
      status: answer.status,
      contentType: "application/json",
      headers: { "Cache-Control": "no-store" },
      body: JSON.stringify(answer.body),
    });
  });
  return posted;
}

test("Connect OpenRouter: an S256 challenge of a random verifier kept in sessionStorage", async ({ page }) => {
  const { auth, origin, verifier } = await connect(page);
  expect(auth.origin + auth.pathname).toBe("https://openrouter.ai/auth");
  expect(auth.searchParams.get("callback_url")).toBe(`${origin}/recommend/openrouter`);
  expect(auth.searchParams.get("code_challenge_method")).toBe("S256");
  expect(verifier).toMatch(/^[A-Za-z0-9_-]{43,128}$/);
  const challenge = createHash("sha256").update(verifier as string).digest("base64url");
  expect(auth.searchParams.get("code_challenge")).toBe(challenge);
});

test("the callback: code out of the URL and history, verifier deleted, the key pays from memory only", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const key = fakeKey();
  const { verifier } = await connect(page);
  expect(verifier).not.toBeNull();
  const posted = stubExchange(page, { status: 200, body: { key } });

  // OpenRouter sends the visitor back with the code.
  await page.goto(`/recommend/openrouter?code=${CODE}`);
  await expect(page).toHaveURL(/\/recommend$/, RUN);
  expect(posted).toEqual([{ code: CODE, code_verifier: verifier }]);

  // The key is in the holder: the panel is open on it, as an OpenRouter key.
  await expect(page.getByTestId("visitor-key-toggle")).toHaveText(/Your OpenRouter key/, RUN);
  await expect(page.getByTestId("visitor-key-provider")).toHaveValue("openrouter");

  // ...and nowhere a browser keeps values; the verifier is gone; the code is
  // in neither the address bar nor the history entry before it.
  const stored = await storedText(page);
  for (const s of [key, CODE, VERIFIER_STORAGE_KEY]) expect(stored).not.toContain(s);
  expect(page.url()).not.toContain(CODE);

  // It pays: the recommendation request carries it as an OpenRouter key.
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith("/api/recommend"), RUN),
    (async () => {
      await page.getByPlaceholder(/Describe the task/i).fill("Refactor a data pipeline into modules");
      await page.getByRole("button", { name: /^Recommend/ }).click();
    })(),
  ]);
  const headers = await request.allHeaders();
  expect(headers["x-roadmodel-visitor-provider"]).toBe("openrouter");
  expect(headers["x-roadmodel-visitor-key"]).toBe(key);
  expect(request.postData() ?? "").not.toContain(key);
  await expect(page.getByTestId("visitor-key-status")).toBeVisible(RUN);
  expect(await storedText(page)).not.toContain(key);

  await page.goBack();
  expect(page.url()).not.toContain(CODE);
});

test("the callback: a refused exchange deletes the verifier and stores no key", async ({ page }) => {
  await connect(page);
  const posted = stubExchange(page, { status: 400, body: { error: "openrouter_exchange_failed" } });
  await page.goto(`/recommend/openrouter?code=${CODE}`);
  await expect(page.getByTestId("openrouter-callback-error")).toBeVisible(RUN);
  expect(posted).toHaveLength(1);
  expect(page.url()).not.toContain(CODE);
  const stored = await storedText(page);
  for (const s of [CODE, VERIFIER_STORAGE_KEY]) expect(stored).not.toContain(s);
});

test("the callback: no verifier (a visit not started here) makes no exchange", async ({ page }) => {
  const posted = stubExchange(page, { status: 200, body: { key: fakeKey() } });
  await page.goto(`/recommend/openrouter?code=${CODE}`);
  await expect(page.getByTestId("openrouter-callback-error")).toBeVisible(RUN);
  expect(posted).toEqual([]);
  expect(page.url()).not.toContain(CODE);
});
