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
    <section className="mx-auto max-w-6xl px-6 py-8">
      {/* Compact header (the nav already brands "roadmodel") so the picks sit
          near the top of the viewport — the redesign's fit-on-screen goal. */}
      <header className="max-w-2xl">
        <h1 className="text-2xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50">
          Get a model recommendation
        </h1>
        <p className="mt-1.5 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          One prompt, three picks — Cost, Balanced, and Quality — compared side
          by side, with platform, settings, and real cost to you.
        </p>
      </header>

      {/* Single full-width column: the redesign renders the three picks as a
          side-by-side comparison matrix + detail, which needs the full width
          (the old two-column layout squeezed them into stacked cards). */}
      <div className="mt-6">
        <RecommendWorkspace canPersistBudget={session !== null} />
      </div>
    </section>
  );
}
