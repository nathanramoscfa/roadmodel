// web/components/RecommendWorkspace.tsx
"use client";

import { useEffect, useState } from "react";
import type { RecommendResponse } from "@/lib/api";
import { PromptForm } from "./PromptForm";
import { RecommendOutput } from "./RecommendOutput";
import { RecommendOutputEmpty } from "./RecommendOutputEmpty";

export const RECOMMEND_PREFILL_KEY = "roadmodel:recommend-prefill";

interface PrefillPayload {
  task_description: string;
  recommendation: RecommendResponse;
}

export function RecommendWorkspace() {
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

  return (
    <div className="contents">
      <PromptForm
        initialTask={initialTask}
        onSuccess={setData}
      />
      {data ? (
        <RecommendOutput data={data} />
      ) : (
        <RecommendOutputEmpty />
      )}
    </div>
  );
}
