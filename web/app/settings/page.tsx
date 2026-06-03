// web/app/settings/page.tsx
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ProfilePreferencesForm } from "@/components/ProfilePreferencesForm";
import { getServerSession } from "@/lib/auth";
import { DEFAULT_PROFILE, getProfile } from "@/lib/profile";
import { getSubscriptionOptions } from "@/lib/subscriptions";

export const metadata: Metadata = {
  title: "roadmodel — settings",
  description: "Update your subscriptions, budget priority, and jurisdiction preferences.",
  robots: { index: false, follow: false },
};

// Post-onboarding edit surface for the same preferences (issue #154).
// Onboarding is one-shot (redirects away once onboarded_at is set), so
// without this page there was no way to change subscriptions/budget/
// jurisdictions after the first session. Auth-gated; pre-fills from the
// current profile (or sane defaults when no row exists yet).
export default async function SettingsPage() {
  const session = await getServerSession();
  if (!session) {
    redirect("/login?next=/settings");
  }

  const profile = await getProfile(session.id);

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-slate-50 px-6 py-16">
      <div className="w-full max-w-xl rounded-2xl border border-brand-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-brand-slate-900">
          Settings
        </h1>
        <p className="mt-3 text-sm text-brand-slate-600">
          Your subscriptions, budget priority, and jurisdiction preferences
          shape every model recommendation and roadmap suggestion we generate
          for you.
        </p>
        <ProfilePreferencesForm
          subscriptionOptions={getSubscriptionOptions()}
          initialSubscriptions={
            profile?.subscriptions ?? [...DEFAULT_PROFILE.subscriptions]
          }
          initialBudgetPriority={
            profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority
          }
          initialJurisdictions={
            profile?.allowed_jurisdictions ?? [
              ...DEFAULT_PROFILE.allowed_jurisdictions,
            ]
          }
          submitLabel="Save changes"
          redirectOnSave={null}
        />
      </div>
    </div>
  );
}
