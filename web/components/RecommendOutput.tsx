// web/components/RecommendOutput.tsx
"use client";

import { useEffect, useState } from "react";
import type { MultiRecommendResponse, PriorityRecommendation } from "@/lib/api";
import { FreeTierLabel } from "./FreeTierLabel";
import { PriorityCard } from "./PriorityCard";

interface RecommendOutputProps {
  data: MultiRecommendResponse;
  // Signed-in users can pin a priority as their default emphasis (persists to
  // Settings); signed-out users get the three picks without the control.
  canPersist: boolean;
}

export function RecommendOutput({ data, canPersist }: RecommendOutputProps) {
  // Which priority leads (ring + "Default" badge). Seeded from the server's
  // saved preference (data.primary) and re-seeded whenever a new result lands;
  // a "Set as default" click updates it optimistically and persists in the
  // background so Settings reflects it.
  const [primary, setPrimary] = useState(data.primary);
  const [persisting, setPersisting] = useState(false);

  useEffect(() => {
    setPrimary(data.primary);
  }, [data]);

  function handleSetDefault(priority: PriorityRecommendation["priority"]): void {
    setPrimary(priority);
    if (!canPersist) {
      return;
    }
    // Fire-and-forget: the highlight already updated optimistically, so a failed
    // sync never blocks the UI. Only signed-in users have a profile to write to.
    setPersisting(true);
    void fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ budget_priority: priority }),
    })
      .catch(() => {})
      .finally(() => setPersisting(false));
  }

  // recommendations arrive ordered Cost -> Balanced -> Quality (the edge fans
  // out in BUDGET_PRIORITY_IDS order); render them in that order.
  const tierSource =
    data.recommendations.find((r) => r.priority === primary) ??
    data.recommendations[0];

  return (
    <div className="flex flex-col gap-5">
      {data.recommendations.map((rec) => (
        <PriorityCard
          key={rec.priority}
          data={rec}
          isPrimary={rec.priority === primary}
          canPersist={canPersist}
          persisting={persisting}
          onSetDefault={handleSetDefault}
        />
      ))}
      {tierSource ? (
        <FreeTierLabel
          surface="recommend"
          tier={tierSource.tier}
          engine={tierSource.engine}
        />
      ) : null}
    </div>
  );
}
