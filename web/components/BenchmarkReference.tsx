// web/components/BenchmarkReference.tsx
import { BENCHMARKS } from "@/lib/glossary";

interface BenchmarkReferenceProps {
  id?: string;
  // compact: name-only chips (the /recommend panel). Default: full list with
  // each benchmark's one-line description (the /docs page).
  compact?: boolean;
}

export function BenchmarkReference({ id, compact = false }: BenchmarkReferenceProps) {
  if (compact) {
    return (
      <ul className="flex flex-wrap gap-2">
        {BENCHMARKS.map((entry) => (
          <li key={entry.term}>
            <a
              href={entry.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block rounded-md border border-brand-slate-200 dark:border-brand-slate-700 px-2 py-1 text-xs font-medium text-brand-slate-700 dark:text-brand-slate-200 hover:border-brand-accent hover:text-brand-accent"
            >
              {entry.term}
            </a>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section id={id} aria-labelledby="benchmarks-heading" className="scroll-mt-20">
      <h2
        id="benchmarks-heading"
        className="text-xl font-semibold tracking-tight text-brand-slate-900 dark:text-brand-slate-50"
      >
        Benchmarks
      </h2>
      <p className="mt-2 text-brand-slate-600 dark:text-brand-slate-300">
        The recommender grounds its rationale in these public leaderboards; the
        ratings above synthesize them. Each links to its source.
      </p>
      <ul className="mt-4 space-y-3 text-sm">
        {BENCHMARKS.map((entry) => (
          <li key={entry.term}>
            <a
              href={entry.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-brand-accent underline-offset-2 hover:underline"
            >
              {entry.term}
            </a>
            <span className="text-brand-slate-600 dark:text-brand-slate-300">
              {" "}
              &mdash; {entry.definition}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
