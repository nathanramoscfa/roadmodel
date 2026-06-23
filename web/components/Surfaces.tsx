// web/components/Surfaces.tsx
//
// The two product surfaces, side by side: the recommender (/recommend) and the
// model catalog (/models). Replaces the old generic three-step "How it works".
import Link from "next/link";
import { ArrowRight, Compass, Table } from "lucide-react";

import type { CatalogStats } from "@/lib/catalog-models";

export function Surfaces({ stats }: { stats: CatalogStats }) {
  const surfaces = [
    {
      icon: Compass,
      eyebrow: "Recommend",
      href: "/recommend",
      cta: "Get a recommendation",
      description:
        "Describe a task. roadmodel returns one grounded pick — model, platform, and settings — with a session-cost estimate and a rationale that cites benchmark scores.",
      points: [
        "Model + platform (Claude Code, Cursor, Codex, an API…)",
        "Settings block — effort and thinking dialed to the task",
        "Session-cost estimate from live pricing",
        "Rationale citing the benchmarks behind the call",
      ],
    },
    {
      icon: Table,
      eyebrow: "Model catalog",
      href: "/models",
      cta: "Browse the catalog",
      description: `The full set roadmodel recommends from — ${stats.modelCount} models across ${stats.providerCount} providers — with pricing, S→D ratings across ${stats.categoryCount} categories, and the benchmark scores behind every rating.`,
      points: [
        "Sort any column; filter by jurisdiction or cost",
        "Per-category S→D ratings, not one blurry score",
        "Every benchmark links to its source leaderboard",
        "Curated and re-priced automatically every day",
      ],
    },
  ] as const;

  return (
    <section className="border-t border-brand-slate-200 bg-white py-20 dark:border-brand-slate-700 dark:bg-brand-slate-800">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-3xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
          What roadmodel does
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-center text-brand-slate-600 dark:text-brand-slate-300">
          Two surfaces over one catalog: ask for a pick, or read the data
          behind the picks.
        </p>

        <div className="mt-12 grid gap-8 sm:grid-cols-2">
          {surfaces.map((surface) => (
            <article
              key={surface.href}
              className="flex flex-col rounded-xl border border-brand-slate-200 bg-brand-slate-50 p-8 dark:border-brand-slate-700 dark:bg-brand-slate-900"
            >
              <surface.icon
                className="h-8 w-8 text-brand-accent"
                aria-hidden="true"
              />
              <h3 className="mt-4 text-xl font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                {surface.eyebrow}
              </h3>
              <p className="mt-2 text-sm text-brand-slate-600 dark:text-brand-slate-300">
                {surface.description}
              </p>
              <ul className="mt-5 space-y-2 text-sm text-brand-slate-700 dark:text-brand-slate-200">
                {surface.points.map((point) => (
                  <li key={point} className="flex gap-2">
                    <span
                      aria-hidden="true"
                      className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-accent"
                    />
                    {point}
                  </li>
                ))}
              </ul>
              <Link
                href={surface.href}
                className="mt-6 inline-flex items-center gap-1.5 self-start text-sm font-semibold text-brand-accent transition hover:text-brand-accent-hover"
              >
                {surface.cta}
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
