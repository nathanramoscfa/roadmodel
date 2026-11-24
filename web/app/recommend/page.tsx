// web/app/recommend/page.tsx
import { cookies } from "next/headers";
import Link from "next/link";

import { RecommendWorkspace } from "@/components/RecommendWorkspace";
import { getServerSession } from "@/lib/auth";
import { getModelAvailability } from "@/lib/availability";
import { getBenchmarkMeta, getModelRows, getScoreFit } from "@/lib/catalog-models";
import { reachableModelIds } from "@/lib/funding";
import { keylessAgreement } from "@/lib/keyless-eval";
import { getProfile } from "@/lib/profile";
import { DEFAULT_ENGINE, menuFor, viewerFor, visitorMenuFor } from "@/lib/recommend-engines";
import { picksData, viewerPool } from "@/lib/recommend-picks";
import { parseEnginePref, RECOMMEND_PREFS_COOKIE } from "@/lib/recommend-prefs";
import { VISITOR_PROVIDERS, type VisitorProvider } from "@/lib/visitor-key";

export const metadata = {
  title: "Recommend — roadmodel",
  description:
    "Describe a task and get three model picks (Cost, Balanced and Quality), each with a runner-up and a backup from other makers: the platform to run it on, the level to set and what it costs you, read from the cost/quality frontier of the models you can run. Quick pick computes them free from published benchmarks and prices.",
};

export default async function RecommendPage() {
  const session = await getServerSession();
  const viewer = viewerFor(session?.id);
  const engines = menuFor(viewer);
  // The menu for a visitor's own key, by provider: every evaluated engine of it.
  const visitorEngines = Object.fromEntries(
    VISITOR_PROVIDERS.map((p) => [p, visitorMenuFor(p)]),
  ) as Record<VisitorProvider, ReturnType<typeof visitorMenuFor>>;
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
    // The catalog page's frame (app/page.tsx): the same width, header and
    // rhythm, so the two halves of the site read as one.
    <section className="mx-auto max-w-7xl px-6 py-12 sm:py-16">
      <header className="max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">roadmodel</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
          Recommend a model
        </h1>
        <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
          Describe a task. An engine reads it and ranks the models you can run for it, from Artificial
          Analysis&rsquo;s benchmarks, the <strong>S&nbsp;&rarr;&nbsp;D</strong> ratings, prices and the plans you
          hold. You get three picks (the cheapest model that does the job, the best value and the strongest), each
          with a runner-up and a backup from other makers, the platform to run it on, the level to set there and
          what it costs you. Every model behind them is in the{" "}
          <Link href="/" className="font-medium text-brand-accent hover:underline">
            catalog
          </Link>
          .
        </p>
      </header>

      <div className="mt-10">
        <RecommendWorkspace
          key={session?.id ?? "anonymous"}
          engines={engines}
          visitorEngines={visitorEngines}
          initialEngine={initialEngine}
          picks={picks}
          signedIn={session !== null}
          owner={session?.id ?? "anonymous"}
          modelCount={models.length}
          measuredCount={bench.measuredCount}
          keylessViewer={viewer === "anonymous" || viewer === "visitor"}
          agreement={keylessAgreement()}
        />
      </div>
    </section>
  );
}
