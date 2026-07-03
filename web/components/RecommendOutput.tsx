// web/components/RecommendOutput.tsx
"use client";

import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { MultiRecommendResponse, PriorityRecommendation } from "@/lib/api";
import { FreeTierLabel } from "./FreeTierLabel";
import { RatingKey } from "./RatingKey";
import { TierDetail } from "./TierDetail";
import { TierMatrix } from "./TierMatrix";

interface RecommendOutputProps {
  data: MultiRecommendResponse;
  // Signed-in users can pin a priority as their default emphasis (persists to
  // Settings); signed-out users get the picks without the control.
  canPersist: boolean;
}

// The funded-$0 insight strip (the mock's "All three run at $0 to you…"). Only
// shown when EVERY pick is funded at $0 to the user (the common case for a
// subscription like Claude Max) — the "trade-off is capability, not price"
// framing only holds when price is flat. Funding source is best-effort from the
// personalized your_cost string; omitted if the picks don't share one clean one.
function fundedZeroInsight(
  recs: PriorityRecommendation[],
): { source: string | null } | null {
  if (recs.length < 2) {
    return null;
  }
  const fundedRows = recs.map((r) =>
    (r.comparison_table ?? []).find(
      (row) =>
        row.funded === true &&
        typeof row.your_cost === "string" &&
        row.your_cost.includes("$0"),
    ),
  );
  if (fundedRows.some((f) => !f)) {
    return null;
  }
  const sources = new Set(
    fundedRows.map((f) => {
      const raw = typeof f!.your_cost === "string" ? f!.your_cost : "";
      const s = raw
        .replace(/^✓\s*/, "")
        .replace(/\$0/, "")
        .replace(/^[\s·\-–—]+/, "")
        .trim();
      return !s || s.length > 24 || s.includes("$") ? "" : s;
    }),
  );
  const source = sources.size === 1 ? [...sources][0] : null;
  return { source: source || null };
}

// The redesign renders the three priority picks as a single comparison matrix
// (Cost / Balanced / Quality as columns, shared attributes as rows) — replacing
// the three tall stacked cards. The matrix spans the full width; below it, the
// SELECTED pick's rationale sits beside its cost breakdown + the rating key.
// Stacking (rather than matrix-beside-detail) keeps the layout balanced no
// matter how long a rationale runs — a short matrix beside a tall rationale
// otherwise left a large empty column.
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
  const insight = fundedZeroInsight(data.recommendations);
  const three = data.recommendations.length === 3;

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-3 shadow-sm sm:p-4">
        <div className="flex items-baseline justify-between gap-3 px-1 pb-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            Your {three ? "three " : ""}picks
          </h2>
          <span className="text-xs text-brand-slate-400 dark:text-brand-slate-500">
            Select a pick to see why &amp; the full cost
          </span>
        </div>

        {insight ? (
          <div className="mb-3 flex items-center gap-2.5 rounded-md border border-brand-accent/30 bg-brand-accent/10 px-3 py-2 text-[13px] text-brand-slate-700 dark:text-brand-slate-200">
            <Sparkles className="h-4 w-4 flex-none text-brand-accent" aria-hidden />
            <span>
              All {three ? "three " : ""}picks run at{" "}
              <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                $0 to you
              </b>
              {insight.source ? ` on ${insight.source}` : ""} — the trade-off
              here is{" "}
              <b className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                capability &amp; effort
              </b>
              , not price.
            </span>
          </div>
        ) : null}

        {/* Compact comparison matrix (left) beside the selected pick's detail
            (right). The detail column is slightly wider so a long rationale
            wraps to fewer lines; the rating key fills the left column beneath
            the matrix so the two sides stay roughly balanced. */}
        <div className="grid gap-4 lg:grid-cols-[1.18fr_1fr] lg:items-start">
          <div className="flex flex-col gap-3">
            <TierMatrix
              recommendations={data.recommendations}
              selected={selected}
              primary={primary}
              onSelect={setSelected}
            />
            <RatingKey />
          </div>
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
