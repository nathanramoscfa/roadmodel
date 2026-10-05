// web/app/api/openrouter/exchange/route.ts
//
// The server half of "Connect OpenRouter" (OAuth PKCE): the callback page
// (app/recommend/openrouter/page.tsx) posts the authorization `code` and its
// PKCE `code_verifier` here, this route exchanges them at OpenRouter's key
// endpoint, and the key OpenRouter issues goes back to the page in the JSON
// body, once. The exchange runs server-side because the CSP keeps the
// browser's fetches to 'self'.
//
// The route holds nothing: it logs no code, verifier or key (failures log the
// HTTP status alone), writes no audit row, and marks every answer
// Cache-Control: no-store. It takes a same-origin POST only, 10 a minute per
// IP+UA (lib/ratelimit.ts), behind the site gate like every other route
// (middleware.ts). OpenRouter's PKCE docs (2026-10-04):
// https://openrouter.ai/docs/use-cases/oauth-pkce

import { NextResponse } from "next/server";

import { OPENROUTER_KEYS_URL } from "@/lib/openrouter-connect";
import { checkOpenRouterExchangeLimit } from "@/lib/ratelimit";
import { visitorKeyLooksValid } from "@/lib/visitor-key";
import { identifyRequest, ipUaKey } from "@/lib/withFundingLane";

const NO_STORE = { "Cache-Control": "no-store", Pragma: "no-cache" } as const;
const EXCHANGE_TIMEOUT_MS = 15_000;

// An authorization code is opaque; this bounds its alphabet and length. A PKCE
// verifier is 43 to 128 unreserved characters (RFC 7636 §4.1).
const CODE = /^[A-Za-z0-9_\-.~]{1,512}$/;
const VERIFIER = /^[A-Za-z0-9_\-.~]{43,128}$/;

type ExchangeError =
  | "method_not_allowed"
  | "cross_origin"
  | "bad_request"
  | "burst_dropped"
  | "openrouter_exchange_failed";

function fail(status: number, error: ExchangeError, headers: Record<string, string> = {}): NextResponse {
  return NextResponse.json({ error }, { status, headers: { ...NO_STORE, ...headers } });
}

// A same-origin request carries an Origin equal to this site's, and, from a
// browser that sends it, Sec-Fetch-Site same-origin. A missing Origin is
// refused: every browser sends one on a POST fetch.
function sameOrigin(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (!origin || origin !== new URL(req.url).origin) return false;
  const site = req.headers.get("sec-fetch-site");
  return site === null || site === "same-origin";
}

async function readBody(req: Request): Promise<{ code: string; verifier: string } | null> {
  if (!(req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) return null;
  try {
    const body = (await req.json()) as { code?: unknown; code_verifier?: unknown };
    const { code, code_verifier: verifier } = body;
    if (typeof code !== "string" || typeof verifier !== "string") return null;
    return CODE.test(code) && VERIFIER.test(verifier) ? { code, verifier } : null;
  } catch {
    return null;
  }
}

export async function POST(req: Request): Promise<NextResponse> {
  if (!sameOrigin(req)) return fail(403, "cross_origin");

  const limit = await checkOpenRouterExchangeLimit(ipUaKey(identifyRequest(req)));
  if (!limit.allowed) {
    return fail(429, "burst_dropped", { "Retry-After": String(limit.retryAfter ?? 60) });
  }

  const body = await readBody(req);
  if (!body) return fail(400, "bad_request");

  let res: Response;
  try {
    res = await fetch(OPENROUTER_KEYS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: body.code, code_verifier: body.verifier, code_challenge_method: "S256" }),
      cache: "no-store",
      signal: AbortSignal.timeout(EXCHANGE_TIMEOUT_MS),
    });
  } catch (err) {
    // The error's name only: a message could carry the request.
    console.warn(`[openrouter-exchange] key endpoint unreachable (${err instanceof Error ? err.name : "unknown"})`);
    return fail(502, "openrouter_exchange_failed");
  }
  if (!res.ok) {
    // OpenRouter refused the code or the verifier (400/403, or expired).
    console.warn(`[openrouter-exchange] key endpoint answered ${res.status}`);
    return fail(400, "openrouter_exchange_failed");
  }
  const answer = (await res.json().catch(() => null)) as { key?: unknown } | null;
  const key = typeof answer?.key === "string" ? answer.key.trim() : "";
  if (!visitorKeyLooksValid("openrouter", key)) {
    console.warn("[openrouter-exchange] key endpoint answered without an OpenRouter key");
    return fail(502, "openrouter_exchange_failed");
  }
  return NextResponse.json({ key }, { status: 200, headers: NO_STORE });
}

function methodNotAllowed(): NextResponse {
  return fail(405, "method_not_allowed", { Allow: "POST" });
}

export const GET = methodNotAllowed;
export const PUT = methodNotAllowed;
export const PATCH = methodNotAllowed;
export const DELETE = methodNotAllowed;
