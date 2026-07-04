// web/components/RatingKey.tsx
import { RATING_SCALE } from "@/lib/glossary";

// The compact rating-scale block shown under the matrix in the left column: how
// picks are rated (S→D), with a one-line footer pointing at the full benchmark
// list. The benchmark CHIPS themselves live in the collapsed "Benchmarks &
// ratings" drawer below the results card (BenchmarksDrawer) — keeping them out
// of the left column is what lets the whole result fit one viewport, matching
// the mock's no-scroll layout. In the empty state the fuller RecommendReference
// card is shown instead (see RecommendWorkspace).
export function RatingKey() {
  return (
    <div className="mt-auto rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 px-4 py-3">
      <span className="text-[10.5px] font-bold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
        How picks are rated
      </span>
      <div className="mt-2 flex flex-col gap-1.5">
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
      <span className="mt-2.5 block text-[11px] text-brand-slate-400 dark:text-brand-slate-500">
        Grounded in public benchmarks — full list below.
      </span>
    </div>
  );
}
