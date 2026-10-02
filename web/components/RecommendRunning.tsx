// web/components/RecommendRunning.tsx
//
// While the engine works: which engine, how long it has run, and how long it
// usually takes (its median on the engine eval), over a skeleton of the
// picks it will fill. Elapsed time is real; nothing pretends to know which
// step the engine is on.
"use client";

import { useEffect, useState } from "react";

import { seconds } from "@/lib/engine-format";

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
      className="rounded-xl border border-brand-slate-200 bg-white p-4 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
      role="status"
      aria-live="polite"
      data-testid="recommend-running"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="flex items-center gap-2.5 text-sm text-brand-slate-700 dark:text-brand-slate-200">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-accent opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-accent" />
          </span>
          <span>
            <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">{engineName}</b> is weighing
            the catalog for your task
          </span>
        </p>
        <p className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
          {seconds(elapsed)}
          {typicalS !== null ? ` · usually ~${seconds(typicalS)}` : ""}
        </p>
      </div>
      {slow && (
        <p className="mt-2 text-xs text-brand-slate-500 dark:text-brand-slate-400">
          Taking longer than usual. If {engineName} does not answer, another engine takes over and the result
          says so.
        </p>
      )}
      <div className="mt-4 grid grid-cols-3 gap-3" aria-hidden>
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <div className="h-3 w-16 animate-pulse rounded bg-brand-slate-200 dark:bg-brand-slate-700" />
            <div className="h-5 w-3/4 animate-pulse rounded bg-brand-slate-200 dark:bg-brand-slate-700" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-brand-slate-100 dark:bg-brand-slate-700/60" />
            <div className="h-px bg-brand-slate-100 dark:bg-brand-slate-700/60" />
            <div className="h-3 w-full animate-pulse rounded bg-brand-slate-100 dark:bg-brand-slate-700/60" />
            <div className="h-3 w-5/6 animate-pulse rounded bg-brand-slate-100 dark:bg-brand-slate-700/60" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-brand-slate-100 dark:bg-brand-slate-700/60" />
          </div>
        ))}
      </div>
    </div>
  );
}
