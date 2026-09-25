import { BenchmarkReference } from "@/components/BenchmarkReference";
import { CatalogLegend } from "@/components/CatalogLegend";
import { ModelsExplorer } from "@/components/ModelsExplorer";
import { getBenchmarkMeta, getCatalogGeneratedAt, getModelRows, getScoreFit } from "@/lib/catalog-models";

export const metadata = {
  title: "Models — roadmodel",
  description:
    "The full AI-model catalog roadmodel recommends from: pricing, the S→D per-category ratings, and Artificial Analysis's uniform benchmark scores for every model — sortable, filterable, and sourced.",
};

export default function ModelsPage() {
  const models = getModelRows();
  const generatedAt = getCatalogGeneratedAt();
  const bench = getBenchmarkMeta();
  const scoreFit = getScoreFit(models);

  return (
    <section className="mx-auto max-w-7xl px-6 py-12 sm:py-16">
      <header className="max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">roadmodel</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
          Model catalog
        </h1>
        <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
          Every model roadmodel recommends from — with pricing, the per-category{" "}
          <strong>S&nbsp;&rarr;&nbsp;D</strong> ratings, and one uniform set of numbers under
          them: Artificial Analysis&rsquo;s independently measured benchmarks, the same test on
          the same scale for every model, refreshed daily. A rating is a class several models can
          share; the figures separate them within it. Sort any column, filter by provider,
          jurisdiction, or cost (the charts below follow the same filters), switch to the full
          benchmark grid, and hover any label for its definition and source.
        </p>
      </header>

      {/* Most used first: the catalog itself, then the charts that explain its
          Score column, then the frontier drawn across every model (all three
          under the table's filters), then the full key (the table's caption
          links to it). */}
      <div className="mt-10 space-y-8">
        <ModelsExplorer
          models={models}
          generatedAt={generatedAt}
          benchmarksGeneratedAt={bench.generatedAt}
          measuredCount={bench.measuredCount}
          scoreFit={scoreFit}
        />
        <CatalogLegend id="how-to-read" />
        <BenchmarkReference id="benchmarks" />
      </div>
    </section>
  );
}
