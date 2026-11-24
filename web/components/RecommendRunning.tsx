// web/components/RecommendRunning.tsx
//
// While the engine works: which engine, how long it has run, and how long it
// usually takes (its median on the engine eval), over a skeleton of the three
// pick cards it will fill. Elapsed time is real; nothing pretends to know
// which step the engine is on.
"use client";

import { useEffect, useState } from "react";

import { seconds } from "@/lib/engine-format";
import { PRIORITY_LABEL, PRIORITY_ORDER } from "@/lib/ladder-view";

const BAR = "animate-pulse rounded bg-brand-slate-200 dark:bg-brand-slate-700";
const BAR_FAINT = "animate-pulse rounded bg-brand-slate-100 dark:bg-brand-slate-700/60";

export function RecommendRunning({
  engineName,
  typicalS,
  startedAt,
}: {
  engineName: string;
  typicalS: number | null;
  startedAt: number;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.max(0, (now - startedAt) / 1000);
  const slow = typicalS !== null && elapsed > typicalS * 2 + 5;

  return (
    <div
      className="rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      role="status"
      aria-live="polite"
      data-testid="recommend-running"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 py-3">
        <p className="flex items-center gap-2.5 text-sm text-brand-slate-700 dark:text-brand-slate-200">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-accent opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-accent" />
          </span>
          <span>
            <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">{engineName}</b> is reading
            your task and ranking the models you can run
          </span>
        </p>
        <p className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
          {seconds(elapsed)}
          {typicalS !== null ? ` · usually ~${seconds(typicalS)}` : ""}
        </p>
      </div>
      <div className="border-t border-brand-slate-200 px-4 py-4 dark:border-brand-slate-700 sm:px-5 sm:py-5">
        {slow && (
          <p className="mb-4 text-xs text-brand-slate-500 dark:text-brand-slate-400">
            Taking longer than usual. If {engineName} does not answer, another engine takes over and the result
            says so.
          </p>
        )}
        <div className="grid gap-3 md:grid-cols-3" aria-hidden>
          {PRIORITY_ORDER.map((priority) => (
            <div
              key={priority}
              className="space-y-3 rounded-xl border border-brand-slate-200 bg-white p-4 dark:border-brand-slate-700 dark:bg-brand-slate-900"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-accent/70">
                {PRIORITY_LABEL[priority].label}
              </p>
              <div className={"h-6 w-3/4 " + BAR} />
              <div className={"h-3 w-1/2 " + BAR_FAINT} />
              <div className="space-y-2 border-t border-brand-slate-100 pt-3 dark:border-brand-slate-700/60">
                <div className={"h-3 w-full " + BAR_FAINT} />
                <div className={"h-3 w-5/6 " + BAR_FAINT} />
              </div>
              <div className="grid grid-cols-3 gap-3 border-t border-brand-slate-100 pt-3 dark:border-brand-slate-700/60">
                <div className={"h-7 " + BAR} />
                <div className={"h-7 " + BAR} />
                <div className={"h-7 " + BAR} />
              </div>
              <div className="hidden space-y-2 border-t border-brand-slate-100 pt-3 md:block dark:border-brand-slate-700/60">
                <div className={"h-3 w-2/3 " + BAR_FAINT} />
                <div className={"h-3 w-1/2 " + BAR_FAINT} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
