// web/app/recommend/page.tsx
import { RecommendWorkspace } from "@/components/RecommendWorkspace";
import { getServerSession } from "@/lib/auth";

export default async function RecommendPage() {
  // The page returns all three priorities (Cost / Balanced / Quality) per
  // submit; the highlighted-by-default one is seeded server-side from the
  // profile inside /api/recommend. Here we only need to know whether the
  // visitor is signed in, so the "Set as default" control can persist.
  const session = await getServerSession();

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
          Input your prompt and we&apos;ll suggest a Cost, Balanced, and Quality
          model — each with its platform, settings, and cost.
        </p>
      </header>

      {/* Single full-width column: the redesign renders the three picks as a
          side-by-side comparison matrix + detail, which needs the full width
          (the old two-column layout squeezed them into stacked cards). */}
      <div className="mt-8">
        <RecommendWorkspace canPersistBudget={session !== null} />
      </div>
    </section>
  );
}
