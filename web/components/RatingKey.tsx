// web/components/RatingKey.tsx
import Link from "next/link";

import { BENCHMARKS, RATING_SCALE } from "@/lib/glossary";

// The reference block shown under the matrix: how picks are rated (S→D) plus the
// benchmarks a rationale cites and a link to the full docs. It fills the left
// column beneath the comparison matrix so the two sides stay roughly balanced
// beside the (taller) selected-pick detail. In the empty state the fuller
// RecommendReference card is shown instead (see RecommendWorkspace).
export function RatingKey() {
  return (
    <div className="rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 p-4">
      <span className="text-[10.5px] font-bold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
        How picks are rated
      </span>
      <div className="mt-2.5 flex flex-col gap-1.5">
        {RATING_SCALE.map((row) => (
          <div key={row.rating} className="flex items-baseline gap-2.5 text-xs">
            <span className="w-3 flex-none font-extrabold text-brand-accent">
              {row.rating}
            </span>
            <span className="text-brand-slate-500 dark:text-brand-slate-400">
              {row.meaning}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-4">
        <span className="text-[10.5px] font-bold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
          Benchmarks cited
        </span>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {BENCHMARKS.map((b) => (
            <span
              key={b.term}
              className="rounded-full border border-brand-slate-200 dark:border-brand-slate-700 bg-white px-2.5 py-0.5 text-[11px] font-medium text-brand-slate-600 dark:bg-brand-slate-800 dark:text-brand-slate-300"
            >
              {b.term}
            </span>
          ))}
        </div>
      </div>

      <Link
        href="/docs"
        className="mt-4 inline-block text-xs font-medium text-brand-accent underline-offset-2 hover:underline"
      >
        Full reference →
      </Link>
    </div>
  );
}
