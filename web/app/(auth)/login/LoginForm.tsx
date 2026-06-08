// web/app/(auth)/login/LoginForm.tsx
"use client";

import { useMemo, useState } from "react";
import { createBrowserClient } from "@supabase/ssr";

interface LoginFormProps {
  supabaseUrl: string;
  supabaseAnonKey: string;
  next: string;
  initialError: string | null;
}

type Status =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent"; email: string }
  | { kind: "error"; message: string };

export function LoginForm({
  supabaseUrl,
  supabaseAnonKey,
  next,
  initialError,
}: LoginFormProps) {
  const supabase = useMemo(
    () => createBrowserClient(supabaseUrl, supabaseAnonKey),
    [supabaseUrl, supabaseAnonKey],
  );
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>(
    initialError ? { kind: "error", message: initialError } : { kind: "idle" },
  );

  function callbackUrl(): string {
    const origin =
      typeof window !== "undefined" ? window.location.origin : "";
    return `${origin}/callback?next=${encodeURIComponent(next)}`;
  }

  async function sendMagicLink(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus({ kind: "sending" });
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: callbackUrl() },
    });
    if (error) {
      setStatus({ kind: "error", message: error.message });
      return;
    }
    setStatus({ kind: "sent", email });
  }

  async function signInWithGitHub() {
    setStatus({ kind: "sending" });
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "github",
      options: { redirectTo: callbackUrl() },
    });
    if (error) {
      setStatus({ kind: "error", message: error.message });
    }
  }

  const sending = status.kind === "sending";

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-slate-50 dark:bg-brand-slate-900 px-6 py-16">
      <div className="w-full max-w-md rounded-2xl border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50">
          Sign in
        </h1>
        <p className="mt-3 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          Use a magic link or your GitHub account.
        </p>

        <form onSubmit={sendMagicLink} className="mt-6 flex flex-col gap-3">
          <label
            htmlFor="email"
            className="text-sm font-medium text-brand-slate-800 dark:text-brand-slate-100"
          >
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={
              "rounded-lg border border-brand-slate-300 dark:border-brand-slate-700 px-3 py-2 text-sm " +
              "bg-white dark:bg-brand-slate-800 text-brand-slate-900 dark:text-brand-slate-50 " +
              "placeholder:text-brand-slate-400 " +
              "shadow-sm focus:border-brand-accent focus:outline-none " +
              "focus:ring-2 focus:ring-brand-accent/30"
            }
          />
          <button
            type="submit"
            disabled={sending}
            className={
              "mt-2 rounded-lg bg-brand-accent px-4 py-2 text-sm font-semibold " +
              "text-white shadow-sm hover:bg-brand-accent/90 focus:outline-none " +
              "focus:ring-2 focus:ring-brand-accent/40 disabled:opacity-60"
            }
          >
            {sending ? "Sending…" : "Send magic link"}
          </button>
        </form>

        <div className="my-6 flex items-center gap-3">
          <div className="h-px flex-1 bg-brand-slate-200 dark:bg-brand-slate-700" />
          <span className="text-xs uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            or
          </span>
          <div className="h-px flex-1 bg-brand-slate-200 dark:bg-brand-slate-700" />
        </div>

        <button
          type="button"
          onClick={signInWithGitHub}
          disabled={sending}
          className={
            "w-full rounded-lg border border-brand-slate-300 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 px-4 py-2 " +
            "text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100 shadow-sm " +
            "hover:bg-brand-slate-50 dark:bg-brand-slate-900 focus:outline-none focus:ring-2 " +
            "focus:ring-brand-accent/40 disabled:opacity-60"
          }
        >
          Continue with GitHub
        </button>

        {status.kind === "sent" ? (
          <p className="mt-6 text-sm text-brand-slate-700 dark:text-brand-slate-200">
            Check your email at <strong>{status.email}</strong> for the
            sign-in link.
          </p>
        ) : null}
        {status.kind === "error" ? (
          <p className="mt-6 text-sm text-red-600">{status.message}</p>
        ) : null}
      </div>
    </div>
  );
}
