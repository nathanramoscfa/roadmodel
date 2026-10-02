// web/components/CatalogFilterBar.tsx
//
// The /models filters that choose which models the WHOLE page shows: Provider,
// Jurisdiction (a checkbox per code, all checked to start), Weights (All, Open,
// Closed) and Cost tier. The bar sits at the top of the page, above the
// frontier chart, the table and the Score charts, since all three follow it
// (ModelsExplorer owns the state; lib/catalog-filter says what each filter
// changes). The table's own controls (Search, Group by, Ratings / Benchmark
// scores) stay with the table in ModelCatalog.
"use client";

import { useMemo } from "react";

import { COST_TIER_DEFS, jurisdictionDef, WEIGHTS_DEFS, type CostTier, type ModelRow } from "@/lib/catalog-fields";
import type { CatalogFilters } from "@/lib/catalog-filter";

export const INPUT_CLASS =
  "rounded-md border border-brand-slate-300 dark:border-brand-slate-700 " +
  "bg-white dark:bg-brand-slate-800 px-3 py-2 text-sm shadow-sm " +
  "focus:border-brand-accent focus:outline-none focus:ring-1 focus:ring-brand-accent";

export const LABEL_CLASS =
  "flex flex-col gap-1 text-xs font-medium text-brand-slate-600 dark:text-brand-slate-300";

// The frame of a row of toggle buttons (Weights here, Group by in the table).
export const SEGMENTED_CLASS =
  "inline-flex self-start rounded-md border border-brand-slate-300 bg-white p-0.5 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800";

export function CatalogFilterBar({
  models,
  filters,
  jurisdictions,
  onFiltersChange,
}: {
  // Every catalog row: the Provider options.
  models: ModelRow[];
  filters: CatalogFilters;
  // The catalog's jurisdiction codes, in checkbox order.
  jurisdictions: string[];
  onFiltersChange: (next: CatalogFilters) => void;
}) {
  const providers = useMemo(
    () =>
      Array.from(new Set(models.map((m) => m.provider).filter((p): p is string => p !== null))).sort(
        (a, b) => a.localeCompare(b),
      ),
    [models],
  );

  function toggleJurisdiction(code: string) {
    const next = new Set(filters.jurisdictions);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    onFiltersChange({ ...filters, jurisdictions: next });
  }

  return (
    <div
      role="group"
      aria-label="Filter the models on this page"
      data-testid="catalog-filters"
      className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end"
    >
      <label className={LABEL_CLASS}>
        Provider
        <select
          value={filters.provider}
          onChange={(e) => onFiltersChange({ ...filters, provider: e.target.value })}
          aria-label="Filter by provider"
          className={INPUT_CLASS}
        >
          <option value="all">All</option>
          {providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <div className={LABEL_CLASS}>
        <span id="jurisdiction-label">Jurisdiction</span>
        <div role="group" aria-labelledby="jurisdiction-label" data-testid="jurisdiction-filter" className={SEGMENTED_CLASS}>
          {jurisdictions.map((j) => {
            const on = filters.jurisdictions.has(j);
            return (
              <label
                key={j}
                title={jurisdictionDef(j)}
                className={
                  "inline-flex cursor-pointer items-center gap-1.5 rounded px-2.5 py-1.5 text-sm font-medium transition-colors hover:text-brand-accent " +
                  (on ? "text-brand-slate-900 dark:text-brand-slate-50" : "text-brand-slate-400 dark:text-brand-slate-500")
                }
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggleJurisdiction(j)}
                  data-testid={`jurisdiction-${j}`}
                  className="h-3.5 w-3.5 cursor-pointer accent-brand-accent"
                />
                {j.toUpperCase()}
              </label>
            );
          })}
        </div>
      </div>
      <div className={LABEL_CLASS}>
        <span id="weights-label">Weights</span>
        <div role="group" aria-labelledby="weights-label" data-testid="weights-filter" className={SEGMENTED_CLASS}>
          {(["all", "open", "closed"] as const).map((w) => (
            <button
              key={w}
              type="button"
              data-testid={`weights-${w}`}
              aria-pressed={filters.weights === w}
              title={w === "all" ? "Every model, open- and closed-weight." : WEIGHTS_DEFS[w].definition}
              onClick={() => onFiltersChange({ ...filters, weights: w })}
              className={
                "rounded px-3 py-1.5 text-sm font-medium transition-colors " +
                (filters.weights === w
                  ? "bg-brand-accent text-white"
                  : "text-brand-slate-600 hover:text-brand-accent dark:text-brand-slate-300")
              }
            >
              {w === "all" ? "All" : WEIGHTS_DEFS[w].label}
            </button>
          ))}
        </div>
      </div>
      <label className={LABEL_CLASS}>
        Cost tier
        <select
          value={filters.cost}
          onChange={(e) => onFiltersChange({ ...filters, cost: e.target.value as "all" | CostTier })}
          aria-label="Filter by cost tier"
          className={INPUT_CLASS}
        >
          <option value="all">All</option>
          {(["low", "medium", "high", "very-high"] as const).map((t) => (
            <option key={t} value={t}>
              {COST_TIER_DEFS[t].label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
