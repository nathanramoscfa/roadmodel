// web/components/RecommendWorkspace.tsx
//
// /recommend's interactive half. One request at a time moves through three
// states: composing (the task, its files, the engine), running (the engine at
// work, with its real elapsed time), and a result (the three picks, with a way
// to ask another engine the same task). The last few results stay in this
// browser (RecentRecommendations), so a reload or a comparison costs nothing.
"use client";

import { useEffect, useRef, useState } from "react";

import type { MultiRecommendResponse } from "@/lib/api";
import type { EngineOption } from "@/lib/recommend-engines";
import type { PicksData } from "@/lib/recommend-picks";
import { saveEnginePref } from "@/lib/recommend-prefs";
import { attachmentsPrefix, RecommendComposer, type Attachment } from "./RecommendComposer";
import { RecommendIntro } from "./RecommendIntro";
import { RecommendResult } from "./RecommendResult";
import { RecommendRunning } from "./RecommendRunning";
import { loadRecent, RecentRecommendations, saveRecent, type RecentRun } from "./RecentRecommendations";

interface Running {
  startedAt: number;
  engine: EngineOption;
}

function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

// What a visitor the operator lane does not fund reads in place of an error
// (402 funding_required, lib/funding-lane.ts). Phase 4.11 Steps 2 and 5 add
// the key entry and the Quick pick form beside it.
export const FUNDING_NOTICE =
  "Recommend runs on roadmodel's account for invited members. Your own API key will work here soon.";

// The user-facing message for a failed request, by status and error code.
function errorMessage(status: number, body: { error?: string; engine?: string }, engines: EngineOption[]): string {
  if (status === 403 && body.error === "engine_not_evaluated") {
    const e = engines.find((o) => o.hint === body.engine);
    return `${e?.name ?? "That engine"} has not passed the engine evaluation yet. Choose another engine.`;
  }
  if (status === 403 && body.error === "engine_not_allowed") {
    const e = engines.find((o) => o.hint === body.engine);
    const who = e?.access === "invited" ? "invited members" : "the operator";
    return `${e?.name ?? "That engine"} is open to ${who}. Choose another engine.`;
  }
  if (status === 429 && body.error === "burst_dropped") {
    return "Slow down — too many requests in a short window. Try again in a minute.";
  }
  if (status === 429) {
    return "You've hit the daily recommendation limit. Try again tomorrow.";
  }
  if (status === 503 && body.error === "daily_cost_cap") {
    return "Recommendations are paused until midnight UTC: today's spending cap has been reached.";
  }
  if (status === 400) {
    return body.error === "unknown_engine"
      ? "That engine is no longer offered. Choose another engine."
      : "Write a task (or attach a file) of up to 50,000 characters.";
  }
  return "The recommender is unavailable — try again in a moment.";
}

export function RecommendWorkspace({
  engines,
  initialEngine,
  picks,
  signedIn,
  modelCount,
  measuredCount,
}: {
  engines: EngineOption[];
  initialEngine: string;
  picks: PicksData;
  signedIn: boolean;
  modelCount: number;
  measuredCount: number;
}) {
  const [task, setTask] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [engine, setEngine] = useState(initialEngine);
  const [rerunEngine, setRerunEngine] = useState(initialEngine);
  const [running, setRunning] = useState<Running | null>(null);
  const [result, setResult] = useState<RecentRun | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentRun[]>([]);
  const top = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setRecent(loadRecent());
  }, []);

  function chooseEngine(hint: string) {
    setEngine(hint);
    setRerunEngine(hint);
    saveEnginePref(hint);
  }

  async function run(taskText: string, shownTask: string, engineHint: string) {
    const option = engines.find((o) => o.hint === engineHint) ?? engines[0];
    setError(null);
    setNotice(null);
    setRunning({ startedAt: Date.now(), engine: option });
    try {
      const res = await fetch("/api/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_description: taskText, engine: engineHint }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string; engine?: string };
        if (res.status === 402 && body.error === "funding_required") {
          setNotice(FUNDING_NOTICE);
          return;
        }
        setError(errorMessage(res.status, body, engines));
        return;
      }
      const data = (await res.json()) as MultiRecommendResponse;
      const entry: RecentRun = { id: newId(), at: Date.now(), task: shownTask, data };
      setResult(entry);
      setEditing(false);
      setRecent((prev) => saveRecent([entry, ...prev]));
      top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch {
      setError("The recommender is unavailable — try again in a moment.");
    } finally {
      setRunning(null);
    }
  }

  function submit() {
    const prefix = attachmentsPrefix(attachments).text;
    const typed = task.trim();
    const shown = typed || `Attached: ${attachments.map((a) => a.name).join(", ")}`;
    void run(`${prefix}${typed}`, shown, engine);
  }

  function rerun() {
    if (!result) return;
    const prefix = attachmentsPrefix(attachments).text;
    const typed = task.trim() || result.task;
    void run(`${prefix}${typed}`, result.task, rerunEngine);
  }

  const showComposer = !result || editing;

  return (
    <div ref={top} className="scroll-mt-20 space-y-5">
      {showComposer && (
        <RecommendComposer
          task={task}
          onTaskChange={setTask}
          attachments={attachments}
          onAttachmentsChange={setAttachments}
          engines={engines}
          engine={engine}
          onEngineChange={chooseEngine}
          signedIn={signedIn}
          pending={running !== null}
          error={result ? null : error}
          notice={result ? null : notice}
          onSubmit={submit}
        />
      )}

      {running ? (
        <RecommendRunning
          engineName={running.engine.name}
          typicalS={running.engine.eval?.p50_latency_s ?? null}
          startedAt={running.startedAt}
        />
      ) : result && !editing ? (
        <>
          {error && (
            <p
              className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
              role="alert"
            >
              {error}
            </p>
          )}
          {notice && (
            <p
              className="rounded-lg border border-brand-slate-200 px-4 py-2.5 text-sm text-brand-slate-600 dark:border-brand-slate-700 dark:text-brand-slate-300"
              role="status"
              data-testid="funding-notice"
            >
              {notice}
            </p>
          )}
          <RecommendResult
            data={result.data}
            task={result.task}
            picks={picks}
            engines={engines}
            rerunEngine={rerunEngine}
            onRerunEngineChange={(hint) => {
              setRerunEngine(hint);
              saveEnginePref(hint);
            }}
            onRerun={rerun}
            onEdit={() => {
              setTask(result.task);
              setEditing(true);
            }}
            onNew={() => {
              setTask("");
              setAttachments([]);
              setResult(null);
              setEditing(false);
              setError(null);
              setNotice(null);
            }}
            canPersist={signedIn}
            signedIn={signedIn}
            pending={running !== null}
          />
        </>
      ) : !result ? (
        <RecommendIntro modelCount={modelCount} measuredCount={measuredCount} />
      ) : null}

      <RecentRecommendations
        runs={recent}
        activeId={result?.id ?? null}
        onOpen={(r) => {
          setResult(r);
          setEditing(false);
          setError(null);
          top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
        }}
        onClear={() => setRecent(saveRecent([]))}
      />
    </div>
  );
}
