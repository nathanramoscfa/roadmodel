// web/components/TierDetail.tsx
"use client";

import type { PriorityRecommendation } from "@/lib/api";
import { WhyDisclosure } from "./WhyDisclosure";

// The rationale STRING (the fallback + the fold-in the edge assembles into
// settings.rationale). Structured sections, when present, come from
// rec.rationale_sections and take precedence inside WhyDisclosure.
function extractRationale(rec: PriorityRecommendation): string | null {
  const fromSettings = rec.settings?.rationale;
  if (typeof fromSettings === "string" && fromSettings.trim()) {
    return fromSettings;
  }
  const first = rec.comparison_table?.[0];
  if (first && typeof first.rationale === "string") {
    return first.rationale;
  }
  return null;
}

interface TierDetailProps {
  rec: PriorityRecommendation;
  // Signed-in users can pin the selected pick as their default emphasis.
  canPersist: boolean;
  persisting: boolean;
  // Whether the selected pick is already the pinned default.
  isDefault: boolean;
  onSetDefault: (priority: PriorityRecommendation["priority"]) => void;
}

// The selected pick's rationale panel ("Why this model?" + the pin control). The
// cost table renders separately (RecommendOutput's right column) so the two
// detail columns stay balanced regardless of how long the rationale runs.
export function TierDetail({
  rec,
  canPersist,
  persisting,
  isDefault,
  onSetDefault,
}: TierDetailProps) {
  const rationale = extractRationale(rec);
  const sections = rec.rationale_sections ?? null;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-50 dark:bg-brand-slate-900 p-4">
      <WhyDisclosure rationale={rationale} sections={sections} />

      {canPersist ? (
        isDefault ? (
          <p className="text-xs font-medium text-green-600 dark:text-green-400">
            ✓ Current default
          </p>
        ) : (
          <button
            type="button"
            disabled={persisting}
            onClick={() => onSetDefault(rec.priority)}
            className="self-start rounded-md border border-brand-slate-300 dark:border-brand-slate-600 px-3 py-1.5 text-xs font-semibold text-brand-slate-600 dark:text-brand-slate-300 hover:border-brand-accent hover:text-brand-accent disabled:opacity-50"
          >
            Set as default
          </button>
        )
      ) : null}
    </div>
  );
}
