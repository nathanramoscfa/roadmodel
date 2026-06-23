// web/components/RatingSystem.tsx
//
// "How it rates models" — the methodology behind every recommendation, for an
// audience that wants to see the data, not take it on faith. Reuses the exact
// rating scale, category defs, benchmark list, and colors that the /models
// table and /recommend rationale use, so the home page can't drift from them.
import Link from "next/link";
import { Gauge, Layers, LineChart } from "lucide-react";

import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  RATING_COLORS,
  type Rating,
} from "@/lib/catalog-fields";
import { BENCHMARKS, RATING_SCALE } from "@/lib/glossary";
import type { CatalogStats } from "@/lib/catalog-models";

const BADGE =
  "inline-flex min-w-[1.75rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold";

const CARD =
  "rounded-xl border border-brand-slate-200 bg-white p-6 dark:border-brand-slate-700 dark:bg-brand-slate-800";

const CARD_HEADING =
  "flex items-center gap-2 text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50";

export function RatingSystem({ stats }: { stats: CatalogStats }) {
  return (
    <section className="border-t border-brand-slate-200 py-20 dark:border-brand-slate-700">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-3xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
          How it rates models
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-center text-brand-slate-600 dark:text-brand-slate-300">
          Every pick is grounded in the same rubric: seven capability
          categories, a per-category S&nbsp;&rarr;&nbsp;D scale, and public
          benchmark scores — not vibes.
        </p>

        <div className="mt-12 grid gap-6 lg:grid-cols-3">
          {/* Seven categories */}
          <div className={CARD}>
            <h3 className={CARD_HEADING}>
              <Layers className="h-4 w-4 text-brand-accent" aria-hidden="true" />
              Seven categories
            </h3>
            <div className="mt-4 flex flex-wrap gap-2">
              {CATEGORY_ORDER.map((cat) => (
                <span
                  key={cat}
                  title={CATEGORY_DEFS[cat].definition}
                  className="rounded-md border border-brand-slate-200 bg-brand-slate-50 px-2.5 py-1 text-xs font-medium text-brand-slate-700 dark:border-brand-slate-700 dark:bg-brand-slate-900 dark:text-brand-slate-200"
                >
                  {CATEGORY_DEFS[cat].label}
                </span>
              ))}
            </div>
            <p className="mt-4 text-xs text-brand-slate-500 dark:text-brand-slate-400">
              A model is scored independently per category, so a coding pick
              isn&apos;t dragged down by weak multimodal — and vice versa.
            </p>
          </div>

          {/* S → D scale */}
          <div className={CARD}>
            <h3 className={CARD_HEADING}>
              <Gauge className="h-4 w-4 text-brand-accent" aria-hidden="true" />
              S&nbsp;&rarr;&nbsp;D per category
            </h3>
            <dl className="mt-4 space-y-2">
              {RATING_SCALE.map((row) => (
                <div key={row.rating} className="flex items-start gap-2 text-sm">
                  <dt>
                    <span
                      className={`${BADGE} ${RATING_COLORS[row.rating as Rating]}`}
                    >
                      {row.rating}
                    </span>
                  </dt>
                  <dd className="text-brand-slate-600 dark:text-brand-slate-300">
                    {row.meaning}
                  </dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Benchmarks */}
          <div className={CARD}>
            <h3 className={CARD_HEADING}>
              <LineChart
                className="h-4 w-4 text-brand-accent"
                aria-hidden="true"
              />
              Grounded in public benchmarks
            </h3>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {BENCHMARKS.map((bench) => {
                const chip =
                  "rounded-md border border-brand-slate-200 bg-brand-slate-50 px-2 py-0.5 text-xs font-medium text-brand-slate-600 transition hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-700 dark:bg-brand-slate-900 dark:text-brand-slate-300";
                return bench.url ? (
                  <Link
                    key={bench.term}
                    href={bench.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={bench.definition}
                    className={chip}
                  >
                    {bench.term}
                  </Link>
                ) : (
                  <span key={bench.term} title={bench.definition} className={chip}>
                    {bench.term}
                  </span>
                );
              })}
            </div>
            <p className="mt-4 text-xs text-brand-slate-500 dark:text-brand-slate-400">
              {stats.benchmarkCount} leaderboards, each linked to its source.
            </p>
          </div>
        </div>

        {/* Providers + freshness meta */}
        <div className="mt-8 rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 px-6 py-5 dark:border-brand-slate-700 dark:bg-brand-slate-800/40">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                {stats.providerCount} providers
              </span>
              {stats.providers.map((provider) => (
                <span
                  key={provider}
                  className="rounded-full bg-brand-slate-200 px-2.5 py-0.5 text-xs font-medium text-brand-slate-700 dark:bg-brand-slate-700 dark:text-brand-slate-200"
                >
                  {provider}
                </span>
              ))}
            </div>
            <p className="shrink-0 text-xs text-brand-slate-500 dark:text-brand-slate-400">
              {stats.jurisdictionCount} jurisdictions · re-priced daily · last
              refresh {stats.generatedAt}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
