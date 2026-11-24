// web/components/RecommendResult.tsx
//
// A finished recommendation from the AI recommender: the task as written and
// what it was read as, the engine that answered (with what that run took and
// cost, and a way to ask another engine), then the answer itself
// (LadderResult): the three picks ranked three deep, the selected pick's
// reasoning and cost, and the chart of where they sit on the frontier.
"use client";

import { AlertTriangle, Cpu } from "lucide-react";
import { useMemo } from "react";

import type { MultiRecommendResponse } from "@/lib/api";
import { cents, runCostNote, seconds } from "@/lib/engine-format";
import { engineLadder } from "@/lib/ladder-view";
import type { EngineOption } from "@/lib/recommend-engines";
import type { PicksData } from "@/lib/recommend-picks";
import { EnginePicker } from "./EnginePicker";
import { LadderResult, TaskChips } from "./LadderResult";

function EngineLine({
  data,
  engines,
  rerunEngine,
  onRerunEngineChange,
  onRerun,
  signedIn,
  pending,
}: {
  data: MultiRecommendResponse;
  engines: EngineOption[];
  rerunEngine: string;
  onRerunEngineChange: (hint: string) => void;
  onRerun: () => void;
  signedIn: boolean;
  pending: boolean;
}) {
  const run = data.engine;
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2" data-testid="engine-line">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
        <Cpu className="h-4 w-4 flex-none text-brand-slate-400" aria-hidden />
        {run ? (
          <>
            <span>
              Picked by <strong className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">{run.name}</strong>
            </span>
            <span className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
              {run.latency_ms !== null ? `${seconds(run.latency_ms / 1000)} · ` : ""}
              <span title={runCostNote(run.funded_by ?? "operator", run.cost_source === "measured")}>
                {cents(run.cost_usd)}
                {run.cost_source === "estimated" ? " (est.)" : ""}
                {run.funded_by === "visitor" ? ", billed to your key" : ""}
              </span>
              {run.cached_share !== null && run.cached_share > 0.5 ? " · prompt cached" : ""}
            </span>
          </>
        ) : (
          <span>Recommendation</span>
        )}
      </p>
      <div className="flex items-center gap-2">
        <EnginePicker
          options={engines}
          value={rerunEngine}
          onChange={onRerunEngineChange}
          signedIn={signedIn}
          disabled={pending}
        />
        <button
          type="button"
          onClick={onRerun}
          disabled={pending}
          className="rounded-lg border border-brand-slate-300 px-3 py-2 text-sm font-semibold text-brand-slate-700 transition hover:border-brand-accent hover:text-brand-accent disabled:opacity-50 dark:border-brand-slate-600 dark:text-brand-slate-200"
          data-testid="rerun"
        >
          Run again
        </button>
      </div>
      {run?.fell_back && (
        <p
          className="flex w-full items-start gap-2 rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
          role="status"
          data-testid="engine-fell-back"
        >
          <AlertTriangle className="mt-px h-3.5 w-3.5 flex-none" aria-hidden />
          {run.requested_name} did not answer, so {run.name} wrote these picks.
        </p>
      )}
    </div>
  );
}

const BAR_BUTTON =
  "rounded-md border border-brand-slate-300 px-2.5 py-1 text-xs font-semibold text-brand-slate-600 hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-600 dark:text-brand-slate-300";
const BAR_LABEL =
  "whitespace-nowrap text-[11px] font-semibold uppercase tracking-wide text-brand-slate-400 dark:text-brand-slate-500";

export function RecommendResult({
  data,
  task,
  picks,
  engines,
  rerunEngine,
  onRerunEngineChange,
  onRerun,
  onEdit,
  onNew,
  canPersist,
  signedIn,
  pending,
}: {
  data: MultiRecommendResponse;
  task: string;
  picks: PicksData;
  engines: EngineOption[];
  rerunEngine: string;
  onRerunEngineChange: (hint: string) => void;
  onRerun: () => void;
  onEdit: () => void;
  onNew: () => void;
  canPersist: boolean;
  signedIn: boolean;
  pending: boolean;
}) {
  const view = useMemo(() => engineLadder(picks, data), [picks, data]);

  const header = (
    <div className="rounded-xl border border-brand-slate-200 bg-white shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800">
      <div className="space-y-2.5 px-5 py-3.5">
        <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
          <span className={"mt-0.5 w-16 flex-none " + BAR_LABEL}>Your task</span>
          <p
            className="line-clamp-2 min-w-0 flex-1 basis-48 text-sm text-brand-slate-800 dark:text-brand-slate-100"
            data-testid="result-task"
          >
            {task || "—"}
          </p>
          <div className="ml-auto flex flex-none gap-1.5">
            <button type="button" onClick={onEdit} className={BAR_BUTTON}>
              Edit
            </button>
            <button type="button" onClick={onNew} className={BAR_BUTTON}>
              New task
            </button>
          </div>
        </div>
        {view.task && (
          <div className="flex items-center gap-3">
            <span className={"w-16 flex-none " + BAR_LABEL}>Read as</span>
            <TaskChips task={view.task} />
          </div>
        )}
      </div>
      <div className="border-t border-brand-slate-200 px-5 py-3 dark:border-brand-slate-700">
        <EngineLine
          data={data}
          engines={engines}
          rerunEngine={rerunEngine}
          onRerunEngineChange={onRerunEngineChange}
          onRerun={onRerun}
          signedIn={signedIn}
          pending={pending}
        />
      </div>
    </div>
  );

  return <LadderResult view={view} picks={picks} header={header} canPersist={canPersist} testId="recommend-result" />;
}
