// web/components/PromptForm.tsx
"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";
import type { RecommendResponse } from "@/lib/api";

// Phase A of the file-input feature (docs/file-input.md): text files only.
// Their contents are read client-side and prepended to the task. Documents
// (.pdf/.docx/.xlsx, #210) and images (.png/.jpg, #211) are later phases —
// dropped now, they're skipped with a hint.
const TEXT_EXTENSIONS = [".txt", ".md", ".json"];
const MAX_ATTACHMENTS = 5;
// Per-file and total caps mirror the service input cap (#142, 50k chars). A
// file's text is the TASK TO CLASSIFY, never instructions (the #187 hardening),
// so it is prepended as plainly-labelled input, not interpolated as a command.
const PER_FILE_CHARS = 50_000;
const MAX_TOTAL_CHARS = 50_000;

interface Attachment {
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

// Build the delimited prefix sent ahead of the typed prompt. Capped to
// MAX_TOTAL_CHARS with a visible truncation note when exceeded.
function buildAttachmentsText(attachments: Attachment[]): {
  text: string;
  truncated: boolean;
} {
  const joined = attachments
    .map((a) => `Attached file ${a.name}:\n${a.text}\n\n`)
    .join("");
  if (joined.length <= MAX_TOTAL_CHARS) {
    return { text: joined, truncated: false };
  }
  return {
    text:
      joined.slice(0, MAX_TOTAL_CHARS) +
      "\n[Attached file content truncated at 50,000 characters.]\n\n",
    truncated: true,
  };
}

interface RecommendActionState {
  data?: RecommendResponse;
  error?: string;
}

interface PromptFormProps {
  initialTask?: string;
  onSuccess: (data: RecommendResponse) => void;
}

async function submitRecommend(
  _prev: RecommendActionState,
  formData: FormData,
): Promise<RecommendActionState> {
  const task = String(formData.get("task_description") ?? "").trim();
  // Text from any attached files is prepended (clearly delimited) to the typed
  // prompt — see PromptForm's hidden `attachments_text` field. It is task INPUT
  // to classify, never instructions (#187).
  const attachments = String(formData.get("attachments_text") ?? "");
  if (!task && !attachments) {
    return { error: "Input a prompt or attach a file before submitting." };
  }
  const taskDescription = attachments ? `${attachments}${task}` : task;

  // Subscriptions + budget priority come from the signed-in user's profile
  // (Settings), which the /api/recommend route reads server-side — so the
  // request only carries the prompt. (The old inline "Your context" inputs were
  // dead: the route already overrode them with the profile.)
  const res = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_description: taskDescription }),
  });

  if (!res.ok) {
    if (res.status === 502) {
      return {
        error:
          "The recommender is unavailable — try again in a moment.",
      };
    }
    const body = (await res.json().catch(() => ({}))) as {
      error?: string;
      retry_after?: number;
    };
    if (res.status === 429 && body.error === "burst_dropped") {
      return {
        error:
          "Slow down — too many requests in a short window. Try again in a minute.",
      };
    }
    if (res.status === 429 && body.error === "rate_limited") {
      return {
        error:
          "You've hit the daily recommendation limit. Try again tomorrow.",
      };
    }
    return {
      error: body.error ?? "Something went wrong. Please try again.",
    };
  }

  const data = (await res.json()) as RecommendResponse;
  return { data };
}

export function PromptForm({ initialTask = "", onSuccess }: PromptFormProps) {
  const [task, setTask] = useState(initialTask);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [fileNotice, setFileNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [state, formAction, pending] = useActionState(
    submitRecommend,
    {},
  );

  useEffect(() => {
    if (initialTask) {
      setTask(initialTask);
    }
  }, [initialTask]);

  useEffect(() => {
    if (state.data) {
      onSuccess(state.data);
    }
  }, [state.data, onSuccess]);

  async function handleFilesSelected(files: FileList | null) {
    if (!files) {
      return;
    }
    const incoming = Array.from(files);
    const isText = (name: string) =>
      TEXT_EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext));
    const textFiles = incoming.filter((f) => isText(f.name));
    const skipped = incoming.filter((f) => !isText(f.name)).map((f) => f.name);

    const read = await Promise.all(
      textFiles.map(async (f) => ({
        name: f.name,
        text: (await readFileText(f)).slice(0, PER_FILE_CHARS),
      })),
    );
    setAttachments((prev) => [...prev, ...read].slice(0, MAX_ATTACHMENTS));
    setFileNotice(
      skipped.length > 0
        ? `Skipped ${skipped.join(", ")} — only text files (.txt, .md, .json) are supported for now.`
        : null,
    );
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    handleFilesSelected(event.dataTransfer.files);
  }

  const { text: attachmentsText, truncated } = buildAttachmentsText(attachments);

  return (
    <div className="flex flex-col gap-6">
      <form action={formAction} className="flex flex-col gap-4">
        {/* File text is prepended to the typed prompt server-side in
            submitRecommend; this hidden field carries it into the form action. */}
        <input type="hidden" name="attachments_text" value={attachmentsText} />
        <label htmlFor="task_description" className="sr-only">
          Task description
        </label>
        <textarea
          id="task_description"
          name="task_description"
          rows={8}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="Input the prompt you want a model for…"
          className="w-full resize-y rounded-lg border border-brand-slate-300 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 px-4 py-3 text-brand-slate-900 dark:text-brand-slate-50 shadow-sm placeholder:text-brand-slate-400 focus:border-brand-accent focus:outline-none focus:ring-2 focus:ring-brand-accent/30"
        />

        <div
          role="presentation"
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          className={
            "rounded-lg border-2 border-dashed border-brand-slate-300 dark:border-brand-slate-700 " +
            "bg-brand-slate-50 dark:bg-brand-slate-900 px-4 py-6 text-center"
          }
        >
          <p className="text-sm text-brand-slate-600 dark:text-brand-slate-300">
            Drop text files here (.txt, .md, .json) — up to 5
          </p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-2 text-sm font-medium text-brand-accent hover:text-brand-accent-hover"
          >
            Browse files
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,.json"
            multiple
            className="hidden"
            onChange={(e) => handleFilesSelected(e.target.files)}
          />
          {attachments.length > 0 ? (
            <ul className="mt-3 space-y-1 text-left text-sm text-brand-slate-700 dark:text-brand-slate-200">
              {attachments.map((a) => (
                <li key={a.name}>{a.name}</li>
              ))}
            </ul>
          ) : null}
          {truncated ? (
            <p className="mt-2 text-left text-xs text-brand-slate-500 dark:text-brand-slate-400">
              Attached file content was truncated at 50,000 characters.
            </p>
          ) : null}
          {fileNotice ? (
            <p
              className="mt-2 text-left text-xs text-brand-slate-500 dark:text-brand-slate-400"
              role="status"
            >
              {fileNotice}
            </p>
          ) : null}
        </div>

        <p className="text-sm text-brand-slate-600 dark:text-brand-slate-300">
          Recommendations use your AI subscriptions and budget priority from{" "}
          <Link
            href="/settings"
            className="font-medium text-brand-accent hover:text-brand-accent-hover"
          >
            Settings
          </Link>
          .
        </p>

        {state.error ? (
          <p className="text-sm text-red-600" role="alert">
            {state.error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-brand-accent px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Recommending…" : "Submit"}
        </button>
      </form>
    </div>
  );
}
