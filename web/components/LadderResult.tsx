// web/components/LadderResult.tsx
//
// An answer on /recommend, whichever lane wrote it (lib/ladder-view.ts): the
// three picks ranked three deep, the selected pick's reasoning and cost, and
// the chart of where the picks sit on the viewer's cost/quality frontier. The
// lane supplies what sits above them (its task and how it was answered) and
// anything it adds below.
"use client";

import Link from "next/link";
import { AlertTriangle, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { LadderTask } from "@/lib/api";
import { CATEGORY_DEFS, type Category } from "@/lib/catalog-fields";
import { fundedZero, type LadderView } from "@/lib/ladder-view";
import { categoryLabel, complexityLabel } from "@/lib/ladder-task";
import type { BudgetPriority } from "@/lib/profile";
import type { PicksData } from "@/lib/recommend-picks";
import { BenchmarkReference } from "./BenchmarkReference";
import { PickDetail } from "./PickDetail";
import { PicksChart } from "./PicksChart";
import { LadderNote, PicksLadder } from "./PicksLadder";
import { RatingScale } from "./RatingScale";
import { FrontierScope, YOUR_MODELS } from "./ScoreCards";

const CHIP =
  "inline-flex items-center rounded-full border border-brand-slate-200 bg-brand-slate-50 px-2.5 py-0.5 text-xs font-medium text-brand-slate-700 dark:border-brand-slate-600 dark:bg-brand-slate-900 dark:text-brand-slate-200";

// What the task was read as: the classification the picks were ranked for.
export function TaskChips({ task }: { task: LadderTask }) {
  const category = CATEGORY_DEFS[task.category as Category];
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5" data-testid="ladder-task">
      <span className={CHIP} title={category?.definition} data-testid="ladder-task-category">
        {categoryLabel(task.category)}
      </span>
      <span className={CHIP} data-testid="ladder-task-complexity">
        {complexityLabel(task.complexity)} complexity
      </span>
      {task.novel && task.complexity === "high" && (
        <span
          className={CHIP}
          title="Research-grade work with no established method to follow"
          data-testid="ladder-task-novel"
        >
          A new kind of problem
        </span>
      )}
    </span>
  );
}

export function LadderResult({
  view,
  picks,
  header,
  footer = null,
  canPersist,
  testId,
}: {
  view: LadderView;
  picks: PicksData;
  // The lane's own bar above the picks: the task and how it was answered.
  header: ReactNode;
  footer?: ReactNode;
  // A signed-in viewer can keep the selected tier as their default.
  canPersist: boolean;
  testId: string;
}) {
  const [primary, setPrimary] = useState<BudgetPriority>(view.primary);
  const [selected, setSelected] = useState<BudgetPriority>(view.primary);
  const [persisting, setPersisting] = useState(false);

  useEffect(() => {
    setPrimary(view.primary);
    setSelected(view.primary);
  }, [view]);

  function setDefault(priority: BudgetPriority) {
    setPrimary(priority);
    if (!canPersist) return;
    setPersisting(true);
    void fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ budget_priority: priority }),
    })
      .then((response) => response.arrayBuffer())
      .catch(() => {})
      .finally(() => setPersisting(false));
  }

  const column = view.columns.find((c) => c.priority === selected) ?? view.columns[0];
  const insight = fundedZero(view);
  const chartPicks = useMemo(
    () => view.columns.map((c) => ({ priority: c.priority, option: c.pick })),
    [view.columns],
  );
  const n = view.columns.length;

  return (
    // With saved Settings, every frontier card speaks of the viewer's models.
    <FrontierScope.Provider value={picks.pool ? YOUR_MODELS : null}>
      <div className="space-y-6" data-testid={testId}>
        {header}

        <section
          aria-label={n === 3 ? "The three picks" : "The picks"}
          className="rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-5 py-3">
            <h2 className="text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
              Your {n === 3 ? "three " : ""}picks{view.ranked ? ", each with a runner-up and a backup" : ""}
            </h2>
            <span className="hidden text-xs text-brand-slate-500 md:inline dark:text-brand-slate-400">
              Select a pick for its reasoning and cost
            </span>
          </div>
          <div className="space-y-4 border-t border-brand-slate-200 px-4 py-4 dark:border-brand-slate-700 sm:px-5 sm:py-5">
            {insight && (
              <div
                className="flex items-center gap-2.5 rounded-lg border border-brand-accent/30 bg-brand-accent/5 px-3 py-2 text-[13px] text-brand-slate-700 dark:bg-brand-accent/10 dark:text-brand-slate-200"
                data-testid="funded-insight"
              >
                <Sparkles className="h-4 w-4 flex-none text-brand-accent" aria-hidden />
                <span>
                  All {n === 3 ? "three " : ""}picks run at{" "}
                  <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">$0 to you</b>
                  {insight.source ? ` on ${insight.source}` : ""}: the trade-off is{" "}
                  <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">capability and effort</b>,
                  not price.
                </span>
              </div>
            )}
            <PicksLadder view={view} data={picks} selected={selected} primary={primary} onSelect={setSelected} />
            {view.backupWarning && (
              <p
                className="flex items-start gap-2 rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
                data-testid="backup-warning"
              >
                <AlertTriangle className="mt-px h-3.5 w-3.5 flex-none" aria-hidden />
                {view.backupWarning}
              </p>
            )}
            <LadderNote view={view} />
          </div>
        </section>

        {column && (
          <PickDetail
            view={view}
            column={column}
            selected={selected}
            onSelect={setSelected}
            canPersist={canPersist}
            persisting={persisting}
            isDefault={column.priority === primary}
            onSetDefault={setDefault}
          />
        )}

        <PicksChart
          frontier={view.frontier}
          yours={picks.pool !== null}
          picks={chartPicks}
          selected={selected}
          onSelect={setSelected}
        />

        <details className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
            How to read these picks
            <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">show</span>
            <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">hide</span>
          </summary>
          <div className="grid gap-6 border-t border-brand-slate-200 px-5 py-5 text-sm leading-6 text-brand-slate-600 dark:border-brand-slate-700 dark:text-brand-slate-300 md:grid-cols-2">
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                The three columns
              </h3>
              <p>
                <b className="text-brand-slate-800 dark:text-brand-slate-100">Quality</b> is the strongest model for
                the task. <b className="text-brand-slate-800 dark:text-brand-slate-100">Cost</b> is the cheapest
                model that still does the job, and{" "}
                <b className="text-brand-slate-800 dark:text-brand-slate-100">Balanced</b> is the best value between
                them. Each is read from the cost/quality frontier of the models you can run.
              </p>
              <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                The three ranks
              </h3>
              <p>
                The <b className="text-brand-slate-800 dark:text-brand-slate-100">Pick</b> is the column&rsquo;s
                first choice. The <b className="text-brand-slate-800 dark:text-brand-slate-100">Runner-up</b> is the
                column&rsquo;s choice from another maker, and the{" "}
                <b className="text-brand-slate-800 dark:text-brand-slate-100">Backup</b> its choice from a third: a
                plan&rsquo;s usage limit or an outage belongs to one maker, so each rank runs on a different one.
                Every option names the platform to run it on and the level to set there.
              </p>
            </div>
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                The figures
              </h3>
              <p>
                <b className="text-brand-slate-800 dark:text-brand-slate-100">AA Index</b> is the Artificial
                Analysis Intelligence Index at the level shown.{" "}
                <b className="text-brand-slate-800 dark:text-brand-slate-100">Price</b> is the list price per 1M
                tokens at that level&rsquo;s token use.{" "}
                <b className="text-brand-slate-800 dark:text-brand-slate-100">Score</b> is the option&rsquo;s
                0&ndash;100% price-adjusted market percentile against today&rsquo;s price line (50% = on the line). Hover a figure for how it is read.
                Leave Thinking on wherever a platform has that switch: every AA Index and price here is read with
                it on.
              </p>
              <p>
                The letters are the catalog&rsquo;s S&rarr;D ratings in coding, planning, agentic, multimodal,
                long-context, knowledge and speed. A filled letter is measured from an Artificial Analysis
                benchmark; a dashed one is estimated. The{" "}
                <Link href="/#how-to-read" className="font-medium text-brand-accent hover:underline">
                  catalog key
                </Link>{" "}
                has the rules.
              </p>
            </div>
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                Rating scale
              </h3>
              <RatingScale compact />
            </div>
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                The benchmarks behind the ratings
              </h3>
              <BenchmarkReference compact />
              <Link href="/docs" className="mt-3 inline-block text-xs font-medium text-brand-accent hover:underline">
                Full reference &rarr;
              </Link>
            </div>
          </div>
        </details>

        {footer}
      </div>
    </FrontierScope.Provider>
  );
}
