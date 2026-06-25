// web/app/api/gate/route.ts
import { NextRequest, NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "node:crypto";
import { GATE_COOKIE, deriveGateToken } from "@/lib/gate";
import {
  fireGateAlert,
  gateLockState,
  recordGateFailure,
} from "@/lib/gateGuard";

const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7; // 7 days

// Constant-time password comparison. Raw `submitted !== expected` short-
// circuits at the first differing byte, leaking a timing oracle that — given
// enough attempts — lets a remote attacker recover SITE_PASSWORD byte by byte.
// Hash both sides to fixed-length SHA-256 digests first so neither the compare
// timing NOR the buffer length reveals anything about the password, then
// compare with timingSafeEqual. Mirrors the pattern in lib/withRateLimit.ts.
function passwordMatches(submitted: string, expected: string): boolean {
  const a = createHash("sha256").update(submitted).digest();
  const b = createHash("sha256").update(expected).digest();
  return timingSafeEqual(a, b);
}

function safeNext(raw: string | null): string {
  if (typeof raw !== "string" || raw.length === 0) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function clientIp(req: NextRequest): string {
  // Trusted client IP for the brute-force lockout (see lib/gateGuard.ts). On
  // Vercel `x-forwarded-for` is OVERWRITTEN with the real client IP and any
  // client-supplied value is dropped, specifically to prevent IP spoofing
  // (https://vercel.com/docs/headers/request-headers#x-forwarded-for). So the
  // per-IP lockout CANNOT be evaded or poisoned by sending a forged
  // X-Forwarded-For here. Keep `[0]`; do not switch to the last entry (that is
  // only correct on append-style proxies). Revisit if deployed off Vercel.
  return req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
}

function failureRedirect(
  req: NextRequest,
  next: string,
  params: Record<string, string>,
): NextResponse {
  const url = new URL("/gate", req.url);
  url.searchParams.set("next", next);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = NextResponse.redirect(url, 303);
  if (params.retry) res.headers.set("Retry-After", params.retry);
  return res;
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const expected = process.env.SITE_PASSWORD;
  if (!expected) {
    return NextResponse.redirect(new URL("/", req.url), 303);
  }

  const form = await req.formData();
  const submitted = form.get("password");
  const next = safeNext(
    typeof form.get("next") === "string"
      ? (form.get("next") as string)
      : null,
  );

  const ip = clientIp(req);
  const ua = req.headers.get("user-agent") ?? "unknown";

  // Already locked out? Reject before even checking the password, so a locked
  // client cannot keep probing. fireGateAlert dedups per window, so a re-submit
  // while locked does not re-notify.
  const lock = await gateLockState(ip);
  if (lock.locked) {
    await fireGateAlert(ip, ua);
    return failureRedirect(req, next, {
      locked: "1",
      retry: String(lock.retryAfter),
    });
  }

  if (typeof submitted !== "string" || !passwordMatches(submitted, expected)) {
    // Wrong password — count the failure. If it trips the lockout, alert.
    const after = await recordGateFailure(ip);
    if (after.locked) {
      await fireGateAlert(ip, ua);
      return failureRedirect(req, next, {
        locked: "1",
        retry: String(after.retryAfter),
      });
    }
    return failureRedirect(req, next, {
      error: "1",
      remaining: String(after.remaining),
    });
  }

  const token = await deriveGateToken(expected);
  const response = NextResponse.redirect(new URL(next, req.url), 303);
  response.cookies.set({
    name: GATE_COOKIE,
    value: token,
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
  });
  return response;
}
