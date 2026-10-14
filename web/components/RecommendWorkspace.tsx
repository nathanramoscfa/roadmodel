// web/components/RecommendWorkspace.tsx
//
// /recommend's interactive half. One request at a time moves through three
// states: composing (the task, its files, the engine), running (the engine at
// work, with its real elapsed time), and a result (the three picks, with a way
// to ask another engine the same task). Every result is saved in this browser
// and nowhere else (SavedRecommendations), so a reload, a comparison or a
// return visit costs nothing.
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
import { KeylessResult, QuickPickForm, quickPickSummary } from "./QuickPick";
import { attachmentsPrefix, RecommendComposer, type Attachment } from "./RecommendComposer";
import { RecommendIntro } from "./RecommendIntro";
import { RecommendResult } from "./RecommendResult";
import { RecommendRunning } from "./RecommendRunning";
import { SavedRecommendations } from "./SavedRecommendations";
import type { SavedRun } from "@/lib/saved-recommendations";
import { onSavedMessage } from "@/lib/saved-store";
import { useSavedRecommendations } from "@/lib/use-saved-recommendations";
import { useRouter } from "next/navigation";

interface Running {
  startedAt: number;
  engine: EngineOption;
}

type EngineRun = Extract<SavedRun, { kind: "engine" }>;
type QuickRun = Extract<SavedRun, { kind: "quick" }>;

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
  owner,
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
  owner: string;
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
  const [result, setResult] = useState<EngineRun | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const saved = useSavedRecommendations(owner);
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
  const [quickResult, setQuickResult] = useState<QuickRun | null>(null);
  const [quickPending, setQuickPending] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);
  const menu = keyed ? visitorEngines[visitor.provider] : engines;
  const composerEngine = keyed ? visitorEngine : engine;
  const rerunHint = keyed ? visitorEngine : rerunEngine;

  // A new provider opens on its own default engine.
  useEffect(() => {
    setVisitorEngine(visitorDefaultHint(visitorEngines[visitor.provider]));
  }, [visitor.provider, visitorEngines]);

  const generation = useRef(0);
  const previousOwner = useRef(owner);
  const activeRequests = useRef(new Set<AbortController>());
  const router = useRouter();
  const { forget } = visitor;
  useEffect(() => {
    const pending = activeRequests.current;
    const invalidate = () => { generation.current++; };
    const reset = () => {
      invalidate();
      pending.forEach((controller) => controller.abort());
      pending.clear();
      setResult(null); setTask(""); setAttachments([]);
      setQuickResult(null); setRunning(null); setQuickPending(false);
      setError(null); setQuickError(null); setNotice(null); forget();
    };
    if (previousOwner.current !== owner) reset();
    previousOwner.current = owner;
    // Another tab signed out: drop what this one shows, pending answers
    // included, and reload as signed out.
    const off = onSavedMessage((message) => {
      if (message.type !== "signout") return;
      reset();
      router.refresh();
    });
    return () => {
      invalidate();
      pending.forEach((controller) => controller.abort());
      pending.clear();
      off();
    };
  }, [owner, router, forget]);

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
    const current = generation.current;
    const controller = new AbortController();
    activeRequests.current.add(controller);
    setQuickTask(t);
    setQuickError(null);
    setQuickPending(true);
    try {
      const res = await fetch("/api/recommend/keyless", {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(t),
      });
      if (current !== generation.current) return;
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        if (current !== generation.current) return;
        setQuickError(keylessErrorMessage(res.status, body.error));
        return;
      }
      const answer = (await res.json()) as KeylessResponse;
      if (current !== generation.current) return;
      const entry: QuickRun = { kind: "quick", id: newId(), at: Date.now(), task: quickPickSummary(answer.task), data: answer };
      setQuickResult(entry);
      saved.save(entry);
      top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch {
      if (current !== generation.current) return;
      setQuickError("Quick pick is unavailable — try again in a moment.");
    } finally {
      activeRequests.current.delete(controller);
      if (current === generation.current) setQuickPending(false);
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
    const current = generation.current;
    const controller = new AbortController();
    activeRequests.current.add(controller);
    const option = menu.find((o) => o.hint === engineHint) ?? menu[0];
    const keyProvider = keyed ? visitor.provider : null;
    setError(null);
    setNotice(null);
    setRunning({ startedAt: Date.now(), engine: option });
    try {
      const res = await fetch("/api/recommend", {
        method: "POST",
        signal: controller.signal,
        // The key, when one pays, rides only in its header.
        headers: { "Content-Type": "application/json", ...visitor.headersFor() },
        body: JSON.stringify({ task_description: taskText, engine: engineHint }),
      });
      if (current !== generation.current) return;
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string; engine?: string };
        if (current !== generation.current) return;
        if (res.status === 402 && body.error === "funding_required") {
          setNotice(FUNDING_NOTICE);
          setKeyOpen(true);
          return;
        }
        setError(errorMessage(res.status, body, menu, keyProvider));
        return;
      }
      const data = (await res.json()) as MultiRecommendResponse;
      if (current !== generation.current) return;
      const entry: EngineRun = { kind: "engine", id: newId(), at: Date.now(), task: shownTask, data };
      setResult(entry);
      setQuickResult(null);
      setEditing(false);
      saved.save(entry);
      top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch {
      if (current !== generation.current) return;
      setError("The recommender is unavailable — try again in a moment.");
    } finally {
      activeRequests.current.delete(controller);
      if (current === generation.current) setRunning(null);
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

  // A saved entry opens in the lane that made it, without a new request.
  function openSaved(run: SavedRun) {
    setEditing(false);
    setError(null);
    if (run.kind === "quick") {
      setResult(null);
      setQuickResult(run);
      setLane("quick");
    } else {
      setQuickResult(null);
      setResult(run);
      setLane("key");
    }
    top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  const savedList = (activeId: string | null) => (
    <SavedRecommendations
      runs={saved.runs}
      activeId={activeId}
      status={saved.status}
      onOpen={openSaved}
      onDelete={saved.remove}
      onClear={saved.clear}
      onExport={saved.exportAll}
      onImport={(file) => void saved.importFile(file)}
    />
  );

  if (activeLane !== "key") {
    return (
      <div ref={top} className="scroll-mt-20 space-y-5">
        <LaneChooser lane={activeLane} openRouter={false} onChoose={chooseLane} />
        {activeLane === "agent" ? (
          <OwnAgentPanel />
        ) : quickResult ? (
          <KeylessResult
            data={quickResult.data}
            agreement={agreement}
            onChange={() => setQuickResult(null)}
            onDescribe={() => chooseLane("key")}
          />
        ) : (
          <QuickPickForm initial={quickTask} pending={quickPending} error={quickError} onSubmit={(t) => void runQuick(t)} />
        )}
        {savedList(activeLane === "quick" ? (quickResult?.id ?? null) : null)}
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
      ) : quickResult && !result ? (
        // A saved Quick pick, opened where there is no Quick pick lane.
        <KeylessResult
          data={quickResult.data}
          agreement={agreement}
          onChange={() => setQuickResult(null)}
          onDescribe={() => setQuickResult(null)}
        />
      ) : !result ? (
        <RecommendIntro modelCount={modelCount} measuredCount={measuredCount} />
      ) : null}

      {savedList(result?.id ?? quickResult?.id ?? null)}
    </div>
  );
}
