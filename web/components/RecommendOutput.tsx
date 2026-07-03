// web/components/RecommendOutput.tsx
"use client";

import { useEffect, useState } from "react";
import type { MultiRecommendResponse, PriorityRecommendation } from "@/lib/api";
import { FreeTierLabel } from "./FreeTierLabel";
import { TierDetail } from "./TierDetail";
import { TierMatrix } from "./TierMatrix";

interface RecommendOutputProps {
  data: MultiRecommendResponse;
  // Signed-in users can pin a priority as their default emphasis (persists to
  // Settings); signed-out users get the picks without the control.
  canPersist: boolean;
}

// The redesign renders the three priority picks as a single comparison matrix
// (Cost / Balanced / Quality as columns, shared attributes as rows) beside a
// detail panel for the SELECTED pick — replacing the three tall stacked cards
// that overflowed the viewport and read as duplicates. `selected` drives the
// detail (click a column to switch); `primary` is the pinned default badge.
export function RecommendOutput({ data, canPersist }: RecommendOutputProps) {
  const [primary, setPrimary] = useState(data.primary);
  const [selected, setSelected] = useState(data.primary);
  const [persisting, setPersisting] = useState(false);

  useEffect(() => {
    setPrimary(data.primary);
    setSelected(data.primary);
  }, [data]);

  function handleSetDefault(priority: PriorityRecommendation["priority"]): void {
    // Optimistic: the badge moves immediately; a failed sync never blocks the UI.
    setPrimary(priority);
    if (!canPersist) {
      return;
    }
    setPersisting(true);
    void fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ budget_priority: priority }),
    })
      .catch(() => {})
      .finally(() => setPersisting(false));
  }

  const selectedRec =
    data.recommendations.find((r) => r.priority === selected) ??
    data.recommendations[0];

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-3 shadow-sm sm:p-4">
        <div className="flex items-baseline justify-between gap-3 px-1 pb-1">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            Your picks
          </h2>
          <span className="text-xs text-brand-slate-400 dark:text-brand-slate-500">
            Select a pick to see why &amp; the full cost
          </span>
        </div>
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr] lg:items-start">
          <TierMatrix
            recommendations={data.recommendations}
            selected={selected}
            primary={primary}
            onSelect={setSelected}
          />
          {selectedRec ? (
            <TierDetail
              rec={selectedRec}
              canPersist={canPersist}
              persisting={persisting}
              isDefault={selectedRec.priority === primary}
              onSetDefault={handleSetDefault}
            />
          ) : null}
        </div>
      </div>
      {selectedRec ? (
        <FreeTierLabel
          surface="recommend"
          tier={selectedRec.tier}
          engine={selectedRec.engine}
        />
      ) : null}
    </div>
  );
}
