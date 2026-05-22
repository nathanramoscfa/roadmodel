// web/app/(auth)/onboarding/page.tsx
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { getServerSession } from "@/lib/auth";
import { getProfile, isOnboarded } from "@/lib/profile";

import { OnboardingForm } from "./OnboardingForm";

export const metadata: Metadata = {
  title: "roadmodel — onboarding",
  description: "Tell us about your setup so recommendations fit your stack.",
  robots: { index: false, follow: false },
};

interface OnboardingPageProps {
  searchParams: Promise<{ next?: string }>;
}

export default async function OnboardingPage({
  searchParams,
}: OnboardingPageProps) {
  const session = await getServerSession();
  if (!session) {
    redirect("/login?next=/onboarding");
  }

  const profile = await getProfile(session.id);
  if (isOnboarded(profile)) {
    redirect("/");
  }

  const params = await searchParams;
  const next =
    typeof params.next === "string" && params.next.startsWith("/")
      ? params.next
      : "/";

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-slate-50 px-6 py-16">
      <div className="w-full max-w-xl rounded-2xl border border-brand-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-brand-slate-900">
          Tell us about your setup
        </h1>
        <p className="mt-3 text-sm text-brand-slate-600">
          Your subscriptions, budget priority, and jurisdiction
          preferences shape every model recommendation and roadmap
          suggestion we generate for you.
        </p>
        <OnboardingForm next={next} />
      </div>
    </div>
  );
}
