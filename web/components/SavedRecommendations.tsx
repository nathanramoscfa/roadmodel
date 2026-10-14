// web/components/SavedRecommendations.tsx
//
// The recommendations saved in this browser (lib/use-saved-recommendations.ts),
// newest first: open one again without paying for it, delete it, search them,
// or export them to a file and import that file in another browser. They are
// kept only here; roadmodel's servers never receive them.
"use client";

import { Download, History, Upload, X } from "lucide-react";
import { useRef, useState } from "react";

import { pickedModels, type SavedRun } from "@/lib/saved-recommendations";
import type { SavedStatus } from "@/lib/use-saved-recommendations";

// Shown before "Show all"; a search shows every match.
const SHOWN = 8;

function ago(at: number): string {
  const s = Math.max(0, (Date.now() - at) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function engineName(run: SavedRun): string {
  return run.kind === "quick" ? "Quick pick" : run.data.engine?.name ?? "earlier engine";
}

function short(task: string): string {
  return task.length > 80 ? `${task.slice(0, 79)}…` : task;
}

const ACTION = "inline-flex items-center gap-1 text-xs text-brand-slate-400 hover:text-brand-accent";

export function SavedRecommendations({
  runs,
  activeId,
  status,
  onOpen,
  onDelete,
  onClear,
  onExport,
  onImport,
}: {
  runs: SavedRun[];
  activeId: string | null;
  status: SavedStatus | null;
  onOpen: (run: SavedRun) => void;
  onDelete: (run: SavedRun) => void;
  onClear: () => void;
  onExport: () => void;
  onImport: (file: File) => void;
}) {
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? runs.filter((r) => r.task.toLowerCase().includes(needle) || pickedModels(r).some((m) => m.toLowerCase().includes(needle)))
    : runs;
  const shown = all || needle ? matches : matches.slice(0, SHOWN);

  return (
    <section aria-labelledby="saved-heading" className="space-y-2" data-testid="saved-recommendations">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2
          id="saved-heading"
          className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400"
        >
          <History className="h-3.5 w-3.5" aria-hidden />
          Saved in this browser{runs.length > 0 ? ` (${runs.length})` : ""}
        </h2>
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => file.current?.click()} className={ACTION}>
            <Upload className="h-3 w-3" aria-hidden />
            Import
          </button>
          {runs.length > 0 && (
            <>
              <button type="button" onClick={onExport} className={ACTION} data-testid="saved-export">
                <Download className="h-3 w-3" aria-hidden />
                Export
              </button>
              <button type="button" onClick={() => setConfirming(true)} className={ACTION}>
                Clear
              </button>
            </>
          )}
        </div>
        <input
          ref={file}
          type="file"
          accept=".json,application/json"
          className="hidden"
          data-testid="saved-import-file"
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            e.target.value = "";
            if (chosen) onImport(chosen);
          }}
        />
      </div>

      {confirming && runs.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-brand-slate-200 px-4 py-2 text-sm text-brand-slate-700 dark:border-brand-slate-700 dark:text-brand-slate-200">
          <span>Remove all {runs.length} saved recommendations from this browser?</span>
          <button
            type="button"
            onClick={() => {
              setConfirming(false);
              onClear();
            }}
            className="font-semibold text-red-600 hover:underline dark:text-red-400"
          >
            Remove all
          </button>
          <button type="button" onClick={() => setConfirming(false)} className="text-brand-slate-500 hover:underline">
            Cancel
          </button>
        </div>
      )}

      {status && (
        <p
          role={status.error ? "alert" : "status"}
          data-testid="saved-status"
          className={"text-xs " + (status.error ? "text-red-600 dark:text-red-400" : "text-brand-slate-500 dark:text-brand-slate-400")}
        >
          {status.text}
        </p>
      )}

      {runs.length > SHOWN && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search saved recommendations"
          aria-label="Search saved recommendations"
          className="w-full rounded-lg border border-brand-slate-200 bg-white px-3 py-1.5 text-sm text-brand-slate-800 placeholder:text-brand-slate-400 focus:border-brand-accent focus:outline-none dark:border-brand-slate-700 dark:bg-brand-slate-800 dark:text-brand-slate-100"
        />
      )}

      {shown.length > 0 && (
        <ul className="divide-y divide-brand-slate-100 overflow-hidden rounded-xl border border-brand-slate-200 bg-white dark:divide-brand-slate-700/70 dark:border-brand-slate-700 dark:bg-brand-slate-800">
          {shown.map((run) => (
            <li key={run.id} className={"flex items-stretch " + (run.id === activeId ? "bg-brand-accent/5" : "")}>
              <button
                type="button"
                onClick={() => onOpen(run)}
                aria-current={run.id === activeId ? "true" : undefined}
                className="flex min-w-0 flex-1 flex-col gap-0.5 px-4 py-2.5 text-left transition hover:bg-brand-slate-50 dark:hover:bg-brand-slate-700/40"
              >
                <span className="truncate text-sm text-brand-slate-800 dark:text-brand-slate-100">{run.task}</span>
                <span className="flex flex-wrap gap-x-2 text-xs text-brand-slate-500 dark:text-brand-slate-400">
                  <span>{pickedModels(run).join(" · ")}</span>
                  <span aria-hidden>·</span>
                  <span>{engineName(run)}</span>
                  <span aria-hidden>·</span>
                  <span>{ago(run.at)}</span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => onDelete(run)}
                aria-label={`Delete “${short(run.task)}”`}
                data-testid="saved-delete"
                className="flex-none px-3 text-brand-slate-400 transition hover:bg-brand-slate-50 hover:text-red-600 dark:hover:bg-brand-slate-700/40 dark:hover:text-red-400"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}

      {!all && !needle && matches.length > SHOWN && (
        <button type="button" onClick={() => setAll(true)} className="text-xs font-semibold text-brand-accent hover:underline">
          Show all {matches.length}
        </button>
      )}
      {needle && matches.length === 0 && (
        <p className="text-sm text-brand-slate-500 dark:text-brand-slate-400">No saved recommendation matches.</p>
      )}

      <p className="text-xs text-brand-slate-400 dark:text-brand-slate-500">
        Every recommendation you get is saved here, in this browser only; roadmodel never receives it. Export a file to
        back them up or to move them to another browser.
      </p>
    </section>
  );
}
