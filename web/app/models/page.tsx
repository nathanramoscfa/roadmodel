import { BenchmarkReference } from "@/components/BenchmarkReference";
import { CatalogLegend } from "@/components/CatalogLegend";
import { ModelCatalog } from "@/components/ModelCatalog";
import { getCatalogGeneratedAt, getModelRows } from "@/lib/catalog-models";

export const metadata = {
  title: "Models — roadmodel",
  description:
    "The full AI-model catalog roadmodel recommends from: pricing, the S→D per-category ratings, and the benchmark scores behind them — sortable, filterable, and sourced.",
};

export default function ModelsPage() {
  const models = getModelRows();
  const generatedAt = getCatalogGeneratedAt();

  return (
    <section className="mx-auto max-w-7xl px-6 py-12 sm:py-16">
      <header className="max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">roadmodel</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
          Model catalog
        </h1>
        <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
          Every model roadmodel recommends from — with pricing, the per-category{" "}
          <strong>S&nbsp;&rarr;&nbsp;D</strong> ratings, and the public-benchmark scores those
          ratings synthesize. The catalog is curated and re-priced automatically every day. Sort any
          column, filter by jurisdiction or cost, and hover any label or benchmark for its
          definition and source.
        </p>
      </header>

      <div className="mt-10 space-y-8">
        <CatalogLegend />
        <ModelCatalog models={models} generatedAt={generatedAt} />
        <BenchmarkReference id="benchmarks" />
      </div>
    </section>
  );
}
