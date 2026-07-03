// web/components/RatingKey.tsx
import { RATING_SCALE } from "@/lib/glossary";

// Compact "how picks are rated" legend (S→D), shown under the matrix so the
// grades a rationale cites are explained inline. `mt-auto` pins it to the bottom
// of the left column so it fills the space beside the taller detail panel (the
// full benchmark list lives in the reference below the results).
export function RatingKey() {
  return (
    <div className="rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 p-3.5">
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
      <span className="mt-2.5 block text-[11px] text-brand-slate-400 dark:text-brand-slate-500">
        Grounded in public benchmarks — full list below.
      </span>
    </div>
  );
}
