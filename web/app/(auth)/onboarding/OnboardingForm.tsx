// web/app/(auth)/onboarding/OnboardingForm.tsx
"use client";

import {
  DEFAULT_JURISDICTIONS,
  ProfilePreferencesForm,
} from "@/components/ProfilePreferencesForm";
import type { SubscriptionOption } from "@/lib/subscriptions";

interface OnboardingFormProps {
  next: string;
  subscriptionOptions: SubscriptionOption[];
}

// First-session capture. Defaults to an empty selection + the recommended
// jurisdiction set, redirects to `next` on save, and offers a skip. The
// actual fields live in the shared ProfilePreferencesForm so onboarding and
// /settings never drift (issue #154); the subscription options are
// catalog-derived and passed from the server page (issue #152).
export function OnboardingForm({ next, subscriptionOptions }: OnboardingFormProps) {
  return (
    <ProfilePreferencesForm
      subscriptionOptions={subscriptionOptions}
      initialSubscriptions={[]}
      initialBudgetPriority="balanced"
      initialJurisdictions={DEFAULT_JURISDICTIONS}
      submitLabel="Save and continue"
      redirectOnSave={next}
      skipLabel="Skip for now"
    />
  );
}
