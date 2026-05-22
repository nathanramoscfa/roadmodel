// web/components/RoadmapComposer.tsx
"use client";

import { useState } from "react";

interface RoadmapComposerProps {
  onSubmit: (text: string) => boolean | void;
}

export function RoadmapComposer({ onSubmit }: RoadmapComposerProps) {
  const [text, setText] = useState("");

  function handleSubmit() {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    const accepted = onSubmit(trimmed);
    if (accepted !== false) {
      setText("");
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="flex flex-col gap-3 border-t border-brand-slate-200 pt-4">
      <label htmlFor="roadmap_composer" className="sr-only">
        Project description
      </label>
      <textarea
        id="roadmap_composer"
        rows={4}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          "Describe your project. Paste, type, or attach anything."
        }
        className={
          "w-full resize-y rounded-lg border border-brand-slate-300 " +
          "bg-white px-4 py-3 text-brand-slate-900 shadow-sm " +
          "placeholder:text-brand-slate-400 focus:border-brand-accent " +
          "focus:outline-none focus:ring-2 focus:ring-brand-accent/30"
        }
      />
      <button
        type="button"
        onClick={handleSubmit}
        disabled={!text.trim()}
        className={
          "self-end rounded-lg bg-brand-accent px-6 py-2.5 text-sm " +
          "font-semibold text-white shadow-sm transition " +
          "hover:bg-brand-accent-hover disabled:cursor-not-allowed " +
          "disabled:opacity-60"
        }
      >
        Send
      </button>
    </div>
  );
}
