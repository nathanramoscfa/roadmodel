// web/lib/auth.ts
//
// Server-side Supabase auth helpers for Phase 4 Step 1. The browser
// half of the integration uses createBrowserClient directly from
// @supabase/ssr inside client components (see web/app/(auth)/login/
// LoginForm.tsx). The middleware path lives in web/middleware.ts and
// uses a NextRequest-cookies adapter rather than next/headers, so the
// createSupabaseServerClient helper here is the right pick anywhere
// you would otherwise reach for cookies() in App Router code.
//
// Auth correctness note: every gate path in this file calls
// supabase.auth.getUser() rather than getSession(). getSession reads
// the cookie payload as-is; getUser revalidates with the Supabase
// auth server so a forged or stale cookie can't pass.

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import type { SupabaseClient, User } from "@supabase/supabase-js";

import { env } from "./env";

export class AuthError extends Error {
  readonly status: number;
  constructor(message: string = "unauthorized", status: number = 401) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

export async function createSupabaseServerClient(): Promise<SupabaseClient> {
  const cookieStore = await cookies();
  return createServerClient(
    env.SUPABASE_URL,
    env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          // Setting cookies from a Server Component throws; the
          // middleware refreshes the session cookie on every
          // request, so this no-op is safe in that context.
          try {
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options);
            }
          } catch {
            // intentional — see comment above
          }
        },
      },
    },
  );
}

export async function getServerSession(): Promise<User | null> {
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) {
    return null;
  }
  return data.user;
}

export async function requireSession(): Promise<User> {
  const user = await getServerSession();
  if (!user) {
    throw new AuthError();
  }
  return user;
}

export async function signOut(redirectTo: string = "/"): Promise<NextResponse> {
  const supabase = await createSupabaseServerClient();
  await supabase.auth.signOut();
  const target = new URL(redirectTo, env.NEXT_PUBLIC_SITE_URL);
  return NextResponse.redirect(target);
}
