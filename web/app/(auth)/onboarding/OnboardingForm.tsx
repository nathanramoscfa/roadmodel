// web/app/(auth)/onboarding/OnboardingForm.tsx
"use client";

import {
  DEFAULT_JURISDICTIONS,
  ProfilePreferencesForm,
} from "@/components/ProfilePreferencesForm";

interface OnboardingFormProps {
  next: string;
}

// First-session capture. Defaults to an empty selection + the recommended
// jurisdiction set, redirects to `next` on save, and offers a skip. The
// actual fields live in the shared ProfilePreferencesForm so onboarding and
// /settings never drift (issue #154).
export function OnboardingForm({ next }: OnboardingFormProps) {
  return (
    <ProfilePreferencesForm
      initialSubscriptions={[]}
      initialBudgetPriority="balanced"
      initialJurisdictions={DEFAULT_JURISDICTIONS}
      submitLabel="Save and continue"
      redirectOnSave={next}
      skipLabel="Skip for now"
    />
  );
}
