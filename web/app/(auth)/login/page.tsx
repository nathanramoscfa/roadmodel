// web/app/(auth)/login/page.tsx
//
// Server entry for the login flow. Reads the Supabase project URL +
// publishable key on the server and forwards them to a client form
// component. We pass the URL via prop (rather than introducing a
// second NEXT_PUBLIC_SUPABASE_URL env var) because the URL is only
// needed in one place on the browser; this keeps the env surface
// small and avoids a second env-seed-first round-trip.

import type { Metadata } from "next";

import { env } from "@/lib/env";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = {
  title: "roadmodel — sign in",
  description: "Sign in to roadmodel with a magic link or GitHub.",
  robots: { index: false, follow: false },
};

interface LoginPageProps {
  searchParams: Promise<{ next?: string; error?: string }>;
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : "/";
  const error = typeof params.error === "string" ? params.error : null;
  return (
    <LoginForm
      supabaseUrl={env.SUPABASE_URL}
      supabaseAnonKey={env.NEXT_PUBLIC_SUPABASE_ANON_KEY}
      next={next}
      initialError={error}
    />
  );
}
