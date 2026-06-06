// web/components/HowItWorks.tsx
import { Code2, MessageSquareText, Sparkles } from "lucide-react";

const steps = [
  {
    number: "1",
    title: "Describe your task",
    description:
      "Paste a prompt or task summary — coding, research, long-form, or ops.",
    icon: MessageSquareText,
  },
  {
    number: "2",
    title: "Get a model + platform + cost",
    description:
      "roadmodel returns a model, platform, settings block, and session cost estimate.",
    icon: Sparkles,
  },
  {
    number: "3",
    title: "Run it in your IDE",
    description:
      "Take the recommendation into Claude Code, Cursor, Codex, or your API of choice.",
    icon: Code2,
  },
] as const;

export function HowItWorks() {
  return (
    <section className="border-t border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 py-20">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-3xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
          How it works
        </h2>
        <ol className="mt-12 grid gap-8 sm:grid-cols-3">
          {steps.map((step) => (
            <li
              key={step.number}
              className="rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-50 dark:bg-brand-slate-900 p-6"
            >
              <step.icon
                className="h-8 w-8 text-brand-accent"
                aria-hidden="true"
              />
              <p className="mt-4 text-sm font-semibold text-brand-accent">
                {step.number}
              </p>
              <h3 className="mt-2 text-lg font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                {step.title}
              </h3>
              <p className="mt-2 text-sm text-brand-slate-600 dark:text-brand-slate-300">
                {step.description}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
