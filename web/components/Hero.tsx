// web/components/Hero.tsx
import Link from "next/link";
import { ArrowRight, Lock } from "lucide-react";

import type { CatalogStats } from "@/lib/catalog-models";

// The home hero. No task input here on purpose — describing a task and getting
// a recommendation lives on /recommend; the home page just frames what
// roadmodel is and points to its two surfaces (recommend + catalog).
export function Hero({ stats }: { stats: CatalogStats }) {
  const headlineStats = [
    { value: stats.modelCount, label: "models" },
    { value: stats.providerCount, label: "providers" },
    { value: stats.categoryCount, label: "categories" },
    { value: stats.benchmarkCount, label: "benchmarks" },
  ];

  return (
    <section className="mx-auto max-w-4xl px-6 py-20 text-center sm:py-28">
      <div className="flex items-center justify-center gap-3">
        <span className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-brand-slate-300 px-2.5 py-0.5 text-xs font-medium text-brand-slate-600 dark:border-brand-slate-600 dark:text-brand-slate-300">
          <Lock className="h-3 w-3" aria-hidden="true" />
          Private preview
        </span>
      </div>

      <h1 className="mt-5 text-4xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-5xl">
        Pick the right model for the right job
      </h1>
      <p className="mx-auto mt-6 max-w-2xl text-lg text-brand-slate-600 dark:text-brand-slate-300">
        roadmodel recommends which model, platform, and settings to run for a
        given task — then shows its work in a daily-refreshed catalog of{" "}
        {stats.modelCount} models across {stats.providerCount} providers, each
        rated <span className="font-semibold text-brand-slate-800 dark:text-brand-slate-100">S&nbsp;&rarr;&nbsp;D</span>{" "}
        in {stats.categoryCount} categories against public benchmarks.
      </p>

      <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          href="/recommend"
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-brand-accent px-6 py-3 text-base font-semibold text-white shadow-sm transition hover:bg-brand-accent-hover sm:w-auto"
        >
          Get a recommendation
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
        <Link
          href="/models"
          className="inline-flex w-full items-center justify-center rounded-lg border border-brand-slate-300 px-6 py-3 text-base font-semibold text-brand-slate-800 transition hover:border-brand-slate-400 hover:bg-white dark:border-brand-slate-600 dark:text-brand-slate-100 dark:hover:border-brand-slate-500 dark:hover:bg-brand-slate-800 sm:w-auto"
        >
          Browse the catalog
        </Link>
      </div>

      <dl className="mx-auto mt-12 flex max-w-xl flex-wrap items-center justify-center gap-x-8 gap-y-4">
        {headlineStats.map((stat) => (
          <div key={stat.label} className="flex flex-col items-center">
            <dt className="sr-only">{stat.label}</dt>
            <dd className="text-2xl font-bold tabular-nums text-brand-slate-900 dark:text-brand-slate-50">
              {stat.value}
            </dd>
            <span
              aria-hidden="true"
              className="mt-0.5 text-xs font-medium uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400"
            >
              {stat.label}
            </span>
          </div>
        ))}
        <div className="flex flex-col items-center">
          <dd className="text-2xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
            ↻
          </dd>
          <span className="mt-0.5 text-xs font-medium uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            daily refresh
          </span>
        </div>
      </dl>
    </section>
  );
}
