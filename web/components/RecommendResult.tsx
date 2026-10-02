// web/components/RecommendResult.tsx
//
// A finished recommendation: the task and the engine that answered it (with
// what that run took and cost, and a way to ask another engine), the three
// picks side by side, then the selected pick's reasoning and cost beside the
// chart of where all three sit in the market.
"use client";

import Link from "next/link";
import { AlertTriangle, Cpu, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import type { MultiRecommendResponse, PriorityRecommendation } from "@/lib/api";
import { cents, seconds } from "@/lib/engine-format";
import type { BudgetPriority } from "@/lib/profile";
import type { EngineOption } from "@/lib/recommend-engines";
import { rowForPick, type PicksData } from "@/lib/recommend-picks";
import { BenchmarkReference } from "./BenchmarkReference";
import { EnginePicker } from "./EnginePicker";
import { PicksChart } from "./PicksChart";
import { PicksMatrix } from "./PicksMatrix";
import { RatingScale } from "./RatingScale";
import { TierDetail } from "./TierDetail";

// The trade-off line when every pick costs the user $0 (a subscription funds
// all three): then the picks differ in capability and effort, not price.
function fundedZeroInsight(recs: PriorityRecommendation[]): { source: string | null } | null {
  if (recs.length < 2) return null;
  const fundedRows = recs.map((r) =>
    (r.comparison_table ?? []).find(
      (row) => row.funded === true && typeof row.your_cost === "string" && row.your_cost.includes("$0"),
    ),
  );
  if (fundedRows.some((f) => !f)) return null;
  const sources = new Set(
    fundedRows.map((f) => {
      const raw = typeof f!.your_cost === "string" ? f!.your_cost : "";
      const s = raw.replace(/^✓\s*/, "").replace(/\$0/, "").replace(/^[\s·\-–—]+/, "").trim();
      return !s || s.length > 24 || s.includes("$") ? "" : s;
    }),
  );
  const source = sources.size === 1 ? [...sources][0] : null;
  return { source: source || null };
}

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
              <span title={run.cost_source === "measured" ? "What this run cost roadmodel, from the provider's reported usage" : "Estimated from the prompt size; the provider reported no usage"}>
                {cents(run.cost_usd)}
                {run.cost_source === "estimated" ? " (est.)" : ""}
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
  const [primary, setPrimary] = useState<BudgetPriority>(data.primary);
  const [selected, setSelected] = useState<BudgetPriority>(data.primary);
  const [persisting, setPersisting] = useState(false);

  useEffect(() => {
    setPrimary(data.primary);
    setSelected(data.primary);
  }, [data]);

  function setDefault(priority: BudgetPriority) {
    setPrimary(priority);
    if (!canPersist) return;
    setPersisting(true);
    void fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ budget_priority: priority }),
    })
      .catch(() => {})
      .finally(() => setPersisting(false));
  }

  const recs = data.recommendations;
  const selectedRec = recs.find((r) => r.priority === selected) ?? recs[0];
  const insight = fundedZeroInsight(recs);
  const rows = Object.values(picks.rows);

  return (
    <div className="space-y-4" data-testid="recommend-result">
      <div className="space-y-3 rounded-xl border border-brand-slate-200 bg-white px-4 py-3 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 whitespace-nowrap text-[11px] font-semibold uppercase tracking-wide text-brand-slate-400 dark:text-brand-slate-500">
            Your task
          </span>
          <p className="line-clamp-2 min-w-0 flex-1 text-sm text-brand-slate-800 dark:text-brand-slate-100" data-testid="result-task">
            {task || "—"}
          </p>
          <div className="flex flex-none gap-1.5">
            <button
              type="button"
              onClick={onEdit}
              className="rounded-md border border-brand-slate-300 px-2.5 py-1 text-xs font-semibold text-brand-slate-600 hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-600 dark:text-brand-slate-300"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={onNew}
              className="rounded-md border border-brand-slate-300 px-2.5 py-1 text-xs font-semibold text-brand-slate-600 hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-600 dark:text-brand-slate-300"
            >
              New task
            </button>
          </div>
        </div>
        <div className="border-t border-brand-slate-100 pt-3 dark:border-brand-slate-700/70">
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

      <section
        aria-label="The three picks"
        className="rounded-xl border border-brand-slate-200 bg-white p-3 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800 sm:p-4"
      >
        <div className="flex items-baseline justify-between gap-3 px-1 pb-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            Your {recs.length === 3 ? "three " : ""}picks
          </h2>
          <span className="hidden text-xs text-brand-slate-400 md:inline dark:text-brand-slate-500">
            Select a pick for its reasoning and cost
          </span>
        </div>
        {insight && (
          <div className="mb-2.5 flex items-center gap-2.5 rounded-md border border-brand-accent/30 bg-brand-accent/10 px-3 py-1.5 text-[13px] text-brand-slate-700 dark:text-brand-slate-200">
            <Sparkles className="h-4 w-4 flex-none text-brand-accent" aria-hidden />
            <span>
              All {recs.length === 3 ? "three " : ""}picks run at{" "}
              <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">$0 to you</b>
              {insight.source ? ` on ${insight.source}` : ""}: the trade-off is{" "}
              <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">capability and effort</b>,
              not price.
            </span>
          </div>
        )}
        <PicksMatrix
          recommendations={recs}
          data={picks}
          selected={selected}
          primary={primary}
          onSelect={setSelected}
        />
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
        {selectedRec && (
          <TierDetail
            rec={selectedRec}
            canPersist={canPersist}
            persisting={persisting}
            isDefault={selectedRec.priority === primary}
            onSetDefault={setDefault}
          />
        )}
        <PicksChart
          rows={rows}
          picks={recs.map((r) => ({ priority: r.priority, model: r.model, row: rowForPick(picks, r.model) }))}
          selected={selected}
          onSelect={setSelected}
        />
      </div>

      <details className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
          How to read these picks
          <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">show</span>
          <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">hide</span>
        </summary>
        <div className="grid gap-6 border-t border-brand-slate-200 px-5 py-5 text-sm text-brand-slate-600 dark:border-brand-slate-700 dark:text-brand-slate-300 md:grid-cols-2">
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
              The three picks
            </h3>
            <p>
              <b className="text-brand-slate-800 dark:text-brand-slate-100">Quality</b> is the strongest model for the
              task. <b className="text-brand-slate-800 dark:text-brand-slate-100">Balanced</b> is the best value below
              it, and <b className="text-brand-slate-800 dark:text-brand-slate-100">Cost</b> is the cheapest model that
              still does the job. Each comes with the platform to run it on and its settings.
            </p>
            <p>
              The letters are the catalog&rsquo;s S&rarr;D ratings in coding, planning, agentic, multimodal,
              long-context, knowledge and speed. A filled letter is measured from an Artificial Analysis benchmark; a
              dashed one is estimated. The <Link href="/models#how-to-read" className="font-medium text-brand-accent hover:underline">catalog key</Link> has the rules.
            </p>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
              Rating scale
            </h3>
            <RatingScale compact />
          </div>
          <div className="md:col-span-2">
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
    </div>
  );
}
