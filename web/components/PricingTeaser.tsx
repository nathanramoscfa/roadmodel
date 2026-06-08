// web/components/PricingTeaser.tsx
import Link from "next/link";

const GITHUB_URL = "https://github.com/nathanramoscfa/roadmodel";

export function PricingTeaser() {
  return (
    <section className="border-t border-brand-slate-200 dark:border-brand-slate-700 py-20">
      <div className="mx-auto max-w-4xl px-6">
        <h2 className="text-center text-3xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
          Pricing
        </h2>
        <div className="mt-12 grid gap-8 sm:grid-cols-2">
          <article className="rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-8 shadow-sm">
            <h3 className="text-xl font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              Free CLI
            </h3>
            <p className="mt-3 text-sm text-brand-slate-600 dark:text-brand-slate-300">
              Apache 2.0 open-source CLI. Bring your own API key; roadmodel
              calls your Anthropic, OpenAI, or Google account on every
              recommendation.
            </p>
            <Link
              href={GITHUB_URL}
              className="mt-6 inline-flex rounded-lg border border-brand-slate-300 dark:border-brand-slate-700 px-4 py-2 text-sm font-medium text-brand-slate-800 dark:text-brand-slate-100 transition hover:border-brand-slate-400"
            >
              View repository
            </Link>
          </article>
          <article className="rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-50 dark:bg-brand-slate-900 p-8">
            <h3 className="text-xl font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              Pro Hosted (coming soon)
            </h3>
            <p className="mt-3 text-sm text-brand-slate-600 dark:text-brand-slate-300">
              Hosted recommendations at roadmodel.ai with no local setup.
              Pricing lands in Phase 5.
            </p>
            <button
              type="button"
              disabled
              className="mt-6 cursor-not-allowed rounded-lg bg-brand-slate-200 px-4 py-2 text-sm font-medium text-brand-slate-500 dark:bg-brand-slate-800 dark:text-brand-slate-400"
            >
              Coming in Phase 5
            </button>
          </article>
        </div>
      </div>
    </section>
  );
}
