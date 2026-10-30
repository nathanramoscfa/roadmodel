// web/app/page.tsx
import { cookies } from "next/headers";
import Link from "next/link";

import { BenchmarkReference } from "@/components/BenchmarkReference";
import { CatalogLegend } from "@/components/CatalogLegend";
import { Footer } from "@/components/Footer";
import { ModelsExplorer } from "@/components/ModelsExplorer";
import {
  getBenchmarkMeta,
  getCatalogGeneratedAt,
  getModelRows,
  getPriceFit,
  getScoreFit,
} from "@/lib/catalog-models";
import { parsePrefs, PREFS_COOKIE } from "@/lib/models-prefs";

export default async function HomePage() {
  // The visitor's saved filters, grouping and view, so the first render is
  // already the page they left (lib/models-prefs).
  const prefs = parsePrefs((await cookies()).get(PREFS_COOKIE)?.value);
  const models = getModelRows();
  const generatedAt = getCatalogGeneratedAt();
  const bench = getBenchmarkMeta();
  const scoreFit = getScoreFit(models);
  const priceFit = getPriceFit(models);

  return (
    <>
      <section className="mx-auto max-w-7xl px-6 py-12 sm:py-16">
        <header className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
            roadmodel
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
            Model catalog
          </h1>
          <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
            Every model roadmodel recommends from: its price, its{" "}
            <strong>S&nbsp;&rarr;&nbsp;D</strong> rating in each category, and Artificial
            Analysis&rsquo;s benchmark scores, measured the same way for every model and refreshed
            daily. The filters drive the charts and the table and stay set for your next visit;
            hover any label for its definition and source, or{" "}
            <Link href="/recommend" className="font-medium text-brand-accent hover:underline">
              get a recommendation
            </Link>{" "}
            for a task.
          </p>
        </header>

        {/* Overview first: the filters, the frontier drawn across every model
            right under them, the catalog table (its rows scroll in their own
            box), then the charts that take the frontier apart, by quality
            band or by cost tier as the table is grouped (all three under the
            same filters), then the full key (the table's
            caption links to it). */}
        <div className="mt-10 space-y-8">
          <ModelsExplorer
            models={models}
            generatedAt={generatedAt}
            benchmarksGeneratedAt={bench.generatedAt}
            measuredCount={bench.measuredCount}
            scoreFit={scoreFit}
            priceFit={priceFit}
            prefs={prefs}
          />
          <CatalogLegend id="how-to-read" />
          <BenchmarkReference id="benchmarks" />
        </div>
      </section>
      <Footer />
    </>
  );
}
