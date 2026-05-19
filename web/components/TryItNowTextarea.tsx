// web/components/TryItNowTextarea.tsx
"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export function TryItNowTextarea() {
  const router = useRouter();
  const [task, setTask] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = task.trim();
    if (!trimmed) {
      return;
    }
    const params = new URLSearchParams({ task: trimmed });
    router.push(`/recommend?${params.toString()}`);
  }

  return (
    <form onSubmit={handleSubmit} className="mt-8 w-full max-w-xl">
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
      <button
        type="submit"
        className="mt-3 w-full rounded-lg bg-brand-slate-800 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-brand-slate-900 sm:w-auto"
      >
        Get recommendation
      </button>
    </form>
  );
}
