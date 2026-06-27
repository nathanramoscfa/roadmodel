// web/lib/budget-priority.ts
//
// Single source for the budget-priority control shared by Settings
// (ProfilePreferencesForm) and the /recommend prompt box (PromptForm), so the
// labels and option order stay identical on both surfaces. Type-only import
// from @/lib/profile — importing a VALUE there pulls server-only modules and
// breaks the client bundle (mirrors the note in ProfilePreferencesForm).
import type { BudgetPriority } from "@/lib/profile";

// The stored ids are historical (`cheap`/`balanced`/`best`); the user-facing
// labels are Cost / Balanced / Quality. Ids are unchanged so no data migration.
export const BUDGET_PRIORITY_OPTIONS: {
  id: BudgetPriority;
  label: string;
  hint: string;
}[] = [
  { id: "cheap", label: "Cost", hint: "Cheapest model that can do the job" },
  { id: "balanced", label: "Balanced", hint: "Best value for the task" },
  { id: "best", label: "Quality", hint: "Highest-quality model" },
];

export const BUDGET_PRIORITY_IDS: readonly BudgetPriority[] = [
  "cheap",
  "balanced",
  "best",
];

export function isBudgetPriority(value: unknown): value is BudgetPriority {
  return (
    typeof value === "string" &&
    (BUDGET_PRIORITY_IDS as readonly string[]).includes(value)
  );
}
