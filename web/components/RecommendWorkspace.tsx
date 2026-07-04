// web/components/RecommendWorkspace.tsx
"use client";

import { useEffect, useState } from "react";
import type { MultiRecommendResponse } from "@/lib/api";
import { PromptForm } from "./PromptForm";
import { PromptSummaryBar } from "./PromptSummaryBar";
import { RecommendOutput } from "./RecommendOutput";
import { RecommendOutputEmpty } from "./RecommendOutputEmpty";
import { RecommendReference } from "./RecommendReference";

export const RECOMMEND_PREFILL_KEY = "roadmodel:recommend-prefill";

interface PrefillPayload {
  task_description: string;
  recommendation: MultiRecommendResponse;
}

interface RecommendWorkspaceProps {
  // Signed-in users can pin a priority as their default emphasis (persists to
  // Settings); the server page supplies whether the visitor is signed in.
  canPersistBudget: boolean;
}

// The redesign is a single full-width column: the prompt (which collapses to a
// summary bar once a result lands), the comparison-matrix output, and the
// benchmarks/ratings reference. Full width lets the three picks render as a
// side-by-side comparison instead of three stacked cards.
export function RecommendWorkspace({
  canPersistBudget,
}: RecommendWorkspaceProps) {
  const [data, setData] = useState<MultiRecommendResponse | null>(null);
  const [initialTask, setInitialTask] = useState("");
  const [submittedTask, setSubmittedTask] = useState("");
  const [editing, setEditing] = useState(false);

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
        setSubmittedTask(parsed.task_description);
      }
      // Only accept a well-formed multi-pick payload (a stale single-pick
      // prefill is ignored rather than rendered broken).
      if (Array.isArray(parsed.recommendation?.recommendations)) {
        setData(parsed.recommendation);
      }
    } catch {
      sessionStorage.removeItem(RECOMMEND_PREFILL_KEY);
    }
  }, []);

  // Show the full form pre-submit (or while editing); collapse to the summary
  // bar once a result exists so the picks sit near the top of the viewport.
  const showForm = !data || editing;

  return (
    <div className="flex flex-col gap-3">
      {showForm ? (
        <PromptForm
          initialTask={initialTask}
          onSuccess={(recommendation, task) => {
            setData(recommendation);
            setSubmittedTask(task);
            setEditing(false);
          }}
        />
      ) : (
        <PromptSummaryBar
          task={submittedTask}
          onEdit={() => setEditing(true)}
        />
      )}

      {data ? (
        <RecommendOutput data={data} canPersist={canPersistBudget} />
      ) : (
        <>
          <RecommendOutputEmpty />
          {/* Pre-submit only: once picks render, the rating key inside the
              results (RatingKey) carries the scale + benchmarks, so the fuller
              reference card here would duplicate it. */}
          <RecommendReference />
        </>
      )}
    </div>
  );
}
