// web/app/(auth)/onboarding/OnboardingForm.tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type {
  BudgetPriority,
  JurisdictionCode,
  SubscriptionId,
} from "@/lib/profile";

const SUBSCRIPTION_OPTIONS: {
  id: SubscriptionId;
  label: string;
}[] = [
  { id: "claude-max", label: "claude.ai Max" },
  { id: "cursor-ultra", label: "Cursor Ultra" },
  { id: "chatgpt-pro", label: "ChatGPT Pro" },
];

const BUDGET_OPTIONS: { id: BudgetPriority; label: string }[] = [
  { id: "cheap", label: "Cheap" },
  { id: "balanced", label: "Balanced" },
  { id: "best", label: "Best" },
];

const DEFAULT_JURISDICTIONS: JurisdictionCode[] = [
  "us",
  "eu",
  "uk",
  "ca",
  "au",
  "jp",
  "kr",
];

const ALL_JURISDICTIONS: { id: JurisdictionCode; label: string }[] = [
  { id: "us", label: "United States" },
  { id: "eu", label: "European Union" },
  { id: "uk", label: "United Kingdom" },
  { id: "ca", label: "Canada" },
  { id: "au", label: "Australia" },
  { id: "jp", label: "Japan" },
  { id: "kr", label: "South Korea" },
  { id: "cn", label: "China" },
  { id: "ru", label: "Russia" },
  { id: "unknown", label: "Unknown" },
];

interface OnboardingFormProps {
  next: string;
}

export function OnboardingForm({ next }: OnboardingFormProps) {
  const router = useRouter();
  const [subscriptions, setSubscriptions] = useState<SubscriptionId[]>([]);
  const [budgetPriority, setBudgetPriority] =
    useState<BudgetPriority>("balanced");
  const [restrictLowRisk, setRestrictLowRisk] = useState(true);
  const [customJurisdictions, setCustomJurisdictions] =
    useState<JurisdictionCode[]>(DEFAULT_JURISDICTIONS);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleSubscription(id: SubscriptionId): void {
    setSubscriptions((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
    );
  }

  function toggleJurisdiction(id: JurisdictionCode): void {
    setCustomJurisdictions((prev) => {
      if (prev.includes(id)) {
        const nextList = prev.filter((j) => j !== id);
        return nextList.length > 0 ? nextList : prev;
      }
      return [...prev, id];
    });
  }

  async function saveProfile(body: Record<string, unknown>): Promise<void> {
    setPending(true);
    setError(null);
    const res = await fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setPending(false);
    if (!res.ok) {
      setError("Could not save your preferences. Please try again.");
      return;
    }
    router.push(next);
  }

  function allowedJurisdictions(): JurisdictionCode[] {
    if (restrictLowRisk) {
      return DEFAULT_JURISDICTIONS;
    }
    return customJurisdictions;
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await saveProfile({
      subscriptions,
      budget_priority: budgetPriority,
      allowed_jurisdictions: allowedJurisdictions(),
      skip: false,
    });
  }

  async function handleSkip(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    await saveProfile({ skip: true });
  }

  return (
    <form onSubmit={handleSave} className="mt-8 flex flex-col gap-8">
      <fieldset>
        <legend className="text-sm font-semibold text-brand-slate-900">
          Active subscriptions
        </legend>
        <p className="mt-1 text-sm text-brand-slate-600">
          Select every subscription you pay for today.
        </p>
        <div className="mt-4 flex flex-col gap-3">
          {SUBSCRIPTION_OPTIONS.map((option) => (
            <label
              key={option.id}
              className="flex items-center gap-2 text-sm text-brand-slate-800"
            >
              <input
                type="checkbox"
                checked={subscriptions.includes(option.id)}
                onChange={() => toggleSubscription(option.id)}
                className="rounded border-brand-slate-300"
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-sm font-semibold text-brand-slate-900">
          Budget priority
        </legend>
        <p className="mt-1 text-sm text-brand-slate-600">
          How aggressively should we optimize for cost vs. quality?
        </p>
        <div className="mt-4 flex flex-wrap gap-4">
          {BUDGET_OPTIONS.map((option) => (
            <label
              key={option.id}
              className="flex items-center gap-2 text-sm text-brand-slate-800"
            >
              <input
                type="radio"
                name="budget_priority"
                value={option.id}
                checked={budgetPriority === option.id}
                onChange={() => setBudgetPriority(option.id)}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      <details
        open={advancedOpen}
        onToggle={(event) =>
          setAdvancedOpen((event.target as HTMLDetailsElement).open)
        }
        className="rounded-lg border border-brand-slate-200 bg-white"
      >
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-brand-slate-800">
          Advanced: jurisdiction filter
        </summary>
        <div className="space-y-4 border-t border-brand-slate-200 px-4 py-4">
          <label className="flex items-start gap-2 text-sm text-brand-slate-800">
            <input
              type="checkbox"
              checked={restrictLowRisk}
              onChange={(event) => setRestrictLowRisk(event.target.checked)}
              className="mt-0.5 rounded border-brand-slate-300"
            />
            <span>
              Restrict to low-risk jurisdictions (recommended)
            </span>
          </label>
          {restrictLowRisk ? (
            <div className="flex flex-wrap gap-2">
              {DEFAULT_JURISDICTIONS.map((code) => (
                <span
                  key={code}
                  className={
                    "rounded-full bg-brand-slate-100 px-3 py-1 text-xs " +
                    "font-medium uppercase tracking-wide text-brand-slate-700"
                  }
                >
                  {code}
                </span>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-brand-slate-600">
                Explicitly choose which jurisdictions may appear in
                recommendations. Check China or Russia only if you
                accept the provider risk.
              </p>
              {ALL_JURISDICTIONS.map((option) => (
                <label
                  key={option.id}
                  className="flex items-center gap-2 text-sm text-brand-slate-800"
                >
                  <input
                    type="checkbox"
                    checked={customJurisdictions.includes(option.id)}
                    onChange={() => toggleJurisdiction(option.id)}
                    className="rounded border-brand-slate-300"
                  />
                  {option.label} ({option.id})
                </label>
              ))}
            </div>
          )}
        </div>
      </details>

      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <button
          type="submit"
          disabled={pending}
          className={
            "rounded-lg bg-brand-accent px-6 py-3 text-sm font-semibold " +
            "text-white shadow-sm hover:bg-brand-accent/90 disabled:opacity-60"
          }
        >
          {pending ? "Saving…" : "Save and continue"}
        </button>
        <button
          type="button"
          onClick={handleSkip}
          disabled={pending}
          className="text-sm font-medium text-brand-accent hover:underline"
        >
          Skip for now
        </button>
      </div>
    </form>
  );
}
