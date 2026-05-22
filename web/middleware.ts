// web/middleware.ts
//
// Two stacked branches, processed in order:
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
// Public routes (/, /recommend, /api/recommend, /privacy, /terms,
// /login, /gate, /api/gate, the auth callback) bypass both branches
// after the gate check.

import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

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

function gateRewrite(req: NextRequest): NextResponse {
  const url = req.nextUrl.clone();
  url.pathname = "/gate";
  url.search = "";
  url.searchParams.set("next", `${req.nextUrl.pathname}${req.nextUrl.search}`);
  return NextResponse.rewrite(url);
}

function loginRewrite(req: NextRequest): NextResponse {
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  url.searchParams.set("next", `${req.nextUrl.pathname}${req.nextUrl.search}`);
  return NextResponse.rewrite(url);
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;

  // ──── Branch 1: pre-launch password gate ──────────────────────────
  const expectedPassword = process.env.SITE_PASSWORD;
  if (expectedPassword && !GATE_ALLOWED_PATHS.has(pathname)) {
    if (!(await gatePasses(req, expectedPassword))) {
      return gateRewrite(req);
    }
  }

  // ──── Branch 2: Supabase auth validation ──────────────────────────
  const apiProtected = isProtectedApi(pathname);
  const pageProtected = isProtectedPage(pathname);
  if (!apiProtected && !pageProtected) {
    return NextResponse.next();
  }

  // Build a cookies-aware Supabase client wired to the NextRequest /
  // NextResponse cookie surface. The setAll callback runs when
  // Supabase rotates the access token; we propagate those updates
  // onto the response so the browser keeps the refreshed cookies.
  let supabaseResponse = NextResponse.next({ request: req });
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
          supabaseResponse = NextResponse.next({ request: req });
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
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    return loginRewrite(req);
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    // Everything except Next.js internals, static assets, and image files.
    "/((?!_next/static|_next/image|.*\\.(?:png|svg|jpg|jpeg|gif|webp|ico|txt)).*)",
  ],
};
