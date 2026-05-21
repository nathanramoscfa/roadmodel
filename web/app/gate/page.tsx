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
  }>;
}

export default async function GatePage({ searchParams }: GatePageProps) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : "/";
  const error = params.error === "1";

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-slate-50 px-6 py-16">
      <div className="w-full max-w-md rounded-2xl border border-brand-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-brand-slate-900">
          Preview access
        </h1>
        <p className="mt-3 text-sm text-brand-slate-600">
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
            className="text-sm font-medium text-brand-slate-800"
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
            className={
              "rounded-lg border border-brand-slate-300 px-3 py-2 text-sm " +
              "shadow-sm focus:border-brand-accent focus:outline-none " +
              "focus:ring-2 focus:ring-brand-accent/30"
            }
          />
          {error ? (
            <p className="text-sm text-red-600">
              Incorrect password. Try again.
            </p>
          ) : null}
          <button
            type="submit"
            className={
              "mt-2 rounded-lg bg-brand-accent px-4 py-2 text-sm font-semibold " +
              "text-white shadow-sm hover:bg-brand-accent/90 focus:outline-none " +
              "focus:ring-2 focus:ring-brand-accent/40"
            }
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
