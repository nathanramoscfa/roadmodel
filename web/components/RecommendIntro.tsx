// web/components/RecommendIntro.tsx
//
// Before the first recommendation: how one is made, in three steps with the
// catalog's live counts, then the frontier the picks will be read from, drawn
// over the models this viewer can run. The page explains itself and shows its
// working instead of an empty box.
"use client";

import Link from "next/link";
import { useMemo } from "react";

import { frontierOf } from "@/lib/frontier-points";
import type { PicksData } from "@/lib/recommend-picks";
import { PicksChart } from "./PicksChart";

const NO_PICKS: never[] = [];

export function RecommendIntro({
  modelCount,
  measuredCount,
  picks,
}: {
  modelCount: number;
  measuredCount: number;
  picks: PicksData;
}) {
  const yours = picks.pool !== null;
  // No task yet: the frontier over every effort Artificial Analysis measured
  // each of the viewer's models at.
  const frontier = useMemo(() => frontierOf(picks, null), [picks]);
  const steps = [
    {
      title: "The engine reads your task",
      body: "It names what the task needs most (coding, planning, agentic work, multimodal input, long context, knowledge or speed) and how hard it is.",
    },
    {
      title: yours ? "It reads your frontier" : "It reads the frontier",
      body: `${modelCount} models, ${measuredCount} of them measured by Artificial Analysis, each at every effort level and priced at the tokens it writes there. ${
        yours ? "The ones your plans and API keys reach" : "Together they"
      } form the cost/quality frontier below.`,
    },
    {
      title: "You get three picks, ranked three deep",
      body: "Cost, Balanced and Quality, each with a runner-up and a backup from other makers: the platform to run it on, the level to set, and what it costs you.",
    },
  ];
  return (
    <div className="space-y-6">
      <section
        aria-labelledby="how-it-works"
        className="rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
        data-testid="recommend-intro"
      >
        <h2
          id="how-it-works"
          className="px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100"
        >
          How a recommendation is made
        </h2>
        <div className="border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
          <ol className="grid gap-6 sm:grid-cols-3">
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
            <Link href="/" className="font-medium text-brand-accent hover:underline">
              the catalog
            </Link>
            .
          </p>
        </div>
      </section>

      <PicksChart frontier={frontier} yours={yours} picks={NO_PICKS} />
    </div>
  );
}
