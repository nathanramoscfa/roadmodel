// web/components/RatingScale.tsx
import {
  DERIVATION_BANDS,
  DERIVED_CATEGORIES,
  ESTIMATE_CEILING,
  evidenceLabel,
  RANK_DERIVATION,
  rankRuleText,
} from "@/lib/benchmark-grid";
import { CATEGORY_ORDER } from "@/lib/catalog-fields";
import { RATING_SCALE } from "@/lib/glossary";

// The derivation in words, from the constants the letters are derived with,
// so this page cannot state a rule the data no longer follows.
const DERIVED = CATEGORY_ORDER.filter((c) => DERIVED_CATEGORIES.has(c));
const EVIDENCE = DERIVED.map((c) => evidenceLabel(c)).join(", ");
const GAP = DERIVED.filter((c) => !RANK_DERIVATION[c]).join(", ");
const BANDS = DERIVATION_BANDS.map((b) => `${b.letter} within ${b.max}`).join(", ");
const RANKED = DERIVED.filter((c) => RANK_DERIVATION[c])
  .map((c) => `${c} is the model's rank with the letter spread held fixed: ${rankRuleText(RANK_DERIVATION[c]!)}`)
  .join("; ");

// The S→D per-category rating scale, rendered from the glossary's RATING_SCALE
// (the same source as the rationale's tier popovers). `id` lets the rationale's
// tier links anchor here (the glossary points "S-tier" etc. at /docs#ratings).
// `compact` is the dense S–D list for the /recommend reference panel.
export function RatingScale({ id, compact = false }: { id?: string; compact?: boolean }) {
  if (compact) {
    return (
      <dl className="space-y-1.5">
        {RATING_SCALE.map((row) => (
          <div key={row.rating} className="flex gap-2 text-xs">
            <dt className="w-4 shrink-0 font-bold text-brand-accent">{row.rating}</dt>
            <dd className="text-brand-slate-600 dark:text-brand-slate-300">{row.meaning}</dd>
          </div>
        ))}
      </dl>
    );
  }
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
        <strong>S&nbsp;&rarr;&nbsp;D</strong> scale &mdash; <strong>S</strong> is the
        top &ldquo;tier-list&rdquo; rank, a step above A (the gaming convention for
        the genuine best), then A, B, C, D. A rating is a <em>class</em>, not a
        ranking within it: several frontier models share S in most categories. Four
        of the seven letters &mdash; {DERIVED.join(", ")} &mdash; are <em>derived</em>{" "}
        from a single Artificial Analysis benchmark each ({EVIDENCE}): {GAP} as the
        model&rsquo;s gap to the category leader ({BANDS} points, else D); {RANKED}.
        They refresh with the data and cannot be hand-edited. Every
        other letter is an estimate: planning, multimodal, and speed, and a derived
        category for a model outside its benchmark&rsquo;s measured set, where an
        estimate stops at {ESTIMATE_CEILING} because S takes a measurement. The daily
        catalog automation sets estimates from cited evidence one step at a time, and
        a new model starts from its predecessor&rsquo;s letters. The selection algorithm sets a minimum required rating from the
        prompt&rsquo;s complexity, then picks the highest-rated available model that
        clears it &mdash; ties inside a class resolve on the benchmark evidence, which
        the{" "}
        <a href="/models" className="text-brand-accent hover:underline">
          model catalog
        </a>{" "}
        shows as the Artificial Analysis Intelligence Index and the full benchmark
        grid.
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
