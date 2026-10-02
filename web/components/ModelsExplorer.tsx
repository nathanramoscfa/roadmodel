// web/components/ModelsExplorer.tsx
//
// The /models page's interactive half, in reading order: the filters, the
// frontier chart (the whole market on one chart), the catalog table (its rows
// scroll in their own box), then the Score charts that take the frontier apart
// tier by tier. ONE set of filters drives all three: Provider, Jurisdiction (a
// checkbox per code, all checked to start), Weights (All, Open, Closed) and
// Cost tier sit in the bar at the top (CatalogFilterBar), so unchecking CN
// leaves the US + EU models in the table and in every chart, and Open leaves
// only the models you could run yourself, with the chart that changes right
// under the control. The table's Group by switch keeps its state here too,
// since the charts read it: grouped by quality, the frontier chart marks the
// table's ten-point AA Index bands, and the Score charts, one per cost tier
// either way, say why they stay by tier.
//
// The page remembers them (lib/models-prefs): the server reads the saved
// choices from a cookie and passes them in, so the first render is already
// the visitor's view, and every change here is saved for the next visit.
//
// What each filter changes is set out in lib/catalog-filter: Provider,
// Jurisdiction and Weights choose the pool the frontier is recomputed over; Cost tier
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
import {
  filtersFromPrefs,
  prefsFromFilters,
  savePrefs,
  type Grouping,
  type ModelsPrefs,
} from "@/lib/models-prefs";
import { CatalogFilterBar } from "./CatalogFilterBar";
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
  // The Group by choice: the table's header rows, and what the charts mark.
  const [grouping, setGrouping] = useState<Grouping>(prefs.grouping);
  function changeGrouping(next: Grouping) {
    setGrouping(next);
    savePrefs({ grouping: next });
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
        {/* The filters, then the frontier (the whole market on one chart)
            right under them, then the table, then the Score charts that take
            the frontier apart tier by tier. */}
        <CatalogFilterBar
          models={models}
          filters={filters}
          jurisdictions={jurisdictions}
          onFiltersChange={changeFilters}
        />
        <FrontierChart rows={shown} pool={pool} fit={scoreFit} filter={chartFilter} grouping={grouping} />
        <ModelCatalog
          models={models}
          shown={shown}
          filterSummary={summary}
          onClearFilters={clear}
          scope={scope}
          generatedAt={generatedAt}
          benchmarksGeneratedAt={benchmarksGeneratedAt}
          measuredCount={measuredCount}
          scoreFit={scoreFit}
          groupChoice={grouping}
          onGroupChoiceChange={changeGrouping}
          initialView={prefs.view}
        />
        <ScoreCharts rows={shown} pool={pool} fit={scoreFit} filter={chartFilter} grouping={grouping} />
      </div>
    </FrontierScope.Provider>
  );
}
