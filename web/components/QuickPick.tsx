// web/components/QuickPick.tsx
//
// Quick pick on /recommend: the visitor classifies the task themselves (task
// type, difficulty, a new kind of problem or not, budget priority) and
// /api/recommend/keyless answers with three picks computed from published
// benchmarks and prices (lib/keyless.ts). The result explains each pick in
// three plain sentences (how strong the model is for this kind of work, how it
// meets the task's difficulty, what it costs) and states how often these picks
// matched the AI recommender on the test tasks, from the build's copy of
// docs/keyless-eval.json.
"use client";

import { AlertTriangle, Sparkles, Zap } from "lucide-react";
import { useState } from "react";

import { BUDGET_PRIORITY_OPTIONS } from "@/lib/budget-priority";
import { CATEGORY_DEFS } from "@/lib/catalog-fields";
import {
  KEYLESS_CATEGORIES,
  KEYLESS_COMPLEXITIES,
  type KeylessAgreement,
  type KeylessComplexity,
  type KeylessPriority,
  type KeylessResponse,
  type KeylessTask,
} from "@/lib/keyless";
import type { BudgetPriority } from "@/lib/profile";

const DIFFICULTY: Record<KeylessComplexity, { label: string; hint: string }> = {
  low: { label: "Low", hint: "Routine work with a familiar shape" },
  medium: { label: "Medium", hint: "Several steps and some judgement" },
  high: { label: "High", hint: "Hard, many-part work where mistakes are costly" },
};

const RUNG_LABEL: Record<KeylessPriority, { label: string; hint: string }> = {
  quality: { label: "Quality", hint: "The strongest model for the task" },
  balanced: { label: "Balanced", hint: "The best value below it" },
  cost: { label: "Cost", hint: "The cheapest model that still does the job" },
};

const PRIORITY_RUNG: Record<BudgetPriority, KeylessPriority> = {
  cheap: "cost",
  balanced: "balanced",
  best: "quality",
};

const WHY_LABEL: { key: keyof KeylessResponse["rungs"][number]["why"]; label: string }[] = [
  { key: "quality", label: "Strength" },
  { key: "requirement_shortfall", label: "Fit to the task" },
  { key: "cost", label: "Cost" },
];

export function agreementSentence(a: KeylessAgreement): string {
  return (
    "These picks are computed from published benchmarks and prices. " +
    `On our ${a.tasks} test tasks they matched the AI recommender on ${a.agree} of ${a.total} picks.`
  );
}

function legend(text: string) {
  return (
    <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
      {text}
    </legend>
  );
}

function optionClass(selected: boolean): string {
  return (
    "flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-left transition " +
    (selected
      ? "border-brand-accent bg-brand-accent/10"
      : "border-brand-slate-200 hover:border-brand-accent/60 dark:border-brand-slate-700")
  );
}

export function QuickPickForm({
  initial,
  pending,
  error,
  onSubmit,
}: {
  initial: KeylessTask;
  pending: boolean;
  error: string | null;
  onSubmit: (task: KeylessTask) => void;
}) {
  const [category, setCategory] = useState(initial.category);
  const [complexity, setComplexity] = useState(initial.complexity);
  const [novel, setNovel] = useState(initial.novel);
  const [budget, setBudget] = useState<BudgetPriority>(initial.budget_priority ?? "balanced");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!pending) onSubmit({ category, complexity, novel, budget_priority: budget });
      }}
      className="space-y-5 rounded-xl border border-brand-slate-200 bg-white px-4 py-4 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
      data-testid="quick-pick-form"
    >
      <fieldset>
        {legend("Task type")}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {KEYLESS_CATEGORIES.map((c) => (
            <label key={c} className={optionClass(category === c)}>
              <input
                type="radio"
                name="category"
                value={c}
                checked={category === c}
                onChange={() => setCategory(c)}
                className="mt-1 accent-brand-accent"
              />
              <span>
                <span className="block text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                  {CATEGORY_DEFS[c].label}
                </span>
                <span className="block text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
                  {CATEGORY_DEFS[c].definition}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-5 md:grid-cols-2">
        <fieldset>
          {legend("Difficulty")}
          <div className="grid gap-2 sm:grid-cols-3 md:grid-cols-1 lg:grid-cols-3">
            {KEYLESS_COMPLEXITIES.map((d) => (
              <label key={d} className={optionClass(complexity === d)}>
                <input
                  type="radio"
                  name="complexity"
                  value={d}
                  checked={complexity === d}
                  onChange={() => setComplexity(d)}
                  className="mt-1 accent-brand-accent"
                />
                <span>
                  <span className="block text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                    {DIFFICULTY[d].label}
                  </span>
                  <span className="block text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
                    {DIFFICULTY[d].hint}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <label className="mt-3 flex items-start gap-2 text-sm text-brand-slate-700 dark:text-brand-slate-200">
            <input
              type="checkbox"
              checked={novel}
              onChange={(e) => setNovel(e.target.checked)}
              className="mt-1 accent-brand-accent"
              data-testid="quick-pick-novel"
            />
            <span>
              <span className="font-semibold">A new kind of problem</span>
              <span className="block text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
                Research-grade work with no established method to follow. It raises the bar for high-difficulty
                tasks.
              </span>
            </span>
          </label>
        </fieldset>

        <fieldset>
          {legend("Budget priority")}
          <div className="grid gap-2 sm:grid-cols-3 md:grid-cols-1 lg:grid-cols-3">
            {BUDGET_PRIORITY_OPTIONS.map((o) => (
              <label key={o.id} className={optionClass(budget === o.id)}>
                <input
                  type="radio"
                  name="budget_priority"
                  value={o.id}
                  checked={budget === o.id}
                  onChange={() => setBudget(o.id)}
                  className="mt-1 accent-brand-accent"
                />
                <span>
                  <span className="block text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                    {o.label}
                  </span>
                  <span className="block text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">{o.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-brand-slate-100 pt-3 dark:border-brand-slate-700/70">
        <button
          type="submit"
          disabled={pending}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-accent px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="quick-pick-submit"
        >
          <Zap className="h-4 w-4" aria-hidden />
          {pending ? "Picking…" : "Get three picks"}
        </button>
      </div>
      {error && (
        <p
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
          role="alert"
        >
          {error}
        </p>
      )}
    </form>
  );
}

export function KeylessResult({
  data,
  agreement,
  onChange,
  onDescribe,
}: {
  data: KeylessResponse;
  agreement: KeylessAgreement;
  onChange: () => void;
  // Switch to the AI recommender, which reads the task in the visitor's words.
  onDescribe: () => void;
}) {
  const primary = PRIORITY_RUNG[(data.task.budget_priority as BudgetPriority) ?? "balanced"] ?? "balanced";
  const category = CATEGORY_DEFS[data.task.category as keyof typeof CATEGORY_DEFS]?.label ?? data.task.category;
  const difficulty = DIFFICULTY[data.task.complexity as KeylessComplexity]?.label ?? data.task.complexity;

  return (
    <div className="space-y-4" data-testid="keyless-result">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-slate-200 bg-white px-4 py-3 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-slate-400 dark:text-brand-slate-500">
          Quick pick
        </span>
        <p className="min-w-0 flex-1 text-sm text-brand-slate-800 dark:text-brand-slate-100" data-testid="keyless-task">
          {category} · {difficulty} difficulty{data.task.novel ? " · a new kind of problem" : ""}
        </p>
        <div className="flex flex-none gap-1.5">
          <button
            type="button"
            onClick={onChange}
            className="rounded-md border border-brand-slate-300 px-2.5 py-1 text-xs font-semibold text-brand-slate-600 hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-600 dark:text-brand-slate-300"
          >
            Change the task
          </button>
        </div>
      </div>

      <section aria-label="The three picks" className="grid gap-3 md:grid-cols-3">
        {data.rungs.map((r) => (
          <article
            key={r.priority}
            className={
              "space-y-3 rounded-xl border bg-white p-4 shadow-sm dark:bg-brand-slate-800 " +
              (r.priority === primary
                ? "border-brand-accent ring-1 ring-brand-accent/40"
                : "border-brand-slate-200 dark:border-brand-slate-700")
            }
            data-testid={`keyless-rung-${r.priority}`}
          >
            <header>
              <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                {RUNG_LABEL[r.priority].label}
                {r.priority === primary && (
                  <span className="rounded-full bg-brand-accent/10 px-1.5 py-px text-[10px] text-brand-accent">
                    Your priority
                  </span>
                )}
                {r.specialist && (
                  <span className="rounded-full bg-brand-slate-100 px-1.5 py-px text-[10px] text-brand-slate-600 dark:bg-brand-slate-700 dark:text-brand-slate-200">
                    Category specialist
                  </span>
                )}
              </p>
              <p className="text-[11px] text-brand-slate-400 dark:text-brand-slate-500">{RUNG_LABEL[r.priority].hint}</p>
              <h3 className="mt-1.5 text-lg font-bold text-brand-slate-900 dark:text-brand-slate-50">{r.model_name}</h3>
              <p className="text-sm text-brand-slate-600 dark:text-brand-slate-300">
                on {r.platform_name} · Effort {r.effort}
              </p>
            </header>
            <dl className="space-y-2 text-sm">
              {WHY_LABEL.map((w) => (
                <div key={w.key}>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-brand-slate-400 dark:text-brand-slate-500">
                    {w.label}
                  </dt>
                  <dd className="leading-6 text-brand-slate-700 dark:text-brand-slate-200">{r.why[w.key]}</dd>
                </div>
              ))}
            </dl>
            {r.backup && (
              <p className="border-t border-brand-slate-100 pt-2 text-xs text-brand-slate-500 dark:border-brand-slate-700/70 dark:text-brand-slate-400">
                Backup: <span className="font-semibold">{r.backup.model_name}</span> on {r.backup.platform_name} ·
                Effort {r.backup.effort}
              </p>
            )}
          </article>
        ))}
      </section>

      {data.backup_warning && (
        <p className="flex items-start gap-2 rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <AlertTriangle className="mt-px h-3.5 w-3.5 flex-none" aria-hidden />
          {data.backup_warning}
        </p>
      )}

      <div className="flex flex-wrap items-start gap-2.5 rounded-xl border border-brand-accent/30 bg-brand-accent/5 px-4 py-3 text-sm text-brand-slate-700 dark:text-brand-slate-200">
        <Sparkles className="mt-0.5 h-4 w-4 flex-none text-brand-accent" aria-hidden />
        <div className="min-w-0 flex-1 space-y-1">
          <p data-testid="keyless-agreement">{agreementSentence(agreement)}</p>
          <p className="text-xs text-brand-slate-500 dark:text-brand-slate-400" data-testid="keyless-agreement-date">
            Measured {agreement.evaluatedOn}. For picks that read your task in your own words, the AI recommender
            runs on your own API key.{" "}
            <button type="button" onClick={onDescribe} className="font-semibold text-brand-accent hover:underline">
              Describe your task
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
