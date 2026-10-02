// web/app/recommend/page.tsx
import { cookies } from "next/headers";

import { RecommendWorkspace } from "@/components/RecommendWorkspace";
import { getServerSession } from "@/lib/auth";
import { getModelAvailability } from "@/lib/availability";
import { getBenchmarkMeta, getModelRows, getScoreFit } from "@/lib/catalog-models";
import { reachableModelIds } from "@/lib/funding";
import { getProfile } from "@/lib/profile";
import { DEFAULT_ENGINE, menuFor, viewerFor } from "@/lib/recommend-engines";
import { picksData, viewerPool } from "@/lib/recommend-picks";
import { parseEnginePref, RECOMMEND_PREFS_COOKIE } from "@/lib/recommend-prefs";

export const metadata = {
  title: "Recommend — roadmodel",
  description:
    "Describe a task and get three model picks (Cost, Balanced and Quality), each with the platform to run it on, its settings and what it costs you, weighed across the whole catalog.",
};

export default async function RecommendPage() {
  const session = await getServerSession();
  const viewer = viewerFor(session?.id);
  const engines = menuFor(viewer);
  // The engine the visitor last chose, if they may still use it.
  const saved = parseEnginePref((await cookies()).get(RECOMMEND_PREFS_COOKIE)?.value);
  const initialEngine = engines.find((e) => e.hint === saved && e.allowed)?.hint ?? DEFAULT_ENGINE.hint;
  const models = getModelRows();
  const bench = getBenchmarkMeta();
  // The models this visitor's Settings reach, so the picks' frontier is drawn
  // over what they can run; the availability read only when there is a pool.
  const profile = session ? await getProfile(session.id) : null;
  const reachable = profile
    ? reachableModelIds(profile.subscriptions, profile.api_providers, profile.allowed_jurisdictions)
    : null;
  const unavailable = reachable ? (await getModelAvailability()).ids : [];
  const picks = picksData(models, {
    pool: viewerPool(models, reachable, unavailable),
    fit: getScoreFit(models),
    snapshot: bench.generatedAt,
  });

  return (
    <section className="mx-auto max-w-6xl px-6 py-10 sm:py-14">
      <header className="max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">roadmodel</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
          Recommend a model
        </h1>
        <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
          Describe a task. An engine reads it and weighs every model in the catalog for it (the S&nbsp;&rarr;&nbsp;D
          ratings, Artificial Analysis&rsquo;s benchmarks, prices, and the subscriptions you hold), then returns
          three picks: the cheapest model that does the job, the best value, and the strongest, each with the
          platform to run it on, its settings, and what it costs you.
        </p>
      </header>

      <div className="mt-8">
        <RecommendWorkspace
          engines={engines}
          initialEngine={initialEngine}
          picks={picks}
          signedIn={session !== null}
          modelCount={models.length}
          measuredCount={bench.measuredCount}
        />
      </div>
    </section>
  );
}
