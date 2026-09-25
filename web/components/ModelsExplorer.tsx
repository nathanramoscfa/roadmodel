// web/components/ModelsExplorer.tsx
//
// The /models page's interactive half: the catalog table, the frontier chart
// and the per-tier Score charts, driven by ONE set of filters. Provider,
// Jurisdiction (a checkbox per code, all checked to start) and Cost tier are
// set in the table's controls and applied to all three, so unchecking CN
// leaves the US + EU models in the table and in every chart.
//
// The page remembers them (lib/models-prefs): the server reads the saved
// choices from a cookie and passes them in, so the first render is already
// the visitor's view, and every change here is saved for the next visit.
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
import { filtersFromPrefs, prefsFromFilters, savePrefs, type ModelsPrefs } from "@/lib/models-prefs";
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
  prefs,
}: {
  models: ModelRow[];
  generatedAt: string;
  benchmarksGeneratedAt: string;
  measuredCount: number;
  scoreFit: ScoreFit | null;
  // The visitor's saved choices (defaults on a first visit).
  prefs: ModelsPrefs;
}) {
  const jurisdictions = useMemo(() => jurisdictionCodes(models), [models]);
  const [filters, setFilters] = useState<CatalogFilters>(() =>
    filtersFromPrefs(
      prefs,
      models.flatMap((m) => (m.provider ? [m.provider] : [])),
      jurisdictions,
    ),
  );
  function changeFilters(next: CatalogFilters) {
    setFilters(next);
    savePrefs(prefsFromFilters(next, jurisdictions));
  }

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
  const clear = () => changeFilters(allFilters(jurisdictions));
  const chartFilter: ChartFilter | null = summary ? { summary, onClear: clear } : null;

  return (
    <FrontierScope.Provider value={scope}>
      <div className="space-y-8">
        <ModelCatalog
          models={models}
          shown={shown}
          filters={filters}
          jurisdictions={jurisdictions}
          onFiltersChange={changeFilters}
          filterSummary={summary}
          onClearFilters={clear}
          scope={scope}
          generatedAt={generatedAt}
          benchmarksGeneratedAt={benchmarksGeneratedAt}
          measuredCount={measuredCount}
          scoreFit={scoreFit}
          initialGroupBy={prefs.groupBy}
          initialView={prefs.view}
        />
        {/* The frontier first (the whole market on one chart), then the Score
            charts that take it apart tier by tier. */}
        <FrontierChart rows={shown} pool={pool} fit={scoreFit} filter={chartFilter} />
        <ScoreCharts rows={shown} pool={pool} fit={scoreFit} filter={chartFilter} />
      </div>
    </FrontierScope.Provider>
  );
}
