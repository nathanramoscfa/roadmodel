// web/components/LaneChooser.tsx
//
// The ways a visitor outside the invite list, holding no key, can get a
// recommendation on /recommend: Quick pick (three picks computed in code from
// published benchmarks and prices, free to everyone), their own API key or
// OpenRouter credits (the AI recommender, reading their own words), or
// roadmodel's MCP server in their own agent. Invited members and visitors
// holding a key see the free-text composer alone.
"use client";

import { Bot, KeyRound, Terminal, Zap, type LucideIcon } from "lucide-react";

export type Lane = "quick" | "key" | "agent";
export type LaneChoice = Lane | "openrouter";

const CHOICES: { id: LaneChoice; lane: Lane; title: string; detail: string; icon: LucideIcon }[] = [
  {
    id: "quick",
    lane: "quick",
    title: "Quick pick",
    detail: "Free, computed from published benchmarks and prices",
    icon: Zap,
  },
  {
    id: "key",
    lane: "key",
    title: "Use your own API key",
    detail: "An AI reads your task, billed to your key",
    icon: KeyRound,
  },
  {
    id: "openrouter",
    lane: "key",
    title: "Connect OpenRouter",
    detail: "An AI reads your task, paid from your OpenRouter balance",
    icon: Bot,
  },
  {
    id: "agent",
    lane: "agent",
    title: "Run it in your own agent",
    detail: "roadmodel's MCP server, inside your coding agent",
    icon: Terminal,
  },
];

export function LaneChooser({
  lane,
  openRouter,
  onChoose,
}: {
  lane: Lane;
  // The key lane is open on OpenRouter, so that choice reads as the current one.
  openRouter: boolean;
  onChoose: (choice: LaneChoice) => void;
}) {
  return (
    <div role="group" aria-label="How to get a recommendation" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" data-testid="lane-chooser">
      {CHOICES.map((c) => {
        const current = c.lane === lane && (c.lane !== "key" || (c.id === "openrouter") === openRouter);
        const Icon = c.icon;
        return (
          <button
            key={c.id}
            type="button"
            aria-pressed={current}
            onClick={() => onChoose(c.id)}
            data-testid={`lane-${c.id}`}
            className={
              "flex items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left shadow-sm transition " +
              (current
                ? "border-brand-accent bg-brand-accent/10 ring-1 ring-brand-accent/40"
                : "border-brand-slate-200 bg-white hover:border-brand-accent/60 dark:border-brand-slate-700 dark:bg-brand-slate-800")
            }
          >
            <Icon className="mt-0.5 h-4 w-4 flex-none text-brand-accent" aria-hidden />
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">{c.title}</span>
              <span className="block text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">{c.detail}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
