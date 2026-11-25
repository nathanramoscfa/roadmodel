// web/components/PickDetail.tsx
//
// The selected pick, explained: its reasoning beside what it costs this
// viewer on each platform that runs it, with the control that makes its tier
// the viewer's default. The tabs repeat the cards' selection so a reader down
// here can switch picks without scrolling back up.
"use client";

import { Check } from "lucide-react";

import { PRIORITY_LABEL, type ColumnView, type LadderView } from "@/lib/ladder-view";
import type { BudgetPriority } from "@/lib/profile";
import { CostComparison } from "./CostComparison";
import { whereText } from "./PicksLadder";
import { WhyDisclosure } from "./WhyDisclosure";

export function PickDetail({
  view,
  column,
  selected,
  onSelect,
  canPersist,
  persisting,
  isDefault,
  onSetDefault,
}: {
  view: LadderView;
  column: ColumnView;
  selected: BudgetPriority;
  onSelect: (priority: BudgetPriority) => void;
  // A signed-in viewer can keep the selected tier as their default.
  canPersist: boolean;
  persisting: boolean;
  isDefault: boolean;
  onSetDefault: (priority: BudgetPriority) => void;
}) {
  const hasCost = column.costRows.length > 0;
  const hasWhy = column.why.sections.length > 0 || Boolean(column.why.rationale?.trim());
  const meta = PRIORITY_LABEL[column.priority];
  const row = column.pick.row;
  const listPrice = row ? { input: row.input_price_per_1m, output: row.output_price_per_1m } : null;

  return (
    <section
      aria-label={`The ${meta.label} pick in detail`}
      className="rounded-xl border border-brand-slate-200 bg-white shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
      data-testid="pick-detail"
      data-pick={column.priority}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-brand-slate-200 px-5 py-3 dark:border-brand-slate-700">
        <p className="min-w-0 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          <span className="font-semibold uppercase tracking-wide text-brand-accent">{meta.label}</span>
          <span className="mx-2 text-brand-slate-300 dark:text-brand-slate-600" aria-hidden>
            /
          </span>
          <span className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">{column.pick.model}</span>
          {whereText(column.pick) && <span className="ml-2">on {whereText(column.pick)}</span>}
        </p>
        {view.columns.length > 1 && (
          <div
            role="tablist"
            aria-label="Pick shown in detail"
            className="hidden gap-1 rounded-lg bg-brand-slate-100 p-1 md:inline-flex dark:bg-brand-slate-900"
            data-testid="pick-detail-tabs"
          >
            {view.columns.map((c) => (
              <button
                key={c.priority}
                type="button"
                role="tab"
                aria-selected={c.priority === selected}
                onClick={() => onSelect(c.priority)}
                className={
                  "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wide transition " +
                  (c.priority === selected
                    ? "bg-white text-brand-accent shadow-sm dark:bg-brand-slate-700"
                    : "text-brand-slate-500 hover:text-brand-slate-800 dark:text-brand-slate-400 dark:hover:text-brand-slate-100")
                }
              >
                {PRIORITY_LABEL[c.priority].label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div
        className={
          "grid gap-x-8 gap-y-5 px-5 py-5 " +
          (hasCost && hasWhy ? "lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]" : "")
        }
      >
        {hasWhy && (
          <WhyDisclosure rationale={column.why.rationale} sections={column.why.sections} model={column.pick.model} />
        )}

        {hasCost && (
          <div>
            <h3 className="text-base font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              Your cost by platform
            </h3>
            <div className="mt-3">
              <CostComparison comparisonTable={column.costRows} listPrice={listPrice} />
            </div>
          </div>
        )}

        {!hasWhy && !hasCost && (
          <p className="text-sm text-brand-slate-500 dark:text-brand-slate-400">
            This answer carries no reasoning for the pick.
          </p>
        )}
      </div>

      {canPersist && (
        <div className="flex items-center gap-3 border-t border-brand-slate-200 px-5 py-3 text-xs dark:border-brand-slate-700">
          {isDefault ? (
            <p className="inline-flex items-center gap-1.5 font-medium text-green-600 dark:text-green-400" data-testid="pick-default">
              <Check className="h-3.5 w-3.5" aria-hidden />
              {meta.label} is your default: the tier a new recommendation opens on
            </p>
          ) : (
            <>
              <button
                type="button"
                disabled={persisting}
                onClick={() => onSetDefault(column.priority)}
                className="rounded-md border border-brand-slate-300 px-3 py-1.5 font-semibold text-brand-slate-600 hover:border-brand-accent hover:text-brand-accent disabled:opacity-50 dark:border-brand-slate-600 dark:text-brand-slate-300"
              >
                Set as default
              </button>
              <span className="text-brand-slate-500 dark:text-brand-slate-400">
                Open new recommendations on {meta.label}
              </span>
            </>
          )}
        </div>
      )}
    </section>
  );
}
