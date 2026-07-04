// web/components/BenchmarksDrawer.tsx
import Link from "next/link";

import { BenchmarkReference } from "./BenchmarkReference";

// Collapsed "Benchmarks & ratings" drawer shown BELOW the results card (mirrors
// the mock's `<details class="ref">`). Moving the benchmark chips out of the
// always-visible left column keeps the result compact enough to fit one
// viewport; a reader who wants the sources expands this. Closed by default.
export function BenchmarksDrawer() {
  return (
    <details className="group rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 px-4 shadow-sm">
      <summary className="flex cursor-pointer list-none items-center justify-between py-3 text-sm font-semibold text-brand-slate-700 dark:text-brand-slate-200">
        <span>Benchmarks &amp; ratings — how these picks are graded</span>
        <svg
          className="h-4 w-4 transition-transform group-open:rotate-180"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </summary>
      <div className="border-t border-brand-slate-100 dark:border-brand-slate-800 py-4">
        <p className="mb-3 text-xs text-brand-slate-500 dark:text-brand-slate-400">
          Every rating links to its source. The rationale cites these public
          benchmarks:
        </p>
        <BenchmarkReference compact />
        <Link
          href="/docs"
          className="mt-4 inline-block text-xs font-medium text-brand-accent underline-offset-2 hover:underline"
        >
          Full reference →
        </Link>
      </div>
    </details>
  );
}
