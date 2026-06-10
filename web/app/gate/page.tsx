// web/app/gate/page.tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "roadmodel — preview access",
  description: "roadmodel.ai is in pre-launch preview. Enter the access password to continue.",
  robots: { index: false, follow: false },
};

interface GatePageProps {
  searchParams: Promise<{
    next?: string;
    error?: string;
    locked?: string;
    remaining?: string;
    retry?: string;
  }>;
}

export default async function GatePage({ searchParams }: GatePageProps) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : "/";
  const error = params.error === "1";
  const locked = params.locked === "1";
  const retryMinutes = Math.max(1, Math.ceil(Number(params.retry ?? "300") / 60));
  const remaining = Number(params.remaining ?? "");

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-slate-50 dark:bg-brand-slate-900 px-6 py-16">
      <div className="w-full max-w-md rounded-2xl border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50">
          Preview access
        </h1>
        <p className="mt-3 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          This site is in pre-launch preview while we finish bug fixes and
          design polish. Enter the access password to continue.
        </p>

        <form
          action="/api/gate"
          method="post"
          className="mt-6 flex flex-col gap-3"
        >
          <input type="hidden" name="next" value={next} />
          <label
            htmlFor="password"
            className="text-sm font-medium text-brand-slate-800 dark:text-brand-slate-100"
          >
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            autoFocus
            required
            disabled={locked}
            className={
              "rounded-lg border border-brand-slate-300 dark:border-brand-slate-700 px-3 py-2 text-sm " +
              "bg-white dark:bg-brand-slate-800 text-brand-slate-900 dark:text-brand-slate-50 " +
              "placeholder:text-brand-slate-400 " +
              "shadow-sm focus:border-brand-accent focus:outline-none " +
              "focus:ring-2 focus:ring-brand-accent/30 " +
              "disabled:cursor-not-allowed disabled:opacity-60"
            }
          />
          {locked ? (
            <p className="text-sm text-red-600" role="alert">
              Too many incorrect attempts. Access is locked for about{" "}
              {retryMinutes} minute{retryMinutes === 1 ? "" : "s"}. Try again
              later.
            </p>
          ) : error ? (
            <p className="text-sm text-red-600" role="alert">
              Incorrect password. Try again.
              {Number.isFinite(remaining) && remaining > 0
                ? ` ${remaining} attempt${remaining === 1 ? "" : "s"} left before a temporary lockout.`
                : ""}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={locked}
            className={
              "mt-2 rounded-lg bg-brand-accent px-4 py-2 text-sm font-semibold " +
              "text-white shadow-sm hover:bg-brand-accent/90 focus:outline-none " +
              "focus:ring-2 focus:ring-brand-accent/40 " +
              "disabled:cursor-not-allowed disabled:opacity-60"
            }
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
