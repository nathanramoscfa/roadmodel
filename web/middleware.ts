// web/middleware.ts
//
// Three concerns, processed in order:
//
//   1. Phase 3 Step 5.5b pre-launch password gate. When SITE_PASSWORD
//      is set, every browser route is fronted by a password prompt
//      (rewrite to /gate); when unset, the gate branch is inert. The
//      gate lifts in Step 8 of Phase 4 deliberately.
//
//   2. Phase 4 Step 1 Supabase auth validation. Once the gate is
//      satisfied (or off), protected /api/* mutation routes and
//      signed-in-only page routes are validated against the Supabase
//      session cookie. Missing or invalid → 401 for /api/*, rewrite
//      to /login?next=<original> for page routes.
//
//   3. Content-Security-Policy. A per-request nonce + CSP is attached to
//      EVERY response. Next.js reads the nonce from the request CSP header
//      and stamps it onto every script it emits (bootstrap + streaming RSC
//      payload); our one inline theme script reads it via headers() in
//      app/layout.tsx. Defense-in-depth (no XSS sink today) layered on the
//      static headers in next.config.mjs.
//
// Public routes (/, /recommend, /api/recommend, /privacy, /terms,
// /login, /gate, /api/gate, the auth callback) bypass branches 1-2
// after the gate check, but still get the CSP.

import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import { E2E_AUTH_COOKIE } from "@/lib/auth";
import { isE2eAuthEnabled } from "@/lib/profile";
import { GATE_COOKIE, deriveGateToken } from "@/lib/gate";

const GATE_ALLOWED_PATHS = new Set<string>([
  "/gate",
  "/api/gate",
  "/robots.txt",
  "/favicon.ico",
  "/og-image.png",
]);

const PROTECTED_API_PREFIXES = [
  "/api/profile",
  "/api/roadmap",
  "/api/roadmaps",
] as const;

const PROTECTED_PAGE_PATHS = new Set<string>([
  "/history",
  "/onboarding",
]);

function isProtectedApi(pathname: string): boolean {
  return PROTECTED_API_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isProtectedPage(pathname: string): boolean {
  return PROTECTED_PAGE_PATHS.has(pathname);
}

async function gatePasses(req: NextRequest, expected: string): Promise<boolean> {
  const cookieValue = req.cookies.get(GATE_COOKIE)?.value;
  if (!cookieValue) {
    return false;
  }
  const expectedToken = await deriveGateToken(expected);
  return cookieValue === expectedToken;
}

// ──── CSP / nonce ──────────────────────────────────────────────────────
// 'strict-dynamic' lets the nonce'd Next bootstrap load the chunked bundles;
// connect-src is opened to Supabase (REST/auth https + realtime wss) since the
// browser client talks to it directly. style-src keeps 'unsafe-inline' (Next +
// Tailwind inject inline <style>; far lower risk than inline script). Dev adds
// 'unsafe-eval' for Turbopack/webpack HMR.
function buildCsp(nonce: string): string {
  let supabase = "";
  try {
    const u = new URL(process.env.SUPABASE_URL ?? "");
    supabase = `${u.origin} ${u.origin.replace(/^https:/, "wss:")}`;
  } catch {
    supabase = "";
  }
  const scriptExtra =
    process.env.NODE_ENV !== "production" ? " 'unsafe-eval'" : "";
  return [
    `default-src 'self'`,
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${scriptExtra}`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data: blob:`,
    `font-src 'self'`,
    `connect-src 'self' ${supabase}`.trim(),
    `frame-ancestors 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `object-src 'none'`,
  ].join("; ");
}

function newNonce(): string {
  return btoa(crypto.randomUUID());
}

// Clone inbound headers + inject the nonce and CSP so Next renders scripts with
// the nonce. Passed to every NextResponse via { request: { headers } }.
function withNonceRequest(req: NextRequest, nonce: string, csp: string): Headers {
  const headers = new Headers(req.headers);
  headers.set("x-nonce", nonce);
  headers.set("content-security-policy", csp);
  return headers;
}

function gateRewrite(
  req: NextRequest,
  requestHeaders: Headers,
  csp: string,
): NextResponse {
  const url = req.nextUrl.clone();
  url.pathname = "/gate";
  url.search = "";
  url.searchParams.set("next", `${req.nextUrl.pathname}${req.nextUrl.search}`);
  const res = NextResponse.rewrite(url, { request: { headers: requestHeaders } });
  res.headers.set("content-security-policy", csp);
  return res;
}

function loginRewrite(
  req: NextRequest,
  requestHeaders: Headers,
  csp: string,
): NextResponse {
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  url.searchParams.set("next", `${req.nextUrl.pathname}${req.nextUrl.search}`);
  const res = NextResponse.rewrite(url, { request: { headers: requestHeaders } });
  res.headers.set("content-security-policy", csp);
  return res;
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;

  // Per-request nonce + CSP, attached to every return path below.
  const nonce = newNonce();
  const csp = buildCsp(nonce);
  const requestHeaders = withNonceRequest(req, nonce, csp);
  const withCsp = (res: NextResponse): NextResponse => {
    res.headers.set("content-security-policy", csp);
    return res;
  };

  // ──── Branch 1: pre-launch password gate ──────────────────────────
  const expectedPassword = process.env.SITE_PASSWORD;
  if (expectedPassword && !GATE_ALLOWED_PATHS.has(pathname)) {
    if (!(await gatePasses(req, expectedPassword))) {
      return gateRewrite(req, requestHeaders, csp);
    }
  }

  // ──── Branch 2: Supabase auth validation ──────────────────────────
  const apiProtected = isProtectedApi(pathname);
  const pageProtected = isProtectedPage(pathname);
  if (!apiProtected && !pageProtected) {
    return withCsp(NextResponse.next({ request: { headers: requestHeaders } }));
  }

  // Build a cookies-aware Supabase client wired to the NextRequest /
  // NextResponse cookie surface. The setAll callback runs when
  // Supabase rotates the access token; we propagate those updates
  // onto the response so the browser keeps the refreshed cookies.
  let supabaseResponse = NextResponse.next({
    request: { headers: requestHeaders },
  });
  if (isE2eAuthEnabled() && req.cookies.get(E2E_AUTH_COOKIE)?.value) {
    return withCsp(supabaseResponse);
  }
  const supabase = createServerClient(
    process.env.SUPABASE_URL ?? "",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    {
      cookies: {
        getAll() {
          return req.cookies.getAll();
        },
        setAll(cookiesToSet) {
          for (const { name, value } of cookiesToSet) {
            req.cookies.set(name, value);
          }
          supabaseResponse = NextResponse.next({
            request: { headers: requestHeaders },
          });
          for (const { name, value, options } of cookiesToSet) {
            supabaseResponse.cookies.set(name, value, options);
          }
        },
      },
    },
  );

  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) {
    if (apiProtected) {
      return withCsp(
        NextResponse.json({ error: "unauthorized" }, { status: 401 }),
      );
    }
    return loginRewrite(req, requestHeaders, csp);
  }

  return withCsp(supabaseResponse);
}

export const config = {
  matcher: [
    // Everything except Next.js internals, static assets, and image files.
    "/((?!_next/static|_next/image|.*\\.(?:png|svg|jpg|jpeg|gif|webp|ico|txt)).*)",
  ],
};
