// web/components/PromptForm.tsx
"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";
import type { RecommendResponse } from "@/lib/api";

const ACCEPTED_EXTENSIONS = [".md", ".txt", ".json", ".png", ".jpg"];
const MAX_ATTACHMENTS = 5;

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
  if (!task) {
    return { error: "Input a prompt before submitting." };
  }

  // Subscriptions + budget priority come from the signed-in user's profile
  // (Settings), which the /api/recommend route reads server-side — so the
  // request only carries the prompt. (The old inline "Your context" inputs were
  // dead: the route already overrode them with the profile.)
  const res = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_description: task }),
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
  const [attachments, setAttachments] = useState<string[]>([]);
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

  function handleFilesSelected(files: FileList | null) {
    if (!files) {
      return;
    }
    const names = Array.from(files)
      .map((f) => f.name)
      .filter((name) =>
        ACCEPTED_EXTENSIONS.some((ext) =>
          name.toLowerCase().endsWith(ext),
        ),
      );
    setAttachments((prev) =>
      [...prev, ...names].slice(0, MAX_ATTACHMENTS),
    );
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    handleFilesSelected(event.dataTransfer.files);
  }

  return (
    <div className="flex flex-col gap-6">
      <form action={formAction} className="flex flex-col gap-4">
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
            Drop files here (.md, .txt, .json, .png, .jpg) — up to 5
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
            accept=".md,.txt,.json,.png,.jpg"
            multiple
            className="hidden"
            onChange={(e) => handleFilesSelected(e.target.files)}
          />
          {attachments.length > 0 ? (
            <ul className="mt-3 space-y-1 text-left text-sm text-brand-slate-700 dark:text-brand-slate-200">
              {attachments.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
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
