// web/components/TryItNowTextarea.tsx
"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import type { RecommendResponse } from "@/lib/api";
import { RECOMMEND_PREFILL_KEY } from "./RecommendWorkspace";

// Home CTA posts to /api/recommend and stores the JSON in sessionStorage
// before navigating to /recommend. That avoids stuffing prompt + response
// into the URL bar while still showing results on the recommend page.

export function TryItNowTextarea() {
  const router = useRouter();
  const [task, setTask] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = task.trim();
    if (!trimmed) {
      return;
    }

    setPending(true);
    setError(null);

    try {
      const res = await fetch("/api/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_description: trimmed }),
      });

      if (!res.ok) {
        setError(
          "Could not fetch a recommendation — try again on the full page.",
        );
        return;
      }

      const recommendation = (await res.json()) as RecommendResponse;
      sessionStorage.setItem(
        RECOMMEND_PREFILL_KEY,
        JSON.stringify({
          task_description: trimmed,
          recommendation,
        }),
      );
      router.push("/recommend");
    } catch {
      setError("Network error — please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-8 w-full max-w-xl text-left">
      <label htmlFor="try-task" className="sr-only">
        Describe your task
      </label>
      <textarea
        id="try-task"
        name="task"
        rows={3}
        value={task}
        onChange={(event) => setTask(event.target.value)}
        placeholder="Describe your task — e.g. refactor auth middleware across 12 files"
        className="w-full resize-y rounded-lg border border-brand-slate-300 bg-white px-4 py-3 text-brand-slate-900 shadow-sm placeholder:text-brand-slate-400 focus:border-brand-accent focus:outline-none focus:ring-2 focus:ring-brand-accent/30"
      />
      {error ? (
        <p className="mt-2 text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="mt-3 w-full rounded-lg bg-brand-slate-800 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-brand-slate-900 disabled:opacity-60 sm:w-auto"
      >
        {pending ? "Recommending…" : "Get recommendation"}
      </button>
    </form>
  );
}
