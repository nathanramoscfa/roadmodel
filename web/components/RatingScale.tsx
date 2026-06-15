// web/components/RatingScale.tsx
import { RATING_SCALE } from "@/lib/glossary";

// The S→D per-category rating scale, rendered from the glossary's RATING_SCALE
// (the same source as the rationale's tier popovers). `id` lets the rationale's
// tier links anchor here (the glossary points "S-tier" etc. at /docs#ratings).
export function RatingScale({ id }: { id?: string }) {
  return (
    <section id={id} aria-labelledby="rating-scale-heading" className="scroll-mt-20">
      <h2
        id="rating-scale-heading"
        className="text-xl font-semibold tracking-tight text-brand-slate-900 dark:text-brand-slate-50"
      >
        Rating scale
      </h2>
      <p className="mt-2 text-brand-slate-600 dark:text-brand-slate-300">
        Every model is rated in seven categories &mdash; coding, planning, agentic,
        multimodal, long-context, knowledge, and speed &mdash; on an{" "}
        <strong>S&nbsp;&rarr;&nbsp;D</strong> scale. The selection algorithm sets a
        minimum required rating from the prompt&rsquo;s complexity, then picks the
        highest-rated available model that clears it.
      </p>
      <dl className="mt-4 divide-y divide-brand-slate-200 dark:divide-brand-slate-700 rounded-lg border border-brand-slate-200 dark:border-brand-slate-700">
        {RATING_SCALE.map((row) => (
          <div key={row.rating} className="flex gap-4 px-4 py-3">
            <dt className="w-8 shrink-0 text-lg font-bold text-brand-accent">
              {row.rating}
            </dt>
            <dd className="text-sm text-brand-slate-700 dark:text-brand-slate-200">
              {row.meaning}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
