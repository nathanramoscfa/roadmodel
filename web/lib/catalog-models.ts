// web/lib/catalog-models.ts
//
// Server-only adapter: reads data/catalog.json and projects it to the small,
// serializable ModelRow[] the /models page passes to the client table. Importing
// catalog.json here (not in the client component) keeps it out of the client
// bundle — the same pattern as lib/api-providers.ts and lib/subscriptions.ts.
import catalog from "@/data/catalog.json";
import benchmarks from "@/data/benchmarks.json";

import {
  CATEGORY_ORDER,
  modelProvider,
  type Category,
  type CostTier,
  type ModelRow,
  type Rating,
} from "@/lib/catalog-fields";
import { extractAaIndex } from "@/lib/benchmark-scores";
import { GRID_COLUMNS, paretoFrontier, type BenchKey, type BenchRow } from "@/lib/benchmark-grid";
import { BENCHMARKS } from "@/lib/glossary";

interface RawModel {
  id: string;
  name: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  cache_read_per_1m: number | null;
  tier_cost: string;
  tiers: Record<string, string>;
  jurisdiction: string;
  headline_benchmarks?: string;
  pricing_notes?: string;
  best_for?: string;
}

const MODELS = (catalog as { models?: RawModel[] }).models ?? [];

interface RawBench {
  aa_slug: string;
  aa_name: string;
  evaluations: Record<string, number | null>;
  median_output_tokens_per_second: number | null;
  median_time_to_first_token_seconds: number | null;
}
const BENCH = (benchmarks as { models?: Record<string, RawBench> }).models ?? {};

// Project a benchmarks.json entry to exactly the grid's columns. AA reports
// 0 tokens/s for endpoints it has not throughput-tested; that is "not
// measured", not a speed, so it becomes null like any other gap.
function benchRowFor(id: string): BenchRow | null {
  const raw = BENCH[id];
  if (!raw) return null;
  const values = {} as Record<BenchKey, number | null>;
  for (const col of GRID_COLUMNS) {
    let v: number | null | undefined;
    if (col.key === "median_output_tokens_per_second") {
      v = raw.median_output_tokens_per_second;
      if (v !== null && v !== undefined && v <= 0) v = null;
    } else {
      v = raw.evaluations[col.key];
    }
    values[col.key] = typeof v === "number" && Number.isFinite(v) ? v : null;
  }
  return { aa_slug: raw.aa_slug, aa_name: raw.aa_name, values };
}

export function getModelRows(): ModelRow[] {
  const rows = MODELS.map((m) => {
    const prose = m.headline_benchmarks ?? "";
    const bench = benchRowFor(m.id);
    return {
      id: m.id,
      name: m.name,
      provider: modelProvider(m.id)?.label ?? null,
      input_price_per_1m: m.input_price_per_1m,
      output_price_per_1m: m.output_price_per_1m,
      cache_read_per_1m: m.cache_read_per_1m ?? null,
      tier_cost: m.tier_cost as CostTier,
      tiers: m.tiers as Record<Category, Rating>,
      jurisdiction: m.jurisdiction,
      headline_benchmarks: prose,
      pricing_notes: m.pricing_notes ?? "",
      best_for: m.best_for ?? "",
      aa_index: bench?.values.artificial_analysis_intelligence_index ?? extractAaIndex(prose),
      bench,
      value_frontier: false,
    };
  });
  const frontier = paretoFrontier(
    rows.map((r) => ({ row: r, price: r.output_price_per_1m, index: r.aa_index })),
  );
  for (const f of frontier) f.row.value_frontier = true;
  return rows;
}

// "2026-06-21T12:53:54Z" → "2026-06-21 12:53 UTC". Falls back to the raw value.
function formatStamp(raw: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(raw);
  return m ? `${m[1]} ${m[2]} UTC` : raw;
}

export function getCatalogGeneratedAt(): string {
  return formatStamp((catalog as { generated_at_utc?: string }).generated_at_utc ?? "");
}

export interface BenchmarkMeta {
  generatedAt: string;
  // Catalog models with at least one AA figure.
  measuredCount: number;
}

export function getBenchmarkMeta(): BenchmarkMeta {
  return {
    generatedAt: formatStamp((benchmarks as { generated_at_utc?: string }).generated_at_utc ?? ""),
    measuredCount: MODELS.filter((m) => BENCH[m.id]).length,
  };
}

export interface CatalogStats {
  modelCount: number;
  // Distinct providers, plus their display labels (Anthropic, OpenAI, …) sorted.
  providerCount: number;
  providers: string[];
  // Distinct jurisdiction codes present (us / eu / cn).
  jurisdictionCount: number;
  categoryCount: number;
  benchmarkCount: number;
  generatedAt: string;
}

// Headline numbers for the home page, derived from the live catalog so they
// never drift as the daily refresh adds or re-prices models. Provider labels
// reuse the same modelProvider() inference the /models table links with.
export function getCatalogStats(): CatalogStats {
  const providerLabels = new Map<string, string>();
  const jurisdictions = new Set<string>();
  for (const m of MODELS) {
    const provider = modelProvider(m.id);
    if (provider) providerLabels.set(provider.key, provider.label);
    if (m.jurisdiction) jurisdictions.add(m.jurisdiction);
  }
  const providers = [...providerLabels.values()].sort((a, b) =>
    a.localeCompare(b),
  );
  return {
    modelCount: MODELS.length,
    providerCount: providers.length,
    providers,
    jurisdictionCount: jurisdictions.size,
    categoryCount: CATEGORY_ORDER.length,
    benchmarkCount: BENCHMARKS.length,
    generatedAt: getCatalogGeneratedAt(),
  };
}
