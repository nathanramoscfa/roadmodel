// web/components/ModelsExplorer.tsx
//
// The /models page's interactive half: the catalog table, the per-tier Score
// charts and the frontier chart, driven by ONE set of filters. Provider,
// Jurisdiction (a checkbox per code, all checked to start) and Cost tier are
// set in the table's controls and applied to all three, so unchecking CN
// leaves the US + EU models in the table and in every chart.
//
// What each filter changes is set out in lib/catalog-filter: Provider and
// Jurisdiction choose the pool the frontier is recomputed over; Cost tier
// narrows what is shown; the Score is the whole-catalog fit throughout.
"use client";

import { useMemo, useState } from "react";

import type { ScoreFit } from "@/lib/benchmark-grid";
import type { ModelRow } from "@/lib/catalog-fields";
import {
  allFilters,
  filterSummary,
  inPool,
  jurisdictionCodes,
  poolScope,
  withFrontier,
  type CatalogFilters,
} from "@/lib/catalog-filter";
import type { ChartFilter } from "./chart-kit";
import { FrontierChart } from "./FrontierChart";
import { ModelCatalog } from "./ModelCatalog";
import { FrontierScope } from "./ScoreCards";
import { ScoreCharts } from "./ScoreCharts";

export function ModelsExplorer({
  models,
  generatedAt,
  benchmarksGeneratedAt,
  measuredCount,
  scoreFit,
}: {
  models: ModelRow[];
  generatedAt: string;
  benchmarksGeneratedAt: string;
  measuredCount: number;
  scoreFit: ScoreFit | null;
}) {
  const jurisdictions = useMemo(() => jurisdictionCodes(models), [models]);
  const [filters, setFilters] = useState<CatalogFilters>(() => allFilters(jurisdictions));

  const scope = poolScope(filters, jurisdictions);
  // The frontier's pool. Unnarrowed, the server's whole-catalog marks stand.
  const pool = useMemo(
    () => (scope === null ? models : withFrontier(models.filter((m) => inPool(m, filters)))),
    [models, filters, scope],
  );
  const shown = useMemo(
    () => (filters.cost === "all" ? pool : pool.filter((m) => m.tier_cost === filters.cost)),
    [pool, filters.cost],
  );

  const summary = filterSummary(filters, jurisdictions);
  const clear = () => setFilters(allFilters(jurisdictions));
  const chartFilter: ChartFilter | null = summary ? { summary, onClear: clear } : null;

  return (
    <FrontierScope.Provider value={scope}>
      <div className="space-y-8">
        <ModelCatalog
          models={models}
          shown={shown}
          filters={filters}
          jurisdictions={jurisdictions}
          onFiltersChange={setFilters}
          filterSummary={summary}
          onClearFilters={clear}
          scope={scope}
          generatedAt={generatedAt}
          benchmarksGeneratedAt={benchmarksGeneratedAt}
          measuredCount={measuredCount}
          scoreFit={scoreFit}
        />
        <ScoreCharts rows={shown} pool={pool} fit={scoreFit} filter={chartFilter} />
        <FrontierChart rows={shown} pool={pool} fit={scoreFit} filter={chartFilter} />
      </div>
    </FrontierScope.Provider>
  );
}
