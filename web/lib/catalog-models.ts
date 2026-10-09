// web/lib/catalog-models.ts
//
// Server-only adapter: reads data/catalog.json and projects it to the small,
// serializable ModelRow[] the /models page passes to the client table. Importing
// catalog.json here (not in the client component) keeps it out of the client
// bundle — the same pattern as lib/api-providers.ts and lib/subscriptions.ts.
import catalog from "@/data/catalog.json";
import benchmarks from "@/data/benchmarks.json";
import effortTokens from "@/data/effort-tokens.json";

import {
  CATEGORY_ORDER,
  modelProvider,
  type Category,
  type CostTier,
  type ModelRow,
  type Rating,
} from "@/lib/catalog-fields";
import { extractAaIndex } from "@/lib/benchmark-scores";
import {
  blendedPrice,
  fitScoreModel,
  GRID_COLUMNS,
  newUntil,
  scoreFor,
  type BenchKey,
  type BenchRow,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { withFrontier } from "@/lib/catalog-filter";
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
  superseded_by?: string | null;
  superseded_on?: string | null;
  retires_on?: string | null;
  added_on?: string | null;
}

const MODELS = (catalog as { models?: RawModel[] }).models ?? [];

interface RawMethod {
  provider_jurisdiction: string;
  supports_models: string[];
}
// The open-weight models: the ones a local method (Ollama, on the operator's
// own hardware) serves. The selector curates that list by licence, so the
// recommender's local option and this page's Weights filter read one list.
const OPEN_WEIGHTS = new Set(
  ((catalog as { access_methods?: RawMethod[] }).access_methods ?? [])
    .filter((m) => m.provider_jurisdiction === "local")
    .flatMap((m) => m.supports_models),
);

interface RawBench {
  aa_slug: string;
  aa_name: string;
  release_date?: string | null;
  evaluations: Record<string, number | null>;
  median_output_tokens_per_second: number | null;
  median_time_to_first_token_seconds: number | null;
  // The effort AA ran this row at, and its rows at the model's other efforts
  // (update/fetch_aa_benchmarks.py, schema 2).
  aa_effort?: string | null;
  effort_variants?: Record<string, { evaluations?: Record<string, number | null> }>;
}
const BENCH = (benchmarks as { models?: Record<string, RawBench> }).models ?? {};

const INDEX_KEY = "artificial_analysis_intelligence_index";

// Each effort's measured output-token multiplier (docs/effort-tokens.json,
// update/measure_effort_tokens.py), or undefined when it was not measured.
const TOKENS =
  (effortTokens as { models?: Record<string, { levels?: Record<string, { multiplier?: number }> }> })
    .models ?? {};

function multiplierByEffort(id: string): Record<string, number> | undefined {
  const out: Record<string, number> = {};
  for (const [level, row] of Object.entries(TOKENS[id]?.levels ?? {})) {
    const v = row.multiplier;
    if (typeof v === "number" && Number.isFinite(v) && v > 0) out[level] = v;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

// The AA Index at each effort AA measured the model at, or undefined when it
// names none.
function indexByEffort(id: string): Record<string, number> | undefined {
  const raw = BENCH[id];
  if (!raw) return undefined;
  const out: Record<string, number> = {};
  for (const [level, row] of Object.entries(raw.effort_variants ?? {})) {
    const v = row.evaluations?.[INDEX_KEY];
    if (typeof v === "number" && Number.isFinite(v)) out[level] = v;
  }
  const head = raw.evaluations[INDEX_KEY];
  if (raw.aa_effort && typeof head === "number" && Number.isFinite(head)) out[raw.aa_effort] = head;
  return Object.keys(out).length > 0 ? out : undefined;
}

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
  return { aa_slug: raw.aa_slug, aa_name: raw.aa_name, release_date: raw.release_date ?? null, values };
}

// `now` decides which models carry the "New" tag (lib/benchmark-grid
// newUntil); the page renders per request, so the tag clears on its own.
export function getModelRows(now: Date = new Date()): ModelRow[] {
  const rows: ModelRow[] = MODELS.map((m) => {
    const prose = m.headline_benchmarks ?? "";
    const bench = benchRowFor(m.id);
    const measured = bench?.values.artificial_analysis_intelligence_index ?? null;
    const cited = measured === null ? extractAaIndex(prose) : null;
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
      open_weights: OPEN_WEIGHTS.has(m.id),
      headline_benchmarks: prose,
      pricing_notes: m.pricing_notes ?? "",
      best_for: m.best_for ?? "",
      aa_index: measured ?? cited,
      aa_index_source: measured !== null ? "snapshot" : cited !== null ? "cited" : null,
      aa_index_by_effort: indexByEffort(m.id),
      token_multiplier_by_effort: multiplierByEffort(m.id),
      bench,
      value_score: null,
      value_frontier: false,
      value_beaten_by: null,
      superseded_by: m.superseded_by ?? null,
      superseded_on: m.superseded_on ?? null,
      retires_on: m.retires_on ?? null,
      added_on: m.added_on ?? null,
      // Counted from the release AA dates; before AA lists the model, from
      // the day it joined the catalog.
      new_until: newUntil(bench?.release_date ?? m.added_on, now),
    };
  });
  // The frontier across the whole catalog; the page re-marks it over the
  // models its Provider and Jurisdiction filters keep (lib/catalog-filter).
  const marked = withFrontier(rows);
  const fit = getScoreFit(marked);
  for (const r of marked) {
    r.value_score = scoreFor(
      fit,
      r.tier_cost,
      blendedPrice(r.input_price_per_1m, r.output_price_per_1m),
      r.aa_index,
    );
  }
  return marked;
}

// The market fit behind the Score column, over the rows given (the page passes
// the same rows it renders so the header stats match the cells).
export function getScoreFit(
  rows: readonly Pick<ModelRow, "input_price_per_1m" | "output_price_per_1m" | "aa_index" | "tier_cost">[],
): ScoreFit | null {
  return fitScoreModel(
    rows.map((r) => ({
      price: blendedPrice(r.input_price_per_1m, r.output_price_per_1m),
      index: r.aa_index,
      tier: r.tier_cost,
    })),
  );
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

// Models the catalog places in a given jurisdiction, by BOTH id and display
// name — the two spellings an API payload can carry. Derived, never listed:
// a hardcoded set silently stops filtering when the catalog moves on (the cn
// guard named only `kimi-k2.5`, retired in favour of K2.7 / K3, so every other
// cn model would have slipped through a "no cn" preference).
export function modelsInJurisdiction(code: string): Set<string> {
  const out = new Set<string>();
  for (const m of MODELS) {
    if (m.jurisdiction !== code) continue;
    out.add(m.id);
    out.add(m.name);
  }
  return out;
}

// Display names only, for a caller that needs to NAME a model of a given
// jurisdiction (the E2E mock and the test that asserts on it derive the same
// name from this, so they cannot drift apart).
export function modelNamesInJurisdiction(code: string): string[] {
  return MODELS.filter((m) => m.jurisdiction === code)
    .map((m) => m.name)
    .sort();
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
