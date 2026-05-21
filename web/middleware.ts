// web/middleware.ts
//
// Pre-launch password gate. When SITE_PASSWORD is set, every browser
// route is fronted by a password prompt; when unset, the middleware is
// a no-op so PRs can land before the env is seeded. See
// `web/lib/gate.ts` and project memory `project_site_pre_launch_gate`.

import { NextRequest, NextResponse } from "next/server";
import { GATE_COOKIE, deriveGateToken } from "@/lib/gate";

const ALLOWED_PATHS = new Set<string>([
  "/gate",
  "/api/gate",
  "/robots.txt",
  "/favicon.ico",
  "/og-image.png",
]);

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const expected = process.env.SITE_PASSWORD;
  if (!expected) {
    return NextResponse.next();
  }

  const { pathname } = req.nextUrl;
  if (ALLOWED_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const cookieValue = req.cookies.get(GATE_COOKIE)?.value;
  if (cookieValue) {
    const expectedToken = await deriveGateToken(expected);
    if (cookieValue === expectedToken) {
      return NextResponse.next();
    }
  }

  const url = req.nextUrl.clone();
  url.pathname = "/gate";
  url.search = "";
  url.searchParams.set("next", `${pathname}${req.nextUrl.search}`);
  return NextResponse.rewrite(url);
}

export const config = {
  matcher: [
    // Everything except Next.js internals, static assets, and image files.
    "/((?!_next/static|_next/image|.*\\.(?:png|svg|jpg|jpeg|gif|webp|ico|txt)).*)",
  ],
};
