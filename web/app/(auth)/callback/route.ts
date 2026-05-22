// web/app/(auth)/callback/route.ts
//
// OAuth + magic-link callback handler. Both flows redirect here with
// a `code` query param (Supabase PKCE). Exchanging the code mints a
// session cookie via the createServerClient adapter, then we redirect
// to the `next` URL the login form smuggled through.

import { type NextRequest, NextResponse } from "next/server";

import { createSupabaseServerClient } from "@/lib/auth";
import { env } from "@/lib/env";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const rawNext = url.searchParams.get("next");
  const next = rawNext && rawNext.startsWith("/") ? rawNext : "/";

  if (!code) {
    // No code → likely an email-link with the token in the URL
    // fragment, which the browser keeps client-side. Bounce back
    // to /login so the client can finish the handshake.
    const loginUrl = new URL("/login", env.NEXT_PUBLIC_SITE_URL);
    loginUrl.searchParams.set("next", next);
    return NextResponse.redirect(loginUrl);
  }

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const errUrl = new URL("/login", env.NEXT_PUBLIC_SITE_URL);
    errUrl.searchParams.set("error", error.message);
    errUrl.searchParams.set("next", next);
    return NextResponse.redirect(errUrl);
  }

  return NextResponse.redirect(new URL(next, env.NEXT_PUBLIC_SITE_URL));
}
