// web/components/TierMatrix.tsx
"use client";

import { Fragment } from "react";

import type { PriorityRecommendation } from "@/lib/api";
import { BUDGET_PRIORITY_OPTIONS } from "@/lib/budget-priority";
import type { BudgetPriority } from "@/lib/profile";
import { formatSettingValue, humanizeSettingKey } from "@/lib/settings-format";

// The redesign replaces three stacked cards with ONE comparison matrix: the
// Cost / Balanced / Quality picks are COLUMNS and their shared attributes
// (Your cost, the per-surface settings, Backup) are ROWS — so the repeated card
// chrome collapses to a single row label read once and scanned across. Clicking
// a column header selects that pick; its full rationale + cost render in the
// detail panel beside the matrix.

const LABELS = new Map(BUDGET_PRIORITY_OPTIONS.map((o) => [o.id, o]));

// Terse column subtitles — the full budget-priority hints ("Cheapest model that
// can do the job") wrap and crowd the compact column headers, so the matrix uses
// short forms while Settings keeps the descriptive ones.
const SHORT_HINT: Record<string, string> = {
  cheap: "Cheapest that works",
  balanced: "Best value",
  best: "Highest quality",
};

// budget_priority is redundant with the column itself; rationale renders in the
// detail panel. Everything else in `settings` becomes a comparison row.
const HIDDEN_SETTING_KEYS = new Set(["rationale", "budget_priority"]);

// The union of setting keys across the picks, in first-seen order, so every
// surface-specific dimension (effort, thinking, max_mode, intelligence …) gets
// a row even when only one pick emits it.
function settingKeys(recs: PriorityRecommendation[]): string[] {
  const seen: string[] = [];
  for (const rec of recs) {
    for (const key of Object.keys(rec.settings ?? {})) {
      if (!HIDDEN_SETTING_KEYS.has(key) && !seen.includes(key)) {
        seen.push(key);
      }
    }
  }
  return seen;
}

// The single headline cost for a pick: the user's funded cost when the edge
// personalized the cost table, else the session estimate, else an em dash. The
// full per-platform breakdown lives in the detail panel (CostComparison).
function headlineCost(rec: PriorityRecommendation): {
  text: string;
  funded: boolean;
} {
  const table = rec.comparison_table ?? [];
  const fundedRow = table.find(
    (row) => row.funded === true && typeof row.your_cost === "string",
  );
  if (fundedRow) {
    return { text: String(fundedRow.your_cost), funded: true };
  }
  const total = rec.session_cost_estimate?.total_usd;
  if (typeof total === "number") {
    return { text: `$${total.toFixed(4)}`, funded: false };
  }
  return { text: "—", funded: false };
}

interface TierMatrixProps {
  recommendations: PriorityRecommendation[];
  // The pick whose detail is shown (highlighted column).
  selected: BudgetPriority;
  // The pinned default (leads with the "Default" badge).
  primary: BudgetPriority;
  onSelect: (priority: BudgetPriority) => void;
}

export function TierMatrix({
  recommendations,
  selected,
  primary,
  onSelect,
}: TierMatrixProps) {
  const keys = settingKeys(recommendations);
  const showBackup = recommendations.some((r) => typeof r.backup === "string" && r.backup);
  const n = recommendations.length;
  const gridStyle = {
    gridTemplateColumns: `minmax(92px, 116px) repeat(${n}, minmax(0, 1fr))`,
  };

  const cellBase =
    "flex items-center gap-1.5 px-3 py-2 text-sm border-t border-brand-slate-100 dark:border-brand-slate-800";
  const activeCell = "bg-brand-accent/5";
  const rowLabel =
    "flex items-center py-2 text-xs font-medium text-brand-slate-500 dark:text-brand-slate-400 border-t border-brand-slate-100 dark:border-brand-slate-800";

  return (
    <div className="grid" style={gridStyle}>
      {/* header row: empty corner + one selectable head per pick */}
      <div aria-hidden />
      {recommendations.map((rec) => {
        const meta = LABELS.get(rec.priority);
        const isSelected = rec.priority === selected;
        const isPrimary = rec.priority === primary;
        return (
          <button
            key={rec.priority}
            type="button"
            data-priority={rec.priority}
            aria-pressed={isSelected}
            onClick={() => onSelect(rec.priority)}
            className={
              "relative flex flex-col gap-1 rounded-t-lg px-3 pb-3 pt-2.5 text-left transition-colors " +
              (isSelected
                ? "bg-brand-accent/5 ring-1 ring-inset ring-brand-accent"
                : "hover:bg-brand-slate-50 dark:hover:bg-brand-slate-800/60")
            }
          >
            {isPrimary ? (
              <span className="absolute right-2.5 top-2.5 rounded-full bg-brand-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-accent">
                Default
              </span>
            ) : null}
            <span className="text-xs font-semibold uppercase tracking-wide text-brand-accent">
              {meta?.label ?? rec.priority}
            </span>
            <span className="text-[11px] leading-tight text-brand-slate-500 dark:text-brand-slate-400">
              {SHORT_HINT[rec.priority] ?? meta?.hint}
            </span>
            <span className="mt-0.5 text-lg font-bold leading-tight text-brand-slate-900 dark:text-brand-slate-50">
              {rec.model}
            </span>
            <span className="mt-0.5 inline-flex w-fit rounded-full bg-brand-accent-muted px-2.5 py-0.5 text-[11px] font-medium text-brand-accent">
              {rec.platform}
            </span>
          </button>
        );
      })}

      {/* Your cost */}
      <div className={rowLabel}>Your cost</div>
      {recommendations.map((rec) => {
        const cost = headlineCost(rec);
        const isSelected = rec.priority === selected;
        return (
          <div
            key={rec.priority}
            className={
              cellBase +
              " " +
              (isSelected ? activeCell + " " : "") +
              (cost.funded
                ? "font-semibold text-green-600 dark:text-green-400"
                : "text-brand-slate-700 dark:text-brand-slate-200")
            }
          >
            {cost.funded ? "✓ " : ""}
            {cost.text}
          </div>
        );
      })}

      {/* one row per shared setting dimension */}
      {keys.map((key) => (
        <Fragment key={key}>
          <div className={rowLabel}>{humanizeSettingKey(key)}</div>
          {recommendations.map((rec) => {
            const isSelected = rec.priority === selected;
            return (
              <div
                key={rec.priority}
                className={
                  cellBase +
                  " text-brand-slate-700 dark:text-brand-slate-200 " +
                  (isSelected ? activeCell : "")
                }
              >
                {formatSettingValue((rec.settings ?? {})[key])}
              </div>
            );
          })}
        </Fragment>
      ))}

      {/* Backup (only when a pick emitted one) */}
      {showBackup ? (
        <>
          <div className={rowLabel}>Backup</div>
          {recommendations.map((rec) => {
            const isSelected = rec.priority === selected;
            return (
              <div
                key={rec.priority}
                className={
                  cellBase +
                  " text-brand-slate-700 dark:text-brand-slate-200 " +
                  (isSelected ? activeCell : "")
                }
              >
                {typeof rec.backup === "string" && rec.backup ? rec.backup : "—"}
              </div>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
