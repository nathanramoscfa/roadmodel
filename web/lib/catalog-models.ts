// web/lib/catalog-models.ts
//
// Server-only adapter: reads data/catalog.json and projects it to the small,
// serializable ModelRow[] the /models page passes to the client table. Importing
// catalog.json here (not in the client component) keeps it out of the client
// bundle — the same pattern as lib/api-providers.ts and lib/subscriptions.ts.
import catalog from "@/data/catalog.json";
import benchmarks from "@/data/benchmarks.json";
import effortTokens from "@/data/effort-tokens.json";
import effortRatings from "@/data/effort-ratings.json";
import indexEstimates from "@/data/index-estimates.json";
import configurationDoc from "@/data/agent-configurations.json";

import {
  CATEGORY_ORDER,
  modelProvider,
  platformProvider,
  RATING_RANK,
  type AgentConfigurationRow,
  type Category,
  type CostTier,
  type ModelRow,
  type Rating,
} from "@/lib/catalog-fields";
import { extractAaIndex } from "@/lib/benchmark-scores";
import {
  fitScoreModel,
  GRID_COLUMNS,
  newUntil,
  scoreFor,
  type BenchKey,
  type BenchRow,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { withFrontier } from "@/lib/catalog-filter";
import { headlinePrice, resolveTokenMultipliers, type EffortTokensDoc } from "@/lib/pick-effort";
import { BENCHMARKS } from "@/lib/glossary";
import { compareVersions, isNewer, version } from "@/lib/series";

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

// A superseded model leaves the catalog on its `retires_on` day
// (update/build_catalog.py dates it from RETIRE_AFTER_DAYS; the benchmark cron
// then drops the row). Hiding it here from that UTC day on keeps the page right
// even while a stale data/catalog.json still lists it.
export function pastLeaveDate(retiresOn: string | null | undefined, now: Date): boolean {
  return !!retiresOn && now.toISOString().slice(0, 10) >= retiresOn;
}

function liveModels(now: Date = new Date()): RawModel[] {
  return MODELS.filter((m) => !pastLeaveDate(m.retires_on, now));
}

interface RawMethod {
  id?: string;
  name?: string;
  provider?: string;
  provider_jurisdiction: string;
  supports_models: string[];
  default_effort_by_model?: Record<string, string>;
}
const RAW_METHODS = (catalog as { access_methods?: RawMethod[] }).access_methods ?? [];

// The open-weight models: the ones a local method (Ollama, on the operator's
// own hardware) serves. The selector curates that list by licence, so the
// recommender's local option and this page's Weights filter read one list.
const OPEN_WEIGHTS = new Set(
  RAW_METHODS
    .filter((m) => m.provider_jurisdiction === "local")
    .flatMap((m) => m.supports_models),
);

function defaultEffortsFor(id: string): { surface: string; effort: string }[] | undefined {
  const seen = new Set<string>();
  const out: { surface: string; effort: string }[] = [];
  for (const method of RAW_METHODS) {
    const effort = method.default_effort_by_model?.[id];
    const surface = method.name;
    if (!effort || !surface || seen.has(surface)) continue;
    seen.add(surface);
    out.push({ surface, effort });
  }
  return out.length > 0 ? out : undefined;
}

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

// roadmodel's day-one estimate of an unmeasured model's AA Index, from its
// launch table (docs/index-estimates.json, src/roadmodel/estimate.py).
interface RawEstimate {
  index: number;
  band: number;
  method?: string;
  anchors: string[];
  // The top level the model's effort dials offer: the setting a vendor's
  // launch table reports, and the one the recommender places it at.
  effort?: string | null;
  // The models whose launch tables placed it, when its own table is too thin.
  via?: string[];
  // Its estimated letter figures (benchmarks.json keys, as fractions), from its
  // own launch table.
  figures?: Record<string, number>;
}
const ESTIMATES = (indexEstimates as { models?: Record<string, RawEstimate> }).models ?? {};

// The estimate for a model AA has not measured, rounded to a whole point (its
// band is about four), or null when its launch table is too thin.
export function estimateFor(
  id: string,
): { index: number; band: number; method: string; anchors: string[]; effort: string | null; via: string[] } | null {
  const e = ESTIMATES[id];
  if (!e || typeof e.index !== "number" || !Number.isFinite(e.index)) return null;
  return {
    index: Math.round(e.index),
    band: e.band,
    method: e.method ?? "anchors",
    anchors: e.anchors ?? [],
    effort: e.effort ?? null,
    via: e.via ?? [],
  };
}

// The derived categories a launch-table estimate letters (update/derive_ratings.py
// estimated_letters): planning on the index, the others where the model's own
// launch table places the category's benchmark.
const ESTIMATED_FIGURES: [Category, string[]][] = [
  ["coding", ["scicode", "terminalbench_v4_0"]],
  ["planning", []],
  ["agentic", ["terminalbench_v4_0"]],
  ["long-context", ["lcr"]],
  ["knowledge", ["hle"]],
];

export function estimatedCategories(id: string): Category[] {
  const e = ESTIMATES[id];
  if (!e || typeof e.index !== "number" || !Number.isFinite(e.index)) return [];
  const figures = e.figures ?? {};
  return ESTIMATED_FIGURES.filter(([, keys]) => keys.every((k) => typeof figures[k] === "number")).map(
    ([cat]) => cat,
  );
}

// Each effort's output-token multiplier (docs/effort-tokens.json,
// update/measure_effort_tokens.py): measured, else derived, else inherited
// day-one from the newest same-series predecessor.
const TOKEN_DOC = effortTokens as EffortTokensDoc;

const EFFORT_RATINGS =
  (effortRatings as { models?: Record<string, Record<string, Partial<Record<Category, Rating>>>> })
    .models ?? {};

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

// The model whose AA row an unmeasured later version stands on until AA
// measures it: the newest earlier version of its series in the snapshot, the
// rule /recommend ranks by (src/roadmodel/scoring.py inherit_unmeasured).
// Null for a model in the snapshot, and for a new series.
export function inheritedSource(id: string): string | null {
  if (BENCH[id]) return null;
  const older = Object.keys(BENCH).filter((m) => isNewer(m, id));
  if (older.length === 0) return null;
  return older.sort((a, b) => compareVersions(version(b), version(a)) || (a < b ? 1 : a > b ? -1 : 0))[0];
}

function nameOf(id: string): string {
  return MODELS.find((m) => m.id === id)?.name ?? BENCH[id]?.aa_name ?? id;
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

interface RawConfiguration {
  id: string;
  name: string;
  platform_id: string;
  model_id: string | null;
  effort: string | null;
  settings: Record<string, string>;
  roles: { role: string; model: string }[];
  source: string;
  availability: string;
  description: string;
  benchmark_note?: AgentConfigurationRow["configuration"]["benchmarkNote"];
  evidence: {
    configuration_id: string;
    source: string;
    aa_index?: { value: number; kind: "measured" | "estimated"; band?: number };
    price?: { input_per_1m: number; output_per_1m: number };
    grades?: Partial<Record<Category, Rating>>;
  } | null;
}

function configurationRows(): AgentConfigurationRow[] {
  return (configurationDoc.configurations as RawConfiguration[]).flatMap((entry) => {
    const platform = RAW_METHODS.find((method) => method.id === entry.platform_id);
    if (!platform?.name) return [];
    const evidence = entry.evidence?.configuration_id === entry.id && entry.evidence.source.startsWith("https://")
      ? entry.evidence : null;
    const index = evidence?.aa_index;
    const validIndex = index && Number.isFinite(index.value) && index.value >= 0 && index.value <= 100 &&
      (index.kind === "measured" || (index.kind === "estimated" && (index.band ?? 0) > 0 && (index.band ?? 0) <= 100));
    const price = evidence?.price;
    const validPrice = price && Number.isFinite(price.input_per_1m) && price.input_per_1m >= 0 &&
      Number.isFinite(price.output_per_1m) && price.output_per_1m >= 0.000001;
    const output = validPrice ? price.output_per_1m : null;
    return [{
      id: entry.id,
      name: entry.name,
      provider: platformProvider(platform.provider ?? "")?.label ?? null,
      jurisdiction: platform.provider_jurisdiction,
      open_weights: false,
      input_price_per_1m: validPrice ? price.input_per_1m : null,
      output_price_per_1m: output,
      cache_read_per_1m: null,
      tier_cost: output === null ? null : output < 10 ? "low" : output < 15 ? "medium" : output < 25 ? "high" : "very-high",
      tiers: Object.fromEntries(CATEGORY_ORDER.flatMap((cat) => {
        const grade = evidence?.grades?.[cat];
        return grade && Object.hasOwn(RATING_RANK, grade) ? [[cat, grade]] : [];
      })),
      configuration: {
        platform: platform.name,
        pickerModel: entry.model_id ? nameOf(entry.model_id) : entry.name,
        effort: entry.effort,
        settings: entry.settings,
        roles: entry.roles,
        availability: entry.availability,
        source: entry.source,
        evidenceSource: evidence?.source ?? null,
        benchmarkNote: entry.benchmark_note,
      },
      headline_benchmarks: "",
      pricing_notes: "",
      best_for: entry.description,
      aa_index: validIndex ? index.value : null,
      aa_index_source: validIndex ? (index.kind === "estimated" ? "estimated" : "cited") : null,
      aa_index_band: validIndex ? index.band ?? null : null,
      aa_index_effort: entry.effort,
      bench: null,
      value_score: null,
      value_frontier: false,
      value_beaten_by: null,
      superseded_by: null,
      superseded_on: null,
      retires_on: null,
      added_on: null,
      new_until: null,
    }];
  });
}

function fullyRated(row: AgentConfigurationRow): row is AgentConfigurationRow & ModelRow {
  return row.aa_index !== null && row.input_price_per_1m !== null &&
    row.output_price_per_1m !== null && row.tier_cost !== null &&
    CATEGORY_ORDER.every((cat) => row.tiers[cat] !== undefined);
}

export function getUnscoredConfigurations(): AgentConfigurationRow[] {
  return configurationRows().filter((row) => !fullyRated(row));
}

// `now` decides which models carry the "New" tag (lib/benchmark-grid
// newUntil); the page renders per request, so the tag clears on its own.
export function getModelRows(now: Date = new Date()): ModelRow[] {
  const rows: ModelRow[] = liveModels(now).map((m) => {
    const prose = m.headline_benchmarks ?? "";
    const bench = benchRowFor(m.id);
    const measured = bench?.values.artificial_analysis_intelligence_index ?? null;
    const cited = measured === null ? extractAaIndex(prose) : null;
    // Unmeasured: roadmodel's estimate from the launch table, else the earlier
    // version's index. Either is shown ≈; the grid columns and the effort rows
    // stay AA's measurements of this model.
    const source = measured === null && cited === null ? inheritedSource(m.id) : null;
    const estimate = measured === null && cited === null ? estimateFor(m.id) : null;
    const inheritedIndex = source && !estimate ? BENCH[source].evaluations[INDEX_KEY] : null;
    const inherited = typeof inheritedIndex === "number" && Number.isFinite(inheritedIndex) ? inheritedIndex : null;
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
      aa_index: measured ?? cited ?? estimate?.index ?? inherited,
      aa_index_source:
        measured !== null
          ? "snapshot"
          : cited !== null
            ? "cited"
            : estimate
              ? "estimated"
              : inherited !== null
                ? "inherited"
                : null,
      aa_inherited_from: (inherited !== null || estimate) && source ? nameOf(source) : null,
      aa_index_band: estimate?.band ?? null,
      aa_estimate_method: estimate?.method ?? null,
      aa_estimate_anchors: estimate ? estimate.anchors.map(nameOf) : null,
      aa_estimate_via: estimate && estimate.via.length ? estimate.via.map(nameOf) : null,
      aa_estimated_categories: estimate ? estimatedCategories(m.id) : null,
      aa_estimated_figures: estimate
        ? ((ESTIMATES[m.id]?.figures as Partial<Record<BenchKey, number>> | undefined) ?? null)
        : null,
      aa_index_by_effort: indexByEffort(m.id),
      aa_index_effort: measured !== null ? (BENCH[m.id]?.aa_effort ?? null) : (estimate?.effort ?? null),
      token_multiplier_by_effort: resolveTokenMultipliers(m.id, TOKEN_DOC),
      default_efforts: defaultEffortsFor(m.id),
      tiers_by_effort: EFFORT_RATINGS[m.id],
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
  const marked = withFrontier([...rows, ...configurationRows().filter(fullyRated)]);
  const fit = getScoreFit(marked);
  for (const r of marked) {
    r.value_score = scoreFor(
      fit,
      headlinePrice(r),
      r.aa_index,
    );
  }
  return marked;
}

// The market fit behind the Score column, over the rows given (the page passes
// the same rows it renders so the header stats match the cells). The fit is
// drawn through AA's own figures: an inherited index copies another model's
// point and an estimate is not a measurement, so it leaves both out. An
// estimated model still gets a Score against that line.
export function getScoreFit(
  rows: readonly (Pick<ModelRow, "input_price_per_1m" | "output_price_per_1m" | "aa_index"> &
    Partial<Pick<ModelRow, "aa_index_source" | "aa_index_effort" | "token_multiplier_by_effort" | "configuration">>)[],
): ScoreFit | null {
  return fitScoreModel(
    rows.flatMap((r) => r.configuration || r.aa_index_source === "inherited" || r.aa_index_source === "estimated"
      ? [] : [{ price: headlinePrice(r), index: r.aa_index }]),
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
  for (const m of liveModels()) {
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
  return liveModels().filter((m) => m.jurisdiction === code)
    .map((m) => m.name)
    .sort();
}

export function getBenchmarkMeta(): BenchmarkMeta {
  return {
    generatedAt: formatStamp((benchmarks as { generated_at_utc?: string }).generated_at_utc ?? ""),
    measuredCount: liveModels().filter((m) => BENCH[m.id]).length,
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
  const models = liveModels();
  for (const m of models) {
    const provider = modelProvider(m.id);
    if (provider) providerLabels.set(provider.key, provider.label);
    if (m.jurisdiction) jurisdictions.add(m.jurisdiction);
  }
  const providers = [...providerLabels.values()].sort((a, b) =>
    a.localeCompare(b),
  );
  return {
    modelCount: models.length,
    providerCount: providers.length,
    providers,
    jurisdictionCount: jurisdictions.size,
    categoryCount: CATEGORY_ORDER.length,
    benchmarkCount: BENCHMARKS.length,
    generatedAt: getCatalogGeneratedAt(),
  };
}
