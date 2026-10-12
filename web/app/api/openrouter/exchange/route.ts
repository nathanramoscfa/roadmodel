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
// IP (lib/ratelimit.ts), behind the site gate like every other route
// (middleware.ts). OpenRouter's PKCE docs (2026-10-04):
// https://openrouter.ai/docs/use-cases/oauth-pkce

import { sameOrigin, readJson, BodyError, bodyFailure, noStore } from "@/lib/http-boundaries";
import { z } from "zod";
import { NextResponse } from "next/server";

import { OPENROUTER_KEYS_URL } from "@/lib/openrouter-connect";
import { checkOpenRouterExchangeLimit } from "@/lib/ratelimit";
import { visitorKeyLooksValid } from "@/lib/visitor-key";
import { identifyRequest, ipQuotaKey } from "@/lib/withFundingLane";

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
  | "rate_limit_unavailable"
  | "burst_dropped"
  | "openrouter_exchange_failed";

function fail(status: number, error: ExchangeError, headers: Record<string, string> = {}): NextResponse {
  return NextResponse.json({ error }, { status, headers: { ...NO_STORE, ...headers } });
}

async function readBody(req: Request): Promise<{ code: string; verifier: string } | null> {
  if (!(req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) return null;
  try {
    const parsed = z.object({ code: z.string().regex(CODE), code_verifier: z.string().regex(VERIFIER) }).strict().safeParse(await readJson(req, 4096));
    return parsed.success ? { code: parsed.data.code, verifier: parsed.data.code_verifier } : null;
  } catch (error) {
    if (error instanceof BodyError) throw error;
    return null;
  }
}

export async function POST(req: Request): Promise<Response> {
  if (!sameOrigin(req)) return fail(403, "cross_origin");

  const limit = await checkOpenRouterExchangeLimit(ipQuotaKey(identifyRequest(req)));
  if (!limit.allowed) {
    return fail(limit.reason === "rate_limit_unavailable" ? 503 : 429, limit.reason === "rate_limit_unavailable" ? "rate_limit_unavailable" : "burst_dropped", { "Retry-After": String(limit.retryAfter ?? 60) });
  }

  let body;
  try { body = await readBody(req); } catch (error) { return bodyFailure(error); }
  if (!body) return fail(400, "bad_request");

  let res: Response;
  try {
    res = await fetch(OPENROUTER_KEYS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: body.code, code_verifier: body.verifier, code_challenge_method: "S256" }),
      cache: "no-store",
      signal: AbortSignal.timeout(EXCHANGE_TIMEOUT_MS),
      redirect: "error",
    });
  } catch {
    // The error's name only: a message could carry the request.
    console.warn("[openrouter-exchange] key endpoint unreachable");
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
  return noStore(NextResponse.json({ key }, { status: 200, headers: NO_STORE }));
}

function methodNotAllowed(): NextResponse {
  return fail(405, "method_not_allowed", { Allow: "POST" });
}

export const GET = methodNotAllowed;
export const PUT = methodNotAllowed;
export const PATCH = methodNotAllowed;
export const DELETE = methodNotAllowed;
