import "./fixtures/seed-test-env";
import { expect, test } from "@playwright/test";
import { createServerClient } from "@supabase/ssr";
import { Ratelimit } from "@upstash/ratelimit";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";
import * as rl from "../lib/ratelimit";

test("actual Supabase SSR refresh and rejection preserve cookies, forwarded headers and cache policy", async () => {
  const saved = { fetch: globalThis.fetch, url: process.env.SUPABASE_URL, gate: process.env.SITE_PASSWORD, vercel: process.env.VERCEL };
  process.env.SUPABASE_URL = "https://contract.supabase.invalid";
  process.env.SITE_PASSWORD = ""; process.env.VERCEL = "1";
  const uid = "00000000-0000-4000-8000-000000000099";
  const now = Math.floor(Date.now() / 1000);
  const token = (exp: number) => [
    Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
    Buffer.from(JSON.stringify({ sub: uid, exp, iat: now - 200, aud: "authenticated" })).toString("base64url"),
    Buffer.from("synthetic-signature").toString("base64url"),
  ].join(".");
  const user = { id: uid, aud: "authenticated", role: "authenticated", created_at: new Date(0).toISOString(), app_metadata: {}, user_metadata: { filler: "x".repeat(6000) } };
  let mode: "seed" | "refresh" | "invalid" = "seed";
  let refreshes = 0;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input.toString());
    expect(url.origin).toBe("https://contract.supabase.invalid");
    if (url.pathname === "/auth/v1/user") { expect(init?.method).toBe("GET"); return Response.json(user); }
    expect(url.pathname).toBe("/auth/v1/token"); expect(init?.method).toBe("POST");
    expect(["password", "refresh_token"]).toContain(url.searchParams.get("grant_type"));
    if (url.searchParams.get("grant_type") === "refresh_token") refreshes++;
    if (mode === "invalid") return Response.json({ code: "refresh_token_not_found", message: "Synthetic invalid refresh" }, { status: 400, headers: { "x-supabase-api-version": "2024-01-01" } });
    const exp = mode === "seed" ? now - 120 : now + 3600;
    // This is the real GoTrue HTTP shape, not an SDK data/session wrapper.
    return Response.json({ access_token: token(exp), refresh_token: "synthetic-refresh-" + mode, token_type: "bearer", expires_in: exp - now, expires_at: exp, user });
  };
  const jar = new Map<string, string>();
  const client = createServerClient(process.env.SUPABASE_URL, "synthetic-public-key", {
    global: { fetch: globalThis.fetch }, auth: { autoRefreshToken: false, detectSessionInUrl: false },
    cookies: {
      getAll: () => [...jar].map(([name, value]) => ({ name, value })),
      setAll(cookies, headers) {
        expect(headers["Cache-Control"]).toContain("no-store");
        for (const c of cookies) jar.set(c.name, c.value);
      },
    },
  });
  try {
    const seeded = await client.auth.signInWithPassword({ email: ["fixture", "example.invalid"].join("@"), password: "synthetic-password" });
    expect(seeded.error).toBeNull(); expect(seeded.data.user?.id).toBe(uid);
    expect(jar.size).toBeGreaterThanOrEqual(3);
    const old = [...jar].map(([name, value]) => name + "=" + value).join("; ");
    for (const [path, nextMode] of [["/api/profile", "refresh"], ["/api/profile", "invalid"], ["/history", "invalid"]] as const) {
      mode = nextMode;
      const req = new NextRequest("https://contract.invalid" + path, { headers: { cookie: old } });
      const res = await middleware(req);
      const cookies = res.cookies.getAll();
      expect(cookies.length).toBeGreaterThanOrEqual(3);
      expect(cookies.every((c) => c.path === "/" && c.sameSite === "lax" && c.secure === true)).toBe(true);
      expect(res.headers.get("cache-control")).toContain("no-store");
      expect(res.headers.get("expires")).toBe("0"); expect(res.headers.get("pragma")).toBe("no-cache");
      expect(res.headers.get("content-security-policy")).toContain("'nonce-");
      if (mode === "refresh") {
        expect(req.headers.get("cookie")).not.toBe(old);
        expect(res.headers.get("x-middleware-request-cookie")).toBe(req.headers.get("cookie"));
        expect(res.headers.get("x-middleware-request-x-nonce")).toBeTruthy();
      } else {
        expect(cookies.every((c) => c.maxAge === 0 && c.value === "")).toBe(true);
        if (path.startsWith("/api/")) expect(res.status).toBe(401);
        else expect(new URL(res.headers.get("x-middleware-rewrite")!).pathname).toBe("/login");
      }
    }
    expect(refreshes).toBe(3);
  } finally {
    await client.auth.stopAutoRefresh(); globalThis.fetch = saved.fetch;
    for (const [key, value] of Object.entries({ SUPABASE_URL: saved.url, SITE_PASSWORD: saved.gate, VERCEL: saved.vercel })) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

test("actual Upstash timeout shape fails closed at every admission position and bounds remaining reads", async () => {
  const old = process.env.VERCEL; process.env.VERCEL = "1";
  // The installed SDK accepts this exact Redis command subset. No HTTP transport.
  const never = async (): Promise<never> => new Promise(() => {});
  const timeout = new Ratelimit({ redis: { evalsha: never, get: never, set: never }, limiter: Ratelimit.slidingWindow(1, "1 m"), timeout: 10 });
  const actual = await timeout.limit("synthetic");
  expect(actual.success).toBe(true); expect(actual.reason).toBe("timeout"); expect(actual.pending).toBeInstanceOf(Promise);
  const allow = {
    limit: async (): ReturnType<Ratelimit["limit"]> => ({ success: true, limit: 10, remaining: 9, reset: Date.now() + 60000, pending: Promise.resolve() }),
    getRemaining: async () => ({ remaining: 10, limit: 10, reset: Date.now() + 60000 }),
  };
  try {
    for (const slot of ["burst", "invitedDaily"] as const) {
      rl.setTestLaneLimiters({ burst: allow, invitedDaily: allow, [slot]: timeout });
      expect(await rl.checkInvitedLimits("synthetic-user")).toMatchObject({ allowed: false, reason: "rate_limit_unavailable" });
    }
    for (const slot of ["burst", "daily"] as const) {
      rl.setTestVisitorLimiters({ burst: allow, daily: allow, rejected: allow, [slot]: timeout });
      rl.setTestKeylessLimiters({ burst: allow, daily: allow, [slot]: timeout });
      expect(await rl.checkVisitorLimits("synthetic-ip")).toMatchObject({ allowed: false, reason: "rate_limit_unavailable" });
      expect(await rl.checkKeylessLimits("synthetic-ip")).toMatchObject({ allowed: false, reason: "rate_limit_unavailable" });
    }
    rl.setTestExchangeLimiter(timeout);
    expect(await rl.checkOpenRouterExchangeLimit("synthetic-ip")).toMatchObject({ allowed: false, reason: "rate_limit_unavailable" });
    const remaining = { limit: allow.limit, getRemaining: never };
    rl.setTestVisitorLimiters({ burst: allow, daily: allow, rejected: remaining }); rl.setTestRoadmapLimiter(remaining);
    const results = await Promise.all([rl.checkVisitorLimits("synthetic-ip"), rl.checkRoadmapMonthlyLimit("synthetic-user")]);
    for (const result of results) expect(result).toMatchObject({ allowed: false, reason: "rate_limit_unavailable" });
    rl.setTestVisitorLimiters({ burst: allow, daily: allow, rejected: { limit: timeout.limit.bind(timeout), getRemaining: allow.getRemaining } });
    rl.setTestRoadmapLimiter({ limit: timeout.limit.bind(timeout), getRemaining: allow.getRemaining });
    await rl.recordRejectedVisitorKey("synthetic-ip"); await rl.consumeRoadmapMonthlyToken("synthetic-user");
  } finally {
    rl.setTestRoadmapLimiter(null); rl.setTestLaneLimiters(null); rl.setTestVisitorLimiters(null); rl.setTestKeylessLimiters(null); rl.setTestExchangeLimiter(null);
    if (old === undefined) delete process.env.VERCEL; else process.env.VERCEL = old;
  }
});
