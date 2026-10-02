// web/components/RecommendIntro.tsx
//
// Before the first recommendation: how one is made, in three steps, with the
// catalog's live counts, so the page explains itself instead of showing an
// empty box.
import Link from "next/link";

export function RecommendIntro({ modelCount, measuredCount }: { modelCount: number; measuredCount: number }) {
  const steps = [
    {
      title: "The engine reads your task",
      body: "It names what the task needs most: coding, planning, agentic work, multimodal input, long context, knowledge or speed.",
    },
    {
      title: "It weighs the whole catalog",
      body: `${modelCount} models, each rated S→D in every category, ${measuredCount} of them measured by Artificial Analysis, with their prices and the subscriptions you hold.`,
    },
    {
      title: "You get three picks",
      body: "Cost, Balanced and Quality: each with the platform to run it on, its settings, and what it costs you.",
    },
  ];
  return (
    <section
      aria-labelledby="how-it-works"
      className="rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 px-5 py-5 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="recommend-intro"
    >
      <h2 id="how-it-works" className="text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        How a recommendation is made
      </h2>
      <ol className="mt-4 grid gap-5 sm:grid-cols-3">
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-brand-accent/10 text-xs font-bold text-brand-accent">
              {i + 1}
            </span>
            <span>
              <span className="block text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">{s.title}</span>
              <span className="mt-1 block text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">{s.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-5 text-sm text-brand-slate-600 dark:text-brand-slate-300">
        Every model, with its ratings, benchmarks and prices, is on{" "}
        <Link href="/models" className="font-medium text-brand-accent hover:underline">
          the catalog
        </Link>
        .
      </p>
    </section>
  );
}
