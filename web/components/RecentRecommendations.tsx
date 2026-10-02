// web/components/RecentRecommendations.tsx
//
// The last few recommendations made in this browser, so a result survives a
// reload and two engines' answers to the same task can be compared without
// paying for either again. Kept in localStorage: a per-browser convenience,
// read after the page mounts, and the page works the same without it.
"use client";

import { History } from "lucide-react";

import type { MultiRecommendResponse } from "@/lib/api";

const KEY = "roadmodel:recommend-recent";
const MAX = 8;

export interface RecentRun {
  id: string;
  at: number;
  task: string;
  data: MultiRecommendResponse;
}

export function loadRecent(): RecentRun[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (r): r is RecentRun =>
        !!r &&
        typeof r === "object" &&
        typeof (r as RecentRun).task === "string" &&
        Array.isArray((r as RecentRun).data?.recommendations),
    );
  } catch {
    return [];
  }
}

export function saveRecent(runs: RecentRun[]): RecentRun[] {
  const kept = runs.slice(0, MAX);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(kept));
  } catch {
    // Storage full or blocked: the list just doesn't persist.
  }
  return kept;
}

function ago(at: number): string {
  const s = Math.max(0, (Date.now() - at) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function RecentRecommendations({
  runs,
  activeId,
  onOpen,
  onClear,
}: {
  runs: RecentRun[];
  activeId: string | null;
  onOpen: (run: RecentRun) => void;
  onClear: () => void;
}) {
  if (runs.length === 0) return null;
  return (
    <section aria-labelledby="recent-heading" className="space-y-2" data-testid="recent-recommendations">
      <div className="flex items-baseline justify-between">
        <h2
          id="recent-heading"
          className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400"
        >
          <History className="h-3.5 w-3.5" aria-hidden />
          Recent in this browser
        </h2>
        <button type="button" onClick={onClear} className="text-xs text-brand-slate-400 hover:text-brand-accent">
          Clear
        </button>
      </div>
      <ul className="divide-y divide-brand-slate-100 overflow-hidden rounded-xl border border-brand-slate-200 bg-white dark:divide-brand-slate-700/70 dark:border-brand-slate-700 dark:bg-brand-slate-800">
        {runs.map((run) => {
          const byPriority = new Map(run.data.recommendations.map((r) => [r.priority, r.model]));
          const picks = ["cheap", "balanced", "best"].map((p) => byPriority.get(p as "cheap")).filter(Boolean);
          return (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => onOpen(run)}
                aria-current={run.id === activeId ? "true" : undefined}
                className={
                  "flex w-full flex-col gap-0.5 px-4 py-2.5 text-left transition hover:bg-brand-slate-50 dark:hover:bg-brand-slate-700/40 " +
                  (run.id === activeId ? "bg-brand-accent/5" : "")
                }
              >
                <span className="truncate text-sm text-brand-slate-800 dark:text-brand-slate-100">{run.task}</span>
                <span className="flex flex-wrap gap-x-2 text-xs text-brand-slate-500 dark:text-brand-slate-400">
                  <span>{picks.join(" · ")}</span>
                  <span aria-hidden>·</span>
                  <span>{run.data.engine?.name ?? "earlier engine"}</span>
                  <span aria-hidden>·</span>
                  <span>{ago(run.at)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
