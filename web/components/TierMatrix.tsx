// web/components/TierMatrix.tsx
"use client";

import { Fragment, type ReactNode } from "react";

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
// detail panel. `orchestration` is never its own row: Claude Code has no separate
// orchestration dial — Ultracode is the top of its single Effort ladder, so the
// package folds it into the effort VALUE (roadmodel >=0.2.16). Hiding the key
// here also cleans up any stale/cached record that still carries it. Everything
// else in `settings` becomes a comparison row.
const HIDDEN_SETTING_KEYS = new Set(["rationale", "budget_priority", "orchestration"]);

// Active-column outline (matches mockups/recommend-redesign.html). The selected
// column reads as ONE continuous rounded box: the header carries an accent
// border on its top + sides (no bottom, so it flows into the cells), every cell
// carries accent side-borders via inset box-shadows, and the LAST cell adds a
// bottom border + rounded bottom corners to close the box. A subtle accent tint
// fills the whole column. #2563eb == brand-accent DEFAULT (tailwind.config.ts).
const ACTIVE_TINT = "bg-brand-accent/10";
const ACTIVE_HEAD = "border-brand-accent border-b-transparent " + ACTIVE_TINT;
const ACTIVE_CELL_SIDES = "shadow-[inset_1.5px_0_0_#2563eb,inset_-1.5px_0_0_#2563eb]";
const ACTIVE_CELL_LAST =
  "shadow-[inset_1.5px_0_0_#2563eb,inset_-1.5px_0_0_#2563eb,inset_0_-1.5px_0_#2563eb] rounded-b-lg";

// A cell value that carries no signal — an off/absent dial. A row where EVERY
// pick is one of these (e.g. "Max Mode: Off / — / —" when no pick is on a
// Max-Mode surface) is dropped so the matrix shows only differentiating dials,
// keeping the result compact like the mock (which omits such rows).
const MEANINGLESS_VALUES = new Set(["", "—", "-", "off", "n/a", "na", "none"]);

function isMeaningful(value: string): boolean {
  return !MEANINGLESS_VALUES.has(value.trim().toLowerCase());
}

// The backup's reasoning effort for display: the LEVEL from its per-surface
// settings — effort / intelligence, or a thinking level (not the On/Off toggle).
function backupEffortLabel(
  settings: Record<string, string> | undefined,
): string | null {
  if (!settings) return null;
  const effort = settings.effort ?? settings.intelligence;
  if (effort && isMeaningful(effort)) return formatSettingValue(effort);
  const thinking = settings.thinking;
  if (
    thinking &&
    !["on", "off"].includes(thinking.trim().toLowerCase()) &&
    isMeaningful(thinking)
  ) {
    return formatSettingValue(thinking);
  }
  return null;
}

// The Backup cell: model name + its own funded platform pill (with effort), so
// the fallback shows HOW to run it — mirroring a pick's model + platform header
// and adhering to the user's settings. Degrades to just the name (or an em dash)
// when platform/settings are unresolved (anon / no funding).
function backupCell(backup: PriorityRecommendation["backup"]): ReactNode {
  if (!backup?.model) return "—";
  const effort = backupEffortLabel(backup.settings);
  return (
    <span className="flex flex-col items-start gap-1">
      <span>{backup.model}</span>
      {backup.platform ? (
        <span className="inline-flex w-fit rounded-full bg-brand-accent-muted px-2 py-0.5 text-[10px] font-medium text-brand-accent">
          {backup.platform}
          {effort ? ` · ${effort}` : ""}
        </span>
      ) : null}
    </span>
  );
}

// The union of setting keys across the picks, in first-seen order, so every
// surface-specific dimension (effort, thinking, max_mode, intelligence …) gets
// a row even when only one pick emits it — EXCEPT a key whose value is
// non-meaningful for every pick (dropped, see MEANINGLESS_VALUES).
function settingKeys(recs: PriorityRecommendation[]): string[] {
  const seen: string[] = [];
  for (const rec of recs) {
    for (const key of Object.keys(rec.settings ?? {})) {
      if (!HIDDEN_SETTING_KEYS.has(key) && !seen.includes(key)) {
        seen.push(key);
      }
    }
  }
  return seen.filter((key) =>
    recs.some((rec) => isMeaningful(formatSettingValue((rec.settings ?? {})[key]))),
  );
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

// One matrix row: a label plus a per-pick cell. `funded` lets the "Your cost"
// row tint its value green; other rows leave it undefined.
interface MatrixRow {
  key: string;
  label: string;
  cell: (rec: PriorityRecommendation) => { node: ReactNode; funded?: boolean };
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
  const showBackup = recommendations.some((r) => r.backup?.model);
  const n = recommendations.length;
  const gridStyle = {
    gridTemplateColumns: `minmax(92px, 116px) repeat(${n}, minmax(0, 1fr))`,
  };

  const cellBase =
    "flex items-center gap-1.5 px-3 py-1.5 text-sm border-t border-brand-slate-100 dark:border-brand-slate-800";
  const rowLabel =
    "flex items-center py-1.5 text-xs font-medium text-brand-slate-500 dark:text-brand-slate-400 border-t border-brand-slate-100 dark:border-brand-slate-800";

  // Every matrix row in render order — so the LAST one can close the column box.
  const rows: MatrixRow[] = [
    {
      key: "__cost",
      label: "Your cost",
      cell: (rec) => {
        const cost = headlineCost(rec);
        // Match the mock: the amount ("$0") in the funded/green weight, the
        // funding source ("Claude Max") as a muted sub-label — split off the
        // "$0 · Claude Max" your_cost string (drop any leading ✓).
        const [amount, ...rest] = cost.text.replace(/^✓\s*/, "").split(/\s*·\s*/);
        const source = rest.join(" · ");
        return {
          node: (
            <>
              <span>{amount}</span>
              {source ? (
                <span className="font-normal text-brand-slate-400 dark:text-brand-slate-500">
                  {source}
                </span>
              ) : null}
            </>
          ),
          funded: cost.funded,
        };
      },
    },
    ...keys.map(
      (key): MatrixRow => ({
        key,
        label: humanizeSettingKey(key),
        cell: (rec) => ({ node: formatSettingValue((rec.settings ?? {})[key]) }),
      }),
    ),
    ...(showBackup
      ? [
          {
            key: "__backup",
            label: "Backup",
            cell: (rec: PriorityRecommendation) => ({
              node: backupCell(rec.backup),
            }),
          } satisfies MatrixRow,
        ]
      : []),
  ];

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
              "flex flex-col gap-0.5 rounded-t-lg border-[1.5px] px-3 pb-2.5 pt-2 text-left transition-colors " +
              (isSelected
                ? ACTIVE_HEAD
                : "border-transparent hover:bg-brand-slate-50 dark:hover:bg-brand-slate-800/60")
            }
          >
            {/* Label and DEFAULT badge share one in-flow row (justify-between)
                so the badge can never overlap the column label — an absolutely
                positioned badge ran under "BALANCED"/"QUALITY" on narrow columns. */}
            <div className="flex items-start justify-between gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-brand-accent">
                {meta?.label ?? rec.priority}
              </span>
              {isPrimary ? (
                <span className="shrink-0 rounded-full bg-brand-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-accent">
                  Default
                </span>
              ) : null}
            </div>
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

      {/* one row per dimension; the last row closes the active column's box */}
      {rows.map((row, rowIndex) => {
        const isLastRow = rowIndex === rows.length - 1;
        return (
          <Fragment key={row.key}>
            <div className={rowLabel}>{row.label}</div>
            {recommendations.map((rec) => {
              const isSelected = rec.priority === selected;
              const { node, funded } = row.cell(rec);
              const color = funded
                ? "font-semibold text-green-600 dark:text-green-400"
                : "text-brand-slate-700 dark:text-brand-slate-200";
              const active = isSelected
                ? ` ${ACTIVE_TINT} ${isLastRow ? ACTIVE_CELL_LAST : ACTIVE_CELL_SIDES}`
                : "";
              return (
                <div
                  key={rec.priority}
                  className={`${cellBase} ${color}${active}`}
                >
                  {node}
                </div>
              );
            })}
          </Fragment>
        );
      })}
    </div>
  );
}
