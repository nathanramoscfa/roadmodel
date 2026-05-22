// web/app/(auth)/callback/route.ts
//
// OAuth + magic-link callback handler. Both flows redirect here with
// a `code` query param (Supabase PKCE). Exchanging the code mints a
// session cookie via the createServerClient adapter, then we redirect
// first-time users to /onboarding or to `next` when already onboarded.

import { type NextRequest, NextResponse } from "next/server";

import {
  createSupabaseServerClient,
  E2E_AUTH_COOKIE,
  getE2eTestUserId,
  getServerSession,
} from "@/lib/auth";
import { env } from "@/lib/env";
import { getProfile, isE2eAuthEnabled, isOnboarded } from "@/lib/profile";

function redirectToOnboarding(next: string): NextResponse {
  const onboardingUrl = new URL("/onboarding", env.NEXT_PUBLIC_SITE_URL);
  if (next !== "/") {
    onboardingUrl.searchParams.set("next", next);
  }
  return NextResponse.redirect(onboardingUrl);
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const rawNext = url.searchParams.get("next");
  const next = rawNext && rawNext.startsWith("/") ? rawNext : "/";

  if (!code) {
    const loginUrl = new URL("/login", env.NEXT_PUBLIC_SITE_URL);
    loginUrl.searchParams.set("next", next);
    return NextResponse.redirect(loginUrl);
  }

  if (isE2eAuthEnabled() && code === "e2e-test-code") {
    const userId = getE2eTestUserId();
    const profile = await getProfile(userId);
    const response =
      profile == null || !isOnboarded(profile)
        ? redirectToOnboarding(next)
        : NextResponse.redirect(new URL(next, env.NEXT_PUBLIC_SITE_URL));
    response.cookies.set(E2E_AUTH_COOKIE, userId, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
    });
    return response;
  }

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const errUrl = new URL("/login", env.NEXT_PUBLIC_SITE_URL);
    errUrl.searchParams.set("error", error.message);
    errUrl.searchParams.set("next", next);
    return NextResponse.redirect(errUrl);
  }

  const session = await getServerSession();
  if (!session) {
    return NextResponse.redirect(new URL(next, env.NEXT_PUBLIC_SITE_URL));
  }

  const profile = await getProfile(session.id);
  if (profile == null || !isOnboarded(profile)) {
    return redirectToOnboarding(next);
  }

  return NextResponse.redirect(new URL(next, env.NEXT_PUBLIC_SITE_URL));
}
