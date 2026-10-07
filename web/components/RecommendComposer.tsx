// web/components/RecommendComposer.tsx
//
// Where a /recommend request is written: the task, any text files it
// carries, and the engine that will read it. The task grows with its text;
// one-click examples show what a useful task looks like; ⌘/Ctrl+Enter
// submits. File text is read in the browser and sent ahead of the typed task,
// clearly labelled as input to classify, never as instructions (#187). "Use
// your own API key" opens the key panel below the form (VisitorKeyPanel).
"use client";

import Link from "next/link";
import { KeyRound, Paperclip, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { EngineOption } from "@/lib/recommend-engines";
import type { VisitorKey } from "@/lib/use-visitor-key";
import { PROVIDER_LABEL } from "@/lib/visitor-key";
import { EnginePicker } from "./EnginePicker";
import { VisitorKeyPanel } from "./VisitorKeyPanel";

// Text files only for now (docs/file-input.md): documents (#210) and images
// (#211) are later phases and are skipped with a hint.
const TEXT_EXTENSIONS = [".txt", ".md", ".json"];
const MAX_ATTACHMENTS = 5;
// Mirrors the service input cap (#142, 50k chars) for files and for the task.
const MAX_CHARS = 50_000;

// Hardest first: each lands in a different row of the picks table, from
// long-context/high down to speed/low, so running them in order walks the
// scale from the strongest picks to the lightest.
export const EXAMPLES: { label: string; task: string }[] = [
  {
    label: "Audit a long contract",
    task: "Read our 400-page vendor contract and list every clause that limits our liability, with page references.",
  },
  {
    label: "Refactor a pipeline",
    task: "Refactor a 3,000-line Python data pipeline into typed modules with tests, keeping its behaviour identical.",
  },
  {
    label: "Inbox agent",
    task: "Run an agent that triages my inbox, drafts replies for me to approve, and books meetings through my calendar API.",
  },
  {
    label: "Plan a launch",
    task: "Plan a two-week launch for a mobile app: milestones, owners, dependencies and the risks to watch.",
  },
  {
    label: "Bulk-classify tickets",
    task: "Classify 10,000 support tickets by sentiment as cheaply as possible; accuracy still matters.",
  },
];

export interface Attachment {
  name: string;
  text: string;
}

function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("file read failed"));
    reader.readAsText(file);
  });
}

// The labelled block sent ahead of the typed task, capped at the input limit
// with a visible note.
export function attachmentsPrefix(attachments: Attachment[]): { text: string; truncated: boolean } {
  const joined = attachments.map((a) => `Attached file ${a.name}:\n${a.text}\n\n`).join("");
  if (joined.length <= MAX_CHARS) return { text: joined, truncated: false };
  return {
    text: joined.slice(0, MAX_CHARS) + "\n[Attached file content truncated at 50,000 characters.]\n\n",
    truncated: true,
  };
}

export function RecommendComposer({
  task,
  onTaskChange,
  attachments,
  onAttachmentsChange,
  engines,
  engine,
  onEngineChange,
  signedIn,
  pending,
  error,
  notice = null,
  visitor,
  keyOpen,
  onKeyOpenChange,
  onSubmit,
}: {
  task: string;
  onTaskChange: (task: string) => void;
  attachments: Attachment[];
  onAttachmentsChange: (attachments: Attachment[]) => void;
  engines: EngineOption[];
  engine: string;
  onEngineChange: (hint: string) => void;
  signedIn: boolean;
  pending: boolean;
  error: string | null;
  // A plain note in place of an error: what the visitor can do here.
  notice?: string | null;
  // The visitor's own key (held by RecommendWorkspace) and its panel.
  visitor: VisitorKey;
  keyOpen: boolean;
  onKeyOpenChange: (open: boolean) => void;
  onSubmit: () => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileNotice, setFileNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const { truncated } = attachmentsPrefix(attachments);
  const empty = !task.trim() && attachments.length === 0;

  // Grow with the text, between four lines and roughly a screenful.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 104), 360)}px`;
  }, [task]);

  async function addFiles(files: FileList | null) {
    if (!files) return;
    const incoming = Array.from(files);
    const isText = (name: string) => TEXT_EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext));
    const read = await Promise.all(
      incoming
        .filter((f) => isText(f.name))
        .map(async (f) => ({ name: f.name, text: (await readFileText(f)).slice(0, MAX_CHARS) })),
    );
    const skipped = incoming.filter((f) => !isText(f.name)).map((f) => f.name);
    onAttachmentsChange([...attachments, ...read].slice(0, MAX_ATTACHMENTS));
    setFileNotice(
      skipped.length > 0
        ? `Skipped ${skipped.join(", ")}: only text files (.txt, .md, .json) are supported for now.`
        : null,
    );
  }

  return (
    <div className="space-y-2">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!pending && !empty) onSubmit();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void addFiles(e.dataTransfer.files);
        }}
        className={
          "rounded-xl border bg-white shadow-sm transition dark:bg-brand-slate-800 " +
          (dragging
            ? "border-brand-accent ring-2 ring-brand-accent/30"
            : "border-brand-slate-200 focus-within:border-brand-accent/70 dark:border-brand-slate-700")
        }
        data-testid="recommend-composer"
      >
        <label htmlFor="task_description" className="sr-only">
          Task description
        </label>
        <textarea
          ref={area}
          id="task_description"
          name="task_description"
          value={task}
          maxLength={MAX_CHARS}
          disabled={pending}
          onChange={(e) => onTaskChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              if (!pending && !empty) onSubmit();
            }
          }}
          placeholder="Describe the task you want a model for: what it is, how big, and what matters most."
          className="block w-full resize-none rounded-t-xl border-0 bg-transparent px-4 pb-2 pt-3.5 text-[15px] leading-6 text-brand-slate-900 placeholder:text-brand-slate-400 focus:outline-none focus:ring-0 disabled:opacity-70 dark:text-brand-slate-50"
        />

        {(attachments.length > 0 || fileNotice || truncated) && (
          <div className="space-y-1.5 px-4 pb-2">
            {attachments.length > 0 && (
              <ul className="flex flex-wrap gap-1.5" aria-label="Attached files">
                {attachments.map((a, i) => (
                  <li
                    key={`${a.name}-${i}`}
                    className="inline-flex items-center gap-1 rounded-md border border-brand-slate-200 bg-brand-slate-50 py-0.5 pl-2 pr-1 text-xs text-brand-slate-700 dark:border-brand-slate-600 dark:bg-brand-slate-900 dark:text-brand-slate-200"
                  >
                    {a.name}
                    <button
                      type="button"
                      aria-label={`Remove ${a.name}`}
                      onClick={() => onAttachmentsChange(attachments.filter((_, j) => j !== i))}
                      className="rounded p-0.5 text-brand-slate-400 hover:text-brand-slate-700 dark:hover:text-brand-slate-100"
                    >
                      <X className="h-3 w-3" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {truncated && (
              <p className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
                The attached text is cut at 50,000 characters.
              </p>
            )}
            {fileNotice && (
              <p className="text-xs text-brand-slate-500 dark:text-brand-slate-400" role="status">
                {fileNotice}
              </p>
            )}
          </div>
        )}

        {empty && (
          <div className="flex flex-wrap items-center gap-1.5 px-4 pb-3" data-testid="examples">
            <span className="mr-0.5 text-xs font-medium text-brand-slate-500 dark:text-brand-slate-400">Try</span>
            {EXAMPLES.map((ex) => (
              <button
                key={ex.label}
                type="button"
                onClick={() => {
                  onTaskChange(ex.task);
                  area.current?.focus();
                }}
                className="rounded-full border border-brand-slate-200 bg-brand-slate-50 px-2.5 py-1 text-xs text-brand-slate-700 transition hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-600 dark:bg-brand-slate-900 dark:text-brand-slate-200"
              >
                {ex.label}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-brand-slate-100 px-3 py-2.5 dark:border-brand-slate-700/70">
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={pending || attachments.length >= MAX_ATTACHMENTS}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-brand-slate-600 transition hover:bg-brand-slate-100 disabled:opacity-50 dark:text-brand-slate-300 dark:hover:bg-brand-slate-700/60"
            title="Attach text files (.txt, .md, .json), or drop them on the box"
          >
            <Paperclip className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Attach</span>
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".txt,.md,.json"
            multiple
            className="hidden"
            onChange={(e) => {
              void addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <EnginePicker
            options={engines}
            value={engine}
            onChange={onEngineChange}
            signedIn={signedIn}
            disabled={pending}
          />
          <button
            type="button"
            onClick={() => onKeyOpenChange(!keyOpen)}
            aria-expanded={keyOpen}
            aria-controls="visitor-key-panel"
            className={
              "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm transition hover:bg-brand-slate-100 dark:hover:bg-brand-slate-700/60 " +
              (visitor.active && visitor.valid
                ? "font-semibold text-brand-accent"
                : "text-brand-slate-600 dark:text-brand-slate-300")
            }
            data-testid="visitor-key-toggle"
          >
            <KeyRound className="h-4 w-4" aria-hidden />
            <span>
              {visitor.active && visitor.valid
                ? `Your ${PROVIDER_LABEL[visitor.provider]} key`
                : "Use your own API key"}
            </span>
          </button>
          <span className="ml-auto hidden text-xs text-brand-slate-400 md:inline dark:text-brand-slate-500">
            {signedIn ? (
              <>
                Costs use your{" "}
                <Link href="/settings" className="font-medium text-brand-accent hover:underline">
                  subscriptions
                </Link>
              </>
            ) : (
              <>
                <Link href="/login" className="font-medium text-brand-accent hover:underline">
                  Sign in
                </Link>{" "}
                to price picks against your subscriptions
              </>
            )}
          </span>
          <button
            type="submit"
            disabled={pending || empty}
            className="ml-auto inline-flex items-center gap-2 rounded-lg bg-brand-accent px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-accent-hover disabled:cursor-not-allowed disabled:opacity-50 md:ml-0"
          >
            {pending ? "Recommending…" : "Recommend"}
            <kbd className="hidden rounded border border-white/30 px-1 text-[10px] font-medium text-white/80 sm:inline">
              ⌘↵
            </kbd>
          </button>
        </div>

        {error && (
          <p
            className="border-t border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
            role="alert"
          >
            {error}
          </p>
        )}
        {notice && (
          <p
            className="border-t border-brand-slate-100 px-4 py-2.5 text-sm text-brand-slate-600 dark:border-brand-slate-700/70 dark:text-brand-slate-300"
            role="status"
            data-testid="funding-notice"
          >
            {notice}
          </p>
        )}
      </form>
      {keyOpen && <VisitorKeyPanel visitor={visitor} disabled={pending} />}
    </div>
  );
}
