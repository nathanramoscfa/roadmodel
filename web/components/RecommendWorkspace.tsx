// web/components/RecommendWorkspace.tsx
"use client";

import { useEffect, useState } from "react";
import type { RecommendResponse } from "@/lib/api";
import type { BudgetPriority } from "@/lib/profile";
import { PromptForm } from "./PromptForm";
import { RecommendOutput } from "./RecommendOutput";
import { RecommendOutputEmpty } from "./RecommendOutputEmpty";
import { RecommendReference } from "./RecommendReference";

export const RECOMMEND_PREFILL_KEY = "roadmodel:recommend-prefill";

interface PrefillPayload {
  task_description: string;
  recommendation: RecommendResponse;
}

interface RecommendWorkspaceProps {
  // The signed-in user's current budget priority (or the default for anon), so
  // the inline control opens on the right choice; canPersistBudget gates the
  // Settings sync (signed-in only). Both supplied by the server page.
  initialBudgetPriority: BudgetPriority;
  canPersistBudget: boolean;
}

export function RecommendWorkspace({
  initialBudgetPriority,
  canPersistBudget,
}: RecommendWorkspaceProps) {
  const [data, setData] = useState<RecommendResponse | null>(null);
  const [initialTask, setInitialTask] = useState("");

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(RECOMMEND_PREFILL_KEY);
      if (!raw) {
        return;
      }
      sessionStorage.removeItem(RECOMMEND_PREFILL_KEY);
      const parsed = JSON.parse(raw) as PrefillPayload;
      if (parsed.task_description) {
        setInitialTask(parsed.task_description);
      }
      if (parsed.recommendation) {
        setData(parsed.recommendation);
      }
    } catch {
      sessionStorage.removeItem(RECOMMEND_PREFILL_KEY);
    }
  }, []);

  // Two grid columns (the parent page is lg:grid-cols-2): the prompt form plus a
  // benchmarks/ratings reference on the left (the reference fills the space under
  // Submit), and the recommendation output on the right.
  return (
    <div className="contents">
      <div className="flex flex-col gap-8">
        <PromptForm
          initialTask={initialTask}
          initialBudgetPriority={initialBudgetPriority}
          canPersistBudget={canPersistBudget}
          onSuccess={setData}
        />
        <RecommendReference />
      </div>
      {data ? (
        <RecommendOutput data={data} />
      ) : (
        <RecommendOutputEmpty />
      )}
    </div>
  );
}
