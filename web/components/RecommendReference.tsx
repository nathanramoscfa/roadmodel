// web/components/RecommendReference.tsx
import Link from "next/link";

import { BenchmarkReference } from "./BenchmarkReference";
import { RatingScale } from "./RatingScale";

// A static reference shown under the prompt form on /recommend (it fills the
// left column), so the rating scale + benchmarks a recommendation's rationale
// cites are right there next to it. Full explanations live at /docs; this reuses
// the same glossary-driven components in their compact form.
export function RecommendReference() {
  return (
    <aside
      aria-labelledby="recommend-reference-heading"
      className="rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-5 shadow-sm"
    >
      <h2
        id="recommend-reference-heading"
        className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50"
      >
        Benchmarks &amp; ratings
      </h2>
      <p className="mt-1 text-xs text-brand-slate-500 dark:text-brand-slate-400">
        Each recommendation rates models <strong>S&rarr;D</strong> per category,
        grounded in public benchmarks. The rationale links every term to its source.
      </p>

      <div className="mt-4">
        <RatingScale compact />
      </div>

      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
          Benchmarks
        </h3>
        <div className="mt-2">
          <BenchmarkReference compact />
        </div>
      </div>

      <Link
        href="/docs"
        className="mt-4 inline-block text-sm font-medium text-brand-accent underline-offset-2 hover:underline"
      >
        Full reference &rarr;
      </Link>
    </aside>
  );
}
