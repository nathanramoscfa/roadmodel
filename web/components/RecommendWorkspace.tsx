// web/components/RecommendWorkspace.tsx
//
// /recommend's interactive half. One request at a time moves through three
// states: composing (the task, its files, the engine), running (the engine at
// work, with its real elapsed time), and a result (the three picks, with a way
// to ask another engine the same task). The last few results stay in this
// browser (RecentRecommendations), so a reload or a comparison costs nothing.
//
// A visitor may pay with their own API key (VisitorKeyPanel). The key lives in
// one React state holder here (lib/use-visitor-key.ts), shared by the composer
// and "Run again", and leaves the page only as a request header. While a key
// is in use the engine menu is that provider's engines, priced to the key.
//
// A visitor outside the invite list who holds no key chooses a lane first
// (LaneChooser): Quick pick (three picks computed from published benchmarks
// and prices, /api/recommend/keyless), their own API key or OpenRouter (the
// free-text flow below), or roadmodel's MCP server in their own agent.
"use client";

import { KeyRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { MultiRecommendResponse } from "@/lib/api";
import type { KeylessAgreement, KeylessResponse, KeylessTask } from "@/lib/keyless";
import type { EngineOption } from "@/lib/recommend-engines";
import { takeVisitorKeyHandoff, useVisitorKey } from "@/lib/use-visitor-key";
import { KEY_PREFIX_HINT, PROVIDER_LABEL, type VisitorProvider } from "@/lib/visitor-key";
import type { PicksData } from "@/lib/recommend-picks";
import { saveEnginePref } from "@/lib/recommend-prefs";
import { LaneChooser, type Lane, type LaneChoice } from "./LaneChooser";
import { OwnAgentPanel } from "./OwnAgentPanel";
import { KeylessResult, QuickPickForm } from "./QuickPick";
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
// (402 funding_required, lib/funding-lane.ts), with the key panel opened
// beside it. Phase 4.11 Step 5 adds the Quick pick form.
export const FUNDING_NOTICE =
  "Recommend runs on roadmodel's account for invited members. Add your own API key below to run it on yours.";

// The user-facing message for a failed request, by status and error code.
// `keyProvider` is the provider of the visitor's key, when one paid.
function errorMessage(
  status: number,
  body: { error?: string; engine?: string },
  engines: EngineOption[],
  keyProvider: VisitorProvider | null,
): string {
  const provider = keyProvider ? PROVIDER_LABEL[keyProvider] : "Your provider";
  if (body.error === "visitor_key_rejected") {
    return "Your provider declined this key. Check it in your provider's console and paste it again.";
  }
  if (body.error === "visitor_quota") {
    return `${provider} reports this key's rate limit or quota is used up. Raise it in your provider's console, or try again later.`;
  }
  if (body.error === "too_many_rejected_keys") {
    return "Several keys from this browser were declined today, so keys are paused here until tomorrow.";
  }
  if (body.error === "visitor_key_malformed") {
    return keyProvider
      ? `${provider} API keys begin with ${KEY_PREFIX_HINT[keyProvider]}. Paste the whole key.`
      : "Paste the whole API key for the provider you chose.";
  }
  if (keyProvider && body.error === "provider_error") {
    return `${provider} returned no recommendation this time. Try again in a moment.`;
  }
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

// The user-facing message for a failed Quick pick.
function keylessErrorMessage(status: number, error: string | undefined): string {
  if (status === 429 && error === "burst_dropped") {
    return "Slow down — too many Quick picks in a short window. Try again in a minute.";
  }
  if (status === 429) return "You've reached today's Quick pick limit. Try again tomorrow.";
  if (status === 422 && error === "no_frontier") {
    return "Quick pick draws from the benchmarked models your Settings reach. Widen your Settings to bring more of them in.";
  }
  if (status === 400) return "Choose a task type and a difficulty.";
  return "Quick pick is unavailable — try again in a moment.";
}

const QUICK_DEFAULT: KeylessTask = { category: "coding", complexity: "medium", novel: false, budget_priority: "balanced" };

// The engine a visitor's key opens on: its provider's default.
function visitorDefaultHint(options: EngineOption[]): string {
  return (options.find((o) => o.isDefault) ?? options[0])?.hint ?? "";
}

export function RecommendWorkspace({
  engines,
  visitorEngines,
  initialEngine,
  picks,
  signedIn,
  modelCount,
  measuredCount,
  keylessViewer,
  agreement,
}: {
  engines: EngineOption[];
  // The menu for a visitor's own key, by its provider (visitorMenuFor).
  visitorEngines: Record<VisitorProvider, EngineOption[]>;
  initialEngine: string;
  picks: PicksData;
  signedIn: boolean;
  modelCount: number;
  measuredCount: number;
  // Outside the invite list: the operator's account answers none of this
  // viewer's free-text requests, so the page offers the lanes first.
  keylessViewer: boolean;
  // The keyless lane's measured agreement (lib/keyless-eval.ts).
  agreement: KeylessAgreement;
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
  const visitor = useVisitorKey();
  const [keyOpen, setKeyOpen] = useState(false);
  const [visitorEngine, setVisitorEngine] = useState(() => visitorDefaultHint(visitorEngines.openai));
  // A key in use: the menu, the chosen engine and "Run again" are its own.
  const keyed = visitor.active && visitor.valid;
  // The lane chooser, for a keyless viewer holding no key; Quick pick first.
  const [lane, setLane] = useState<Lane>("quick");
  const showChooser = keylessViewer && !keyed;
  const activeLane: Lane = showChooser ? lane : "key";
  const [quickTask, setQuickTask] = useState<KeylessTask>(QUICK_DEFAULT);
  const [quickResult, setQuickResult] = useState<KeylessResponse | null>(null);
  const [quickPending, setQuickPending] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);
  const menu = keyed ? visitorEngines[visitor.provider] : engines;
  const composerEngine = keyed ? visitorEngine : engine;
  const rerunHint = keyed ? visitorEngine : rerunEngine;

  // A new provider opens on its own default engine.
  useEffect(() => {
    setVisitorEngine(visitorDefaultHint(visitorEngines[visitor.provider]));
  }, [visitor.provider, visitorEngines]);

  useEffect(() => {
    setRecent(loadRecent());
  }, []);

  // A key "Connect OpenRouter" just returned (app/recommend/openrouter): it
  // pays from here on, and the panel opens to say so.
  const { setProvider: setKeyProvider, setKey } = visitor;
  useEffect(() => {
    const connected = takeVisitorKeyHandoff();
    if (!connected) return;
    setKeyProvider(connected.provider);
    setKey(connected.key);
    setKeyOpen(true);
  }, [setKeyProvider, setKey]);

  function chooseLane(choice: LaneChoice) {
    if (choice === "key" || choice === "openrouter") {
      if (choice === "openrouter") setKeyProvider("openrouter");
      else if (visitor.provider === "openrouter") setKeyProvider("openai");
      setLane("key");
      setKeyOpen(true);
      return;
    }
    setLane(choice);
  }

  async function runQuick(t: KeylessTask) {
    setQuickTask(t);
    setQuickError(null);
    setQuickPending(true);
    try {
      const res = await fetch("/api/recommend/keyless", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(t),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        setQuickError(keylessErrorMessage(res.status, body.error));
        return;
      }
      setQuickResult((await res.json()) as KeylessResponse);
      top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch {
      setQuickError("Quick pick is unavailable — try again in a moment.");
    } finally {
      setQuickPending(false);
    }
  }

  function chooseEngine(hint: string) {
    // A key's engine is chosen for this page only; the preference cookie keeps
    // the engine for roadmodel's account.
    if (keyed) {
      setVisitorEngine(hint);
      return;
    }
    setEngine(hint);
    setRerunEngine(hint);
    saveEnginePref(hint);
  }

  async function run(taskText: string, shownTask: string, engineHint: string) {
    if (visitor.active && !visitor.valid) {
      setError(errorMessage(400, { error: "visitor_key_malformed" }, menu, visitor.provider));
      setKeyOpen(true);
      return;
    }
    const option = menu.find((o) => o.hint === engineHint) ?? menu[0];
    const keyProvider = keyed ? visitor.provider : null;
    setError(null);
    setNotice(null);
    setRunning({ startedAt: Date.now(), engine: option });
    try {
      const res = await fetch("/api/recommend", {
        method: "POST",
        // The key, when one pays, rides only in its header.
        headers: { "Content-Type": "application/json", ...visitor.headersFor() },
        body: JSON.stringify({ task_description: taskText, engine: engineHint }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string; engine?: string };
        if (res.status === 402 && body.error === "funding_required") {
          setNotice(FUNDING_NOTICE);
          setKeyOpen(true);
          return;
        }
        setError(errorMessage(res.status, body, menu, keyProvider));
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
    void run(`${prefix}${typed}`, shown, composerEngine);
  }

  function rerun() {
    if (!result) return;
    const prefix = attachmentsPrefix(attachments).text;
    const typed = task.trim() || result.task;
    void run(`${prefix}${typed}`, result.task, rerunHint);
  }

  const showComposer = !result || editing;

  if (activeLane !== "key") {
    return (
      <div ref={top} className="scroll-mt-20 space-y-5">
        <LaneChooser lane={activeLane} openRouter={false} onChoose={chooseLane} />
        {activeLane === "agent" ? (
          <OwnAgentPanel />
        ) : quickResult ? (
          <KeylessResult
            data={quickResult}
            agreement={agreement}
            onChange={() => setQuickResult(null)}
            onDescribe={() => chooseLane("key")}
          />
        ) : (
          <QuickPickForm initial={quickTask} pending={quickPending} error={quickError} onSubmit={(t) => void runQuick(t)} />
        )}
        {/* Past free-text results open in the lane that wrote them. */}
        <RecentRecommendations
          runs={recent}
          activeId={null}
          onOpen={(r) => {
            setLane("key");
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

  return (
    <div ref={top} className="scroll-mt-20 space-y-5">
      {showChooser && (
        <LaneChooser lane="key" openRouter={visitor.provider === "openrouter"} onChoose={chooseLane} />
      )}
      {showComposer && (
        <RecommendComposer
          task={task}
          onTaskChange={setTask}
          attachments={attachments}
          onAttachmentsChange={setAttachments}
          engines={menu}
          engine={composerEngine}
          onEngineChange={chooseEngine}
          signedIn={signedIn}
          pending={running !== null}
          error={result ? null : error}
          notice={result ? null : notice}
          visitor={visitor}
          keyOpen={keyOpen}
          onKeyOpenChange={setKeyOpen}
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
          {visitor.active && (
            <p
              className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-brand-slate-600 dark:text-brand-slate-300"
              data-testid="visitor-key-status"
            >
              <KeyRound className="h-4 w-4 flex-none text-brand-accent" aria-hidden />
              <span>
                &ldquo;Run again&rdquo; runs on your {PROVIDER_LABEL[visitor.provider]} key, held in this tab only.
              </span>
              <button
                type="button"
                onClick={visitor.forget}
                className="font-semibold text-brand-accent hover:underline"
                data-testid="visitor-key-status-forget"
              >
                Forget key
              </button>
            </p>
          )}
          <RecommendResult
            data={result.data}
            task={result.task}
            picks={picks}
            engines={menu}
            rerunEngine={rerunHint}
            onRerunEngineChange={(hint) => {
              if (keyed) {
                setVisitorEngine(hint);
                return;
              }
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
