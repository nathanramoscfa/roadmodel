// web/app/recommend/page.tsx
import { RecommendWorkspace } from "@/components/RecommendWorkspace";
import { getServerSession } from "@/lib/auth";
import { DEFAULT_PROFILE, getProfile } from "@/lib/profile";

export default async function RecommendPage() {
  // Seed the inline budget control from the user's saved profile (or the
  // default for signed-out visitors). Signed-in users can persist a change
  // back to Settings; signed-out users get the control for the session only.
  const session = await getServerSession();
  const profile = session ? await getProfile(session.id) : null;
  const initialBudgetPriority =
    profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority;

  return (
    <section className="mx-auto max-w-6xl px-6 py-12 sm:py-16">
      <header className="max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
          Get a model recommendation
        </h1>
        <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
          Input your prompt and we&apos;ll suggest a model, platform, settings,
          and cost.
        </p>
      </header>

      <div className="mt-10 grid grid-cols-1 gap-10 lg:grid-cols-2 lg:gap-12">
        <RecommendWorkspace
          initialBudgetPriority={initialBudgetPriority}
          canPersistBudget={session !== null}
        />
      </div>
    </section>
  );
}
