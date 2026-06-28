// web/components/PriorityCard.tsx
"use client";

import type { PriorityRecommendation } from "@/lib/api";
import { BUDGET_PRIORITY_OPTIONS } from "@/lib/budget-priority";
import { CostComparison } from "./CostComparison";
import { ModelHeader } from "./ModelHeader";
import { SettingsList } from "./SettingsList";
import { WhyDisclosure } from "./WhyDisclosure";

const LABEL = new Map(
  BUDGET_PRIORITY_OPTIONS.map((o) => [o.id, { label: o.label, hint: o.hint }]),
);

function extractRationale(data: PriorityRecommendation): string | null {
  const fromSettings = data.settings.rationale;
  if (typeof fromSettings === "string" && fromSettings.trim()) {
    return fromSettings;
  }
  const first = data.comparison_table[0];
  if (first && typeof first.rationale === "string") {
    return first.rationale;
  }
  return null;
}

interface PriorityCardProps {
  data: PriorityRecommendation;
  // The currently-highlighted priority leads with a ring + "Default" badge.
  isPrimary: boolean;
  // Signed-in users can pin a priority as their default emphasis (persists to
  // Settings). Signed-out users see the three picks but no persistence control.
  canPersist: boolean;
  // A persist is mid-flight (button disabled to avoid double PATCH).
  persisting: boolean;
  onSetDefault: (priority: PriorityRecommendation["priority"]) => void;
}

export function PriorityCard({
  data,
  isPrimary,
  canPersist,
  persisting,
  onSetDefault,
}: PriorityCardProps) {
  const meta = LABEL.get(data.priority);
  const rationale = extractRationale(data);

  return (
    <div
      data-priority={data.priority}
      className={
        "flex flex-col gap-5 rounded-xl border bg-white dark:bg-brand-slate-800 p-5 shadow-sm " +
        (isPrimary
          ? "border-brand-accent ring-2 ring-brand-accent/30"
          : "border-brand-slate-200 dark:border-brand-slate-700")
      }
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
            {meta?.label ?? data.priority}
          </h2>
          {meta?.hint ? (
            <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
              {meta.hint}
            </span>
          ) : null}
        </div>
        {isPrimary ? (
          <span className="rounded-full bg-brand-accent/10 px-2 py-0.5 text-xs font-medium text-brand-accent">
            Default
          </span>
        ) : canPersist ? (
          <button
            type="button"
            disabled={persisting}
            onClick={() => onSetDefault(data.priority)}
            className="text-xs font-medium text-brand-slate-500 underline-offset-2 hover:text-brand-accent hover:underline disabled:opacity-50 dark:text-brand-slate-400"
          >
            Set as default
          </button>
        ) : null}
      </div>

      <ModelHeader model={data.model} platform={data.platform} />
      {data.backup ? (
        <p className="-mt-3 text-sm text-brand-slate-500 dark:text-brand-slate-400">
          Backup if unavailable:{" "}
          <span className="font-medium text-brand-slate-700 dark:text-brand-slate-200">
            {data.backup}
          </span>
        </p>
      ) : null}
      <SettingsList settings={data.settings} />
      <CostComparison comparisonTable={data.comparison_table} />
      <WhyDisclosure rationale={rationale} />
    </div>
  );
}
