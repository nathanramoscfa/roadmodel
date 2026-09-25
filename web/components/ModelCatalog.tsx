// web/components/ModelCatalog.tsx
//
// The interactive catalog table for /models: client-side sort + filter, a toggle
// between the S→D ratings view and the uniform benchmark-scores grid, header
// tooltips (field name + definition + source via GlossaryTerm), and benchmark
// names auto-linkified through the glossary (segmentRationale) in the expanded
// row. Pure presentation — the server page passes the rows; no data import.
//
// Two views, one numeric layer:
//   Ratings — Model (sticky), Provider, Jurisdiction, Input, Output (cost tier
//     as a colored dot), AA Index (with a green ring for the cost/quality
//     frontier, which is catalog-wide), Score (cost-adjusted index residual
//     within the cost tier), then seven letter cells. The frontier ring sits
//     on the AA Index, not the Score, so a within-tier figure never carries a
//     whole-catalog mark; it is a ring, not a dot, so it never reads as the Low
//     tier's dot. Letters only: the uniform figures live in the grid, and the
//     category header's tooltip names which grid column is evidence for it.
//     Sorting a category orders by letter, then AA Index, then name.
//   Benchmark scores — the full AA grid: one column per evaluation, every value
//     on that column's scale, "—" only where AA has not measured the model.
//     Cells are colored by within-column quintile (lib/benchmark-grid bandFor)
//     so a glance reads the same way the letter badges do.
// Two groupings, each under a header row per group (the "Group by" switch):
//   Cost tier (the default: sorting by Score) — the best buy at your budget;
//     each model is read against its own price band (a raw AA Index sort puts
//     cheap models on top and invites "is this flash model really better than
//     the frontier one?").
//   Quality — ten-point AA Index bands, cheapest first: the cheapest way to
//     reach each level.
// Either way, when the top score at a group's prices belongs to a model
// outside it, the group's header names that model (topScoreSentence): each
// tier's Scores average zero, and the header shows it without a hover.
// Cache-read price, tier name, pricing notes, "best for", and the benchmarks
// the cron cited (mixed sources — evidence for the letters, not a scale) live
// in the expanded row so they add no width. Fits a 1024px viewport.
//
// The Provider, Jurisdiction and Cost tier filters belong to ModelsExplorer,
// which applies them to the table AND both chart panels; the table renders
// the controls and receives the rows they keep (frontier re-marked over the
// Provider + Jurisdiction pool, lib/catalog-filter). Jurisdiction is a
// checkbox per code, all checked to start, so any combination (US + EU, say)
// is one click away. Search stays the table's own. Group by and the
// Ratings / Benchmark scores view are saved for the next visit
// (lib/models-prefs), like the filters.
"use client";

import { Fragment, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Info } from "lucide-react";

import { RATING_SCALE, segmentRationale } from "@/lib/glossary";
import {
  AA_HOME,
  bandFor,
  benchPoints,
  blendedPrice,
  benchSortValue,
  CATEGORY_FIGURE,
  DERIVED_CATEGORIES,
  formatBench,
  formatQualityBand,
  formatScore,
  GRID_COLUMN_BY_KEY,
  GRID_COLUMNS,
  QUALITY_BAND_WIDTH,
  qualityBand,
  type Band,
  type BenchColumn,
  type ScoreFit,
  type BenchKey,
} from "@/lib/benchmark-grid";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_COLORS,
  COST_TIER_DEFS,
  COST_TIER_DOT,
  COST_TIER_RANK,
  FIELD_DEFS,
  type CostTier,
  formatPrice,
  jurisdictionDef,
  modelProvider,
  RATING_COLORS,
  RATING_RANK,
  type Category,
  type ModelRow,
} from "@/lib/catalog-fields";
import type { CatalogFilters } from "@/lib/catalog-filter";
import { savePrefs, type Grouping, type View } from "@/lib/models-prefs";
import { HoverCard } from "./FloatingCard";
import { GlossaryTerm } from "./GlossaryTerm";
import { IndexCard, ScoreBreakdownCard, SupersededCard, topScoreSentence } from "./ScoreCards";

const RATING_MEANING: Record<string, string> = Object.fromEntries(
  RATING_SCALE.map((r) => [r.rating, r.meaning]),
);

// Grid cell tint by within-column quintile, on the same palette as the letter
// badges so green/blue/grey/amber/rose mean the same thing in both views.
const BAND_CLASS: Record<Band, string> = {
  5: RATING_COLORS.S,
  4: RATING_COLORS.A,
  3: RATING_COLORS.B,
  2: RATING_COLORS.C,
  1: RATING_COLORS.D,
};
const BAND_LABEL: Record<Band, string> = {
  5: "top 20% of measured models",
  4: "60–80th percentile",
  3: "40–60th percentile",
  2: "20–40th percentile",
  1: "bottom 20% of measured models",
};

type SortKey =
  | "name"
  | "provider"
  | "jurisdiction"
  | "input_price_per_1m"
  | "output_price_per_1m"
  | "aa_index"
  | "value"
  // Not a column: the "Group by: Quality" switch (AA Index band, cheapest first).
  | "quality"
  | Category
  | BenchKey;
type SortDir = "asc" | "desc";

const BENCH_KEYS = new Set<string>(GRID_COLUMNS.map((c) => c.key));
function isBenchKey(key: SortKey): key is BenchKey {
  return BENCH_KEYS.has(key);
}

const INPUT_CLASS =
  "rounded-md border border-brand-slate-300 dark:border-brand-slate-700 " +
  "bg-white dark:bg-brand-slate-800 px-3 py-2 text-sm shadow-sm " +
  "focus:border-brand-accent focus:outline-none focus:ring-1 focus:ring-brand-accent";

const LABEL_CLASS =
  "flex flex-col gap-1 text-xs font-medium text-brand-slate-600 dark:text-brand-slate-300";

const BADGE_CLASS =
  "inline-flex min-w-[2rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold";

// The sticky Model column needs an opaque background so rows scrolling under it
// (narrow viewports only) do not bleed through; it matches the row hover tint.
// The row is a NAMED group (group/row): a bare `group` would also satisfy the
// `group-hover` selectors inside GlossaryTerm and pop every tooltip in the row.
const STICKY_CELL =
  "sticky left-0 z-10 bg-white group-hover/row:bg-brand-slate-50 dark:bg-brand-slate-900 dark:group-hover/row:bg-brand-slate-800";
const STICKY_HEAD = "sticky left-0 z-10 bg-brand-slate-50 dark:bg-brand-slate-800";

// The header row that opens a group (a cost tier, a quality band).
const GROUP_HEADER_CELL =
  "bg-brand-slate-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-brand-slate-600 dark:bg-brand-slate-800/60 dark:text-brand-slate-300";
const GROUP_HEADER_DETAIL =
  "ml-2 font-normal normal-case tracking-normal text-brand-slate-500 dark:text-brand-slate-400";

function nextDir(key: SortKey, active: SortKey, dir: SortDir): SortDir {
  if (key === active) return dir === "asc" ? "desc" : "asc";
  // New column: text sorts A→Z, everything numeric/ranked sorts best-first.
  return key === "name" || key === "provider" || key === "jurisdiction" ? "asc" : "desc";
}

function valueFor(row: ModelRow, key: SortKey): number | string {
  if (isBenchKey(key)) {
    // Missing figures sort last in BOTH directions (handled in the comparator).
    return benchSortValue(row.bench, key) ?? Number.NaN;
  }
  switch (key) {
    case "name":
      return row.name.toLowerCase();
    case "provider":
      return (row.provider ?? "\uffff").toLowerCase(); // unknown provider sorts last
    case "jurisdiction":
      return row.jurisdiction;
    case "input_price_per_1m":
      return row.input_price_per_1m;
    case "output_price_per_1m":
      return row.output_price_per_1m;
    case "aa_index":
      return row.aa_index ?? -1;
    case "value":
      // Sorted via compareNullable above; this branch is only reached by the
      // generic path, where a missing score must sort last.
      return row.value_score ?? Number.NEGATIVE_INFINITY;
    case "quality":
      // Sorted by its own branch in the comparator; here for completeness.
      return qualityBand(row.aa_index) ?? -1;
    default:
      return RATING_RANK[row.tiers[key]];
  }
}

// Compare two nullable figures in the sort direction with nulls LAST either
// way (a missing measurement is not a low score). 0 when nothing separates.
function compareNullable(x: number | null, y: number | null, dir: 1 | -1): number {
  if (x !== null && y !== null) return x === y ? 0 : (x < y ? -1 : 1) * dir;
  if (x !== null) return -1;
  if (y !== null) return 1;
  return 0;
}

// Within one letter of a category column: the AA Index (missing last); the
// caller falls through to the name.
function categoryTieBreak(a: ModelRow, b: ModelRow, dir: 1 | -1): number {
  return compareNullable(a.aa_index, b.aa_index, dir);
}

function isCategory(key: SortKey): key is Category {
  return (CATEGORY_ORDER as string[]).includes(key);
}

// "$0.26" / "$10" — the blended price in a group header, trimmed like the
// price columns.
function formatBlended(v: number): string {
  return `$${Number(v.toFixed(2)).toString()}`;
}

// "$25–$50", or "$25" when every row in the group costs the same.
function priceRange(lo: number, hi: number, fmt: (v: number) => string): string {
  return lo === hi ? fmt(lo) : `${fmt(lo)}–${fmt(hi)}`;
}

interface GroupStats {
  count: number;
  outLo: number;
  outHi: number;
  blendLo: number;
  blendHi: number;
  // Set when the top score at the group's prices belongs to a model outside
  // it: the sentence the header shows (topScoreSentence).
  note: string | null;
}

// The key a row falls under in each of the two groupings.
function groupKey(m: ModelRow, grouping: Grouping): string {
  return grouping === "tier" ? m.tier_cost : String(qualityBand(m.aa_index) ?? "none");
}

// Color the score by how far outside the fit's noise band it sits: beyond +σ
// reads green, beyond −σ reads muted; inside the band is plain — the same
// "within σ is a tie" rule the header states.
function scoreTone(score: number | null, fit: ScoreFit | null): string {
  if (score === null || !fit) return "";
  if (score >= fit.sigma) return "font-semibold text-emerald-700 dark:text-emerald-300";
  if (score <= -fit.sigma) return "text-brand-slate-400 dark:text-brand-slate-500";
  return "text-brand-slate-700 dark:text-brand-slate-200";
}

export function ModelCatalog({
  models,
  shown,
  filters,
  jurisdictions,
  onFiltersChange,
  filterSummary,
  onClearFilters,
  scope,
  generatedAt,
  benchmarksGeneratedAt,
  measuredCount,
  scoreFit,
  initialGroupBy,
  initialView,
}: {
  // Every catalog row: the filter options, the grid's bands, the totals.
  models: ModelRow[];
  // The rows the Provider, Jurisdiction and Cost tier filters keep.
  shown: ModelRow[];
  filters: CatalogFilters;
  // The catalog's jurisdiction codes, in checkbox order.
  jurisdictions: string[];
  onFiltersChange: (next: CatalogFilters) => void;
  // Every active filter in a line; null when none is.
  filterSummary: string | null;
  onClearFilters: () => void;
  // Which models the frontier compares (lib/catalog-filter poolScope); null
  // for the whole catalog.
  scope: string | null;
  generatedAt: string;
  benchmarksGeneratedAt: string;
  measuredCount: number;
  scoreFit: ScoreFit | null;
  // The visitor's saved Group by and view.
  initialGroupBy: Grouping;
  initialView: View;
}) {
  const [view, setView] = useState<View>(initialView);
  const [sortKey, setSortKey] = useState<SortKey>(initialGroupBy === "quality" ? "quality" : "value");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

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

  // Sorted measured values per grid column, over the WHOLE catalog (not the
  // filtered rows), so a cell's band does not change when a filter is applied.
  const columnValues = useMemo(() => {
    const out = {} as Record<BenchKey, number[]>;
    for (const col of GRID_COLUMNS) {
      out[col.key] = models
        .map((m) => benchSortValue(m.bench, col.key))
        .filter((v): v is number => v !== null)
        .sort((x, y) => x - y);
    }
    return out;
  }, [models]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = shown.filter(
      (m) =>
        !needle ||
        m.name.toLowerCase().includes(needle) ||
        (m.provider ?? "").toLowerCase().includes(needle) ||
        m.headline_benchmarks.toLowerCase().includes(needle),
    );
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (isBenchKey(sortKey)) {
        const t = compareNullable(benchSortValue(a.bench, sortKey), benchSortValue(b.bench, sortKey), dir);
        if (t !== 0) return t;
        return a.name.localeCompare(b.name);
      }
      if (sortKey === "aa_index") {
        // Nullable figure: unmeasured rows last in either direction.
        const t = compareNullable(a.aa_index, b.aa_index, dir);
        if (t !== 0) return t;
        return a.name.localeCompare(b.name);
      }
      if (sortKey === "quality") {
        // Grouped by AA Index band, best band first; within a band, cheapest
        // (blended) first, the higher index breaking a price tie; unmeasured
        // rows last, in their own group.
        const band = compareNullable(qualityBand(a.aa_index), qualityBand(b.aa_index), -1);
        if (band !== 0) return band;
        const price =
          blendedPrice(a.input_price_per_1m, a.output_price_per_1m) -
          blendedPrice(b.input_price_per_1m, b.output_price_per_1m);
        if (price !== 0) return price;
        const index = compareNullable(a.aa_index, b.aa_index, -1);
        if (index !== 0) return index;
        return a.name.localeCompare(b.name);
      }
      if (sortKey === "value") {
        // Grouped by cost tier (priciest tier first when descending), then by
        // score within the tier with unmeasured rows last in either direction.
        const tierDiff = (COST_TIER_RANK[a.tier_cost] - COST_TIER_RANK[b.tier_cost]) * dir;
        if (tierDiff !== 0) return tierDiff;
        const t = compareNullable(a.value_score, b.value_score, dir);
        if (t !== 0) return t;
        return a.name.localeCompare(b.name);
      }
      const av = valueFor(a, sortKey);
      const bv = valueFor(b, sortKey);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      if (isCategory(sortKey)) {
        const tie = categoryTieBreak(a, b, dir);
        if (tie !== 0) return tie;
      }
      return a.name.localeCompare(b.name);
    });
  }, [shown, search, sortKey, sortDir]);

  // The model that beats each off-frontier model, looked up by id for the cards.
  const byId = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const leaderOf = (m: ModelRow): ModelRow | null =>
    m.value_beaten_by ? (byId.get(m.value_beaten_by) ?? null) : null;

  // Sorting by Score groups the rows by cost tier; the Quality switch groups
  // them by AA Index band. Any other sort is a plain ranking.
  const grouping: Grouping | null =
    sortKey === "value" ? "tier" : sortKey === "quality" ? "quality" : null;

  // What each group header says about the rows under it: how many, their
  // prices on both scales the page uses (output, which sets the tier, and
  // blended, which the Score, the charts and the frontier use), and whether
  // anything in the group is on the frontier.
  const groupStats = useMemo(() => {
    const out = new Map<string, GroupStats>();
    if (!grouping) return out;
    const members = new Map<string, ModelRow[]>();
    for (const r of rows) {
      const k = groupKey(r, grouping);
      const list = members.get(k);
      if (list) list.push(r);
      else members.set(k, [r]);
    }
    for (const [k, list] of members) {
      const outs = list.map((r) => r.output_price_per_1m);
      const blends = list.map((r) => blendedPrice(r.input_price_per_1m, r.output_price_per_1m));
      out.set(k, {
        count: list.length,
        outLo: Math.min(...outs),
        outHi: Math.max(...outs),
        blendLo: Math.min(...blends),
        blendHi: Math.max(...blends),
        note: topScoreSentence(list, byId, "an AA Index"),
      });
    }
    return out;
  }, [rows, grouping, byId]);

  function groupBy(next: Grouping) {
    setSortKey(next === "tier" ? "value" : "quality");
    setSortDir("desc");
    savePrefs({ groupBy: next });
  }

  function toggleSort(key: SortKey) {
    setSortDir(nextDir(key, sortKey, sortDir));
    setSortKey(key);
  }

  function switchView(v: View) {
    setView(v);
    savePrefs({ view: v });
    // A sort on a column the other view does not show would be invisible;
    // fall back to the shared default.
    const hiddenInGrid = ["provider", "jurisdiction", "input_price_per_1m"].includes(sortKey);
    if ((v === "benchmarks" && (isCategory(sortKey) || hiddenInGrid)) || (v === "ratings" && isBenchKey(sortKey))) {
      setSortKey("aa_index");
      setSortDir("desc");
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Ratings: chevron + model + provider + juris + input + output + AA index +
  // seven categories. Grid: provider/juris/input step aside (they are filters,
  // and pricing is the ratings view's job) so the evaluation columns fit.
  const colSpan =
    view === "ratings"
      ? 8 + CATEGORY_ORDER.length
      : 5 + GRID_COLUMNS.length - 1;

  return (
    <div data-testid="model-catalog">
      {/* Controls */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <label className={LABEL_CLASS}>
            Search
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Model, provider, or benchmark…"
              aria-label="Search models, providers, or benchmarks"
              className={INPUT_CLASS + " sm:w-60"}
            />
          </label>
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
            <div
              role="group"
              aria-labelledby="jurisdiction-label"
              data-testid="jurisdiction-filter"
              className="inline-flex self-start rounded-md border border-brand-slate-300 bg-white p-0.5 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
            >
              {jurisdictions.map((j) => {
                const on = filters.jurisdictions.has(j);
                return (
                  <label
                    key={j}
                    title={jurisdictionDef(j)}
                    className={
                      "inline-flex cursor-pointer items-center gap-1.5 rounded px-2.5 py-1.5 text-sm font-medium transition-colors hover:text-brand-accent " +
                      (on
                        ? "text-brand-slate-900 dark:text-brand-slate-50"
                        : "text-brand-slate-400 dark:text-brand-slate-500")
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
          <div className={LABEL_CLASS}>
            <span id="group-by-label">Group by</span>
            <div
              role="group"
              aria-labelledby="group-by-label"
              className="inline-flex self-start rounded-md border border-brand-slate-300 bg-white p-0.5 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
            >
              {(
                [
                  ["tier", "Cost tier"],
                  ["quality", "Quality"],
                ] as const
              ).map(([g, label]) => (
                <button
                  key={g}
                  type="button"
                  data-testid={`group-by-${g}`}
                  aria-pressed={grouping === g}
                  onClick={() => groupBy(g)}
                  className={
                    "rounded px-3 py-1.5 text-sm font-medium transition-colors " +
                    (grouping === g
                      ? "bg-brand-accent text-white"
                      : "text-brand-slate-600 hover:text-brand-accent dark:text-brand-slate-300")
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* View toggle */}
        <div
          role="group"
          aria-label="Choose what to show"
          className="inline-flex self-start rounded-lg border border-brand-slate-300 p-0.5 dark:border-brand-slate-700"
        >
          {(
            [
              ["ratings", "Ratings"],
              ["benchmarks", "Benchmark scores"],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              type="button"
              data-testid={`view-${v}`}
              aria-pressed={view === v}
              onClick={() => switchView(v)}
              className={
                "rounded-md px-3 py-1.5 text-xs font-semibold transition-colors " +
                (view === v
                  ? "bg-brand-accent text-white"
                  : "text-brand-slate-600 hover:text-brand-accent dark:text-brand-slate-300")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <p className="mt-3 text-xs text-brand-slate-500 dark:text-brand-slate-400">
        Showing <span className="font-semibold">{rows.length}</span> of {models.length} models
        {filterSummary && (
          <>
            {" "}({filterSummary};{" "}
            <button
              type="button"
              onClick={onClearFilters}
              data-testid="clear-filters"
              className="text-brand-accent hover:underline"
            >
              clear filters
            </button>
            )
          </>
        )}
        {view === "benchmarks" && (
          <>
            {" "}&middot; {measuredCount} measured by Artificial Analysis; &ldquo;&mdash;&rdquo; is
            not measured, never a zero; cell color is the value&rsquo;s quintile within its
            column (green = top 20%, rose = bottom 20%)
          </>
        )}
        .{" "}
        <span data-testid="grouping-note">
          {grouping === "tier" ? (
            <>
              <strong className="font-semibold">Grouped by cost tier: the best buy at your budget.</strong>{" "}
              Each Score is read against its own tier.
            </>
          ) : grouping === "quality" ? (
            <>
              <strong className="font-semibold">Grouped by quality: the cheapest way to each level.</strong>{" "}
              Models in the same {QUALITY_BAND_WIDTH}-point AA Index band, cheapest (blended) first.
            </>
          ) : (
            <>Sorted by the column you chose; Group by puts the header rows back.</>
          )}
        </span>{" "}
        Click a column header to sort, a model name for its docs, and the chevron for pricing
        detail, best-for notes, and the benchmarks the curation cited. The{" "}
        <a href="#how-to-read" className="text-brand-accent hover:underline">
          full key
        </a>{" "}
        is below the charts.
      </p>

      {/* The two things the table cannot say for itself. */}
      <div className="mt-3 grid grid-cols-1 gap-2 text-xs leading-5 md:grid-cols-2" data-testid="table-key">
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-50/70 px-3 py-2 text-brand-slate-700 dark:bg-emerald-500/10 dark:text-brand-slate-200">
          <span aria-hidden className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full border-2 border-emerald-500 align-middle" />
          <strong className="text-brand-slate-900 dark:text-brand-slate-50">
            Cost/quality frontier: the top score at every price.
          </strong>{" "}
          A green ring marks a model that scores higher on the AA Index than every other model at
          its price or less. The ring compares{" "}
          {scope ? (
            <>
              every <span data-testid="frontier-scope">{scope}</span> model, at every price (the
              Cost tier filter narrows what you see, not what the ring compares)
            </>
          ) : (
            "every model in the catalog"
          )}
          ; the Score compares a model with its own cost tier. Hover any AA Index for the top score
          at that price, and see the frontier chart below the table for the whole line.
        </p>
        <p className="rounded-lg border border-brand-slate-200 bg-brand-slate-50 px-3 py-2 text-brand-slate-700 dark:border-brand-slate-700 dark:bg-brand-slate-800/60 dark:text-brand-slate-200">
          <strong className="text-brand-slate-900 dark:text-brand-slate-50">
            Blended price = (3 &times; input + 1 &times; output) &divide; 4.
          </strong>{" "}
          One price per model: what 1M tokens cost when three of every four are input, Artificial
          Analysis&rsquo;s standard mix. It sits between the Input and Output prices ($5 in and $25
          out blend to $10). Cost tiers go by output price; the Score, the charts and the frontier
          use blended.
        </p>
      </div>

      {/* Table */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-brand-slate-200 dark:border-brand-slate-700">
        <table className="w-full border-collapse text-left text-sm">
          <thead className="bg-brand-slate-50 text-[11px] uppercase tracking-wide text-brand-slate-500 dark:bg-brand-slate-800/60 dark:text-brand-slate-400">
            <tr className="border-b border-brand-slate-200 dark:border-brand-slate-700">
              <th className="w-8 px-1 py-2" aria-hidden />
              <SortHeader
                field="name"
                sortKey={sortKey}
                dir={sortDir}
                onSort={toggleSort}
                className={"min-w-[9rem] " + STICKY_HEAD}
              />
              {view === "ratings" && (
                <>
                  <SortHeader
                    field="provider"
                    sortKey={sortKey}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortHeader
                    field="jurisdiction"
                    sortKey={sortKey}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortHeader
                    field="input_price_per_1m"
                    sortKey={sortKey}
                    dir={sortDir}
                    onSort={toggleSort}
                    align="right"
                  />
                </>
              )}
              <SortHeader
                field="output_price_per_1m"
                sortKey={sortKey}
                dir={sortDir}
                onSort={toggleSort}
                align="right"
              />
              <SortHeader
                field="aa_index"
                sortKey={sortKey}
                dir={sortDir}
                onSort={toggleSort}
                align="right"
                detail={`This page carries the Artificial Analysis snapshot of ${benchmarksGeneratedAt}: ${measuredCount} of ${models.length} catalog models measured, ${GRID_COLUMNS.length - 1} of its evaluations shown as columns in the benchmark-scores view.`}
              />
              <SortHeader
                field="value"
                sortKey={sortKey}
                dir={sortDir}
                onSort={toggleSort}
                align="right"
                detail={
                  scoreFit
                    ? `Fit over ${scoreFit.n} measured models in ${Object.keys(scoreFit.tiers).length} cost tiers: ${scoreFit.slope.toFixed(1)} index points per 10× price, R² ${scoreFit.r2.toFixed(2)}, residual σ ${scoreFit.sigma.toFixed(1)} — treat gaps under about ${Math.round(scoreFit.sigma)} points as ties.`
                    : "Not enough measured models to fit the market line."
                }
              />
              {view === "ratings"
                ? CATEGORY_ORDER.map((cat) => (
                    <CategoryHeader
                      key={cat}
                      cat={cat}
                      sortKey={sortKey}
                      dir={sortDir}
                      onSort={toggleSort}
                    />
                  ))
                : GRID_BODY_COLUMNS.map((col, i) => (
                    <BenchHeader
                      key={col.key}
                      col={col}
                      sortKey={sortKey}
                      dir={sortDir}
                      onSort={toggleSort}
                      align={i >= GRID_BODY_COLUMNS.length - 3 ? "right" : "left"}
                    />
                  ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-slate-100 dark:divide-brand-slate-800">
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={colSpan}
                  className="px-3 py-10 text-center text-brand-slate-500 dark:text-brand-slate-400"
                >
                  No models match your filters.
                </td>
              </tr>
            ) : (
              rows.map((m, i) => {
                const provider = modelProvider(m.id);
                const isOpen = expanded.has(m.id);
                const tier = COST_TIER_DEFS[m.tier_cost];
                // Grouped (by cost tier or by quality), a header row opens each group.
                const key = grouping ? groupKey(m, grouping) : null;
                const groupStart =
                  grouping !== null && (i === 0 || groupKey(rows[i - 1], grouping) !== key);
                const group = key !== null ? groupStats.get(key) : undefined;
                const tierFit = scoreFit?.tiers[m.tier_cost];
                const band = qualityBand(m.aa_index);
                const count = group ? `${group.count} ${group.count === 1 ? "model" : "models"}` : "";
                const prices = group && (
                  <>
                    output {priceRange(group.outLo, group.outHi, formatPrice)} · blended{" "}
                    {priceRange(group.blendLo, group.blendHi, formatBlended)} (3 input : 1 output)
                    per 1M
                  </>
                );
                const beatenNote = group?.note && (
                  <span
                    className="mt-0.5 block font-medium normal-case tracking-normal text-emerald-700 dark:text-emerald-300"
                    data-testid="group-beaten"
                  >
                    {group.note}
                  </span>
                );
                return (
                  <Fragment key={m.id}>
                    {groupStart && group && grouping === "tier" && (
                      <tr data-testid="score-group" data-tier={m.tier_cost}>
                        <td colSpan={colSpan} className={GROUP_HEADER_CELL}>
                          <span className={"mr-1.5 inline-block h-2 w-2 rounded-full align-middle " + COST_TIER_DOT[m.tier_cost]} />
                          {tier.label} cost · {count}
                          <span className={GROUP_HEADER_DETAIL} data-testid="score-group-prices">
                            {prices}
                            {tierFit && <> · Score is vs. this tier&rsquo;s own price line</>}
                          </span>
                          {beatenNote}
                        </td>
                      </tr>
                    )}
                    {groupStart && group && grouping === "quality" && (
                      <tr data-testid="quality-group" data-band={band === null ? "none" : String(band)}>
                        <td colSpan={colSpan} className={GROUP_HEADER_CELL}>
                          {band === null ? (
                            <>Not measured · {count}</>
                          ) : (
                            <>AA Index {formatQualityBand(band)} · {count}</>
                          )}
                          <span className={GROUP_HEADER_DETAIL} data-testid="quality-group-prices">
                            {band === null ? (
                              <>No AA Index yet, so no quality band</>
                            ) : (
                              <>
                                {prices} · cheapest first
                              </>
                            )}
                          </span>
                          {beatenNote}
                        </td>
                      </tr>
                    )}
                    <tr
                      data-testid="model-row"
                      data-model-id={m.id}
                      data-tier-cost={m.tier_cost}
                      className="group/row align-middle hover:bg-brand-slate-50 dark:hover:bg-brand-slate-800/40"
                    >
                      <td className="px-1 py-2 text-center">
                        <button
                          type="button"
                          onClick={() => toggleExpand(m.id)}
                          aria-expanded={isOpen}
                          aria-label={`${isOpen ? "Hide" : "Show"} details for ${m.name}`}
                          className="rounded p-0.5 text-brand-slate-400 hover:text-brand-accent"
                        >
                          {isOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      </td>
                      <td
                        className={
                          "whitespace-nowrap px-3 py-2 font-medium text-brand-slate-900 dark:text-brand-slate-50 " +
                          STICKY_CELL
                        }
                      >
                        {provider ? (
                          <a
                            href={provider.docUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={`Open ${provider.label} model documentation ↗`}
                            className="border-b border-dotted border-brand-slate-400 hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-500"
                          >
                            {m.name}
                          </a>
                        ) : (
                          m.name
                        )}
                        {m.superseded_by && (
                          <SupersededTag model={m} successor={byId.get(m.superseded_by) ?? null} />
                        )}
                      </td>
                      {view === "ratings" && (
                        <>
                          <td className="whitespace-nowrap px-3 py-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
                            {m.provider ?? <span className="text-brand-slate-400">—</span>}
                          </td>
                          <td className="px-3 py-2">
                            <GlossaryTerm definition={jurisdictionDef(m.jurisdiction)}>
                              <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-slate-600 dark:text-brand-slate-300">
                                {m.jurisdiction}
                              </span>
                            </GlossaryTerm>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-brand-slate-700 dark:text-brand-slate-200">
                            {formatPrice(m.input_price_per_1m)}
                          </td>
                        </>
                      )}
                      <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-brand-slate-900 dark:text-brand-slate-50">
                        <span
                          data-testid="cost-tier-dot"
                          data-tier={m.tier_cost}
                          title={`${tier.label} cost tier — ${tier.definition}`}
                          className={
                            "mr-1.5 inline-block h-2 w-2 rounded-full align-middle " +
                            COST_TIER_DOT[m.tier_cost]
                          }
                        />
                        {formatPrice(m.output_price_per_1m)}
                      </td>
                      <td
                        data-testid="aa-index"
                        data-frontier={m.value_frontier ? "1" : "0"}
                        data-beaten-by={m.value_beaten_by ?? ""}
                        className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-brand-slate-900 dark:text-brand-slate-50"
                      >
                        {m.aa_index === null ? (
                          <span
                            className="text-brand-slate-400 dark:text-brand-slate-500"
                            title="Not measured by Artificial Analysis"
                          >
                            —
                          </span>
                        ) : (
                          <HoverCard
                            label={`${m.name}: AA Index ${m.aa_index}${m.value_frontier ? ", on the cost/quality frontier" : ""}. Show where it stands across every cost tier`}
                            card={
                              <IndexCard model={m} leader={leaderOf(m)} snapshot={benchmarksGeneratedAt} />
                            }
                            triggerTestId="aa-index-trigger"
                            cardTestId="aa-index-card"
                            className="tabular-nums"
                          >
                            {m.value_frontier && (
                              <span
                                aria-hidden
                                data-testid="frontier-mark"
                                className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full border-2 border-emerald-500 align-middle"
                              />
                            )}
                            {m.aa_index}
                          </HoverCard>
                        )}
                      </td>
                      <td
                        className={"whitespace-nowrap px-3 py-2 text-right tabular-nums " + scoreTone(m.value_score, scoreFit)}
                        data-testid="value-cell"
                        data-value={m.value_score === null ? "" : m.value_score.toFixed(3)}
                      >
                        {m.value_score === null || !scoreFit ? (
                          <HoverCard
                            label={`${m.name} has no Score`}
                            card={
                              <p className="w-64 max-w-full text-[13px] leading-5">
                                <span className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                                  No Score for {m.name}.
                                </span>{" "}
                                Artificial Analysis has not measured its Intelligence Index, and
                                the Score is that index measured against price.
                              </p>
                            }
                            className="text-brand-slate-400 dark:text-brand-slate-500"
                          >
                            —
                          </HoverCard>
                        ) : (
                          <HoverCard
                            label={`${m.name}: Score ${formatScore(m.value_score)}. Show how it adds up`}
                            card={
                              <ScoreBreakdownCard
                                model={m}
                                fit={scoreFit}
                                snapshot={benchmarksGeneratedAt}
                                leader={leaderOf(m)}
                              />
                            }
                            triggerTestId="score-trigger"
                            cardTestId="score-card"
                            className="tabular-nums"
                          >
                            {formatScore(m.value_score)}
                          </HoverCard>
                        )}
                      </td>
                      {view === "ratings"
                        ? CATEGORY_ORDER.map((cat) => {
                            const r = m.tiers[cat];
                            const key = CATEGORY_FIGURE[cat];
                            const v = key ? benchSortValue(m.bench, key) : null;
                            const derived = DERIVED_CATEGORIES.has(cat) && key && v !== null;
                            let basis = "Editorial rating.";
                            if (derived) {
                              const col = GRID_COLUMN_BY_KEY[key];
                              const leader = columnValues[key][columnValues[key].length - 1];
                              const gap = benchPoints(leader, col.unit) - benchPoints(v, col.unit);
                              basis = `Derived from ${col.label} ${formatBench(v, col.unit)}: ${gap.toFixed(1)} points behind the category leader (${formatBench(leader, col.unit)}).`;
                            }
                            return (
                              <td key={cat} className="w-14 px-1 py-2 text-center">
                                <span
                                  data-testid="rating-cell"
                                  data-basis={derived ? "derived" : "editorial"}
                                  className={
                                    BADGE_CLASS +
                                    " " +
                                    RATING_COLORS[r] +
                                    (derived ? "" : " ring-1 ring-inset ring-brand-slate-400/60 dark:ring-brand-slate-500/60")
                                  }
                                  title={`${CATEGORY_DEFS[cat].fullName}: ${r} — ${RATING_MEANING[r]} ${basis}`}
                                >
                                  {r}
                                </span>
                              </td>
                            );
                          })
                        : GRID_BODY_COLUMNS.map((col) => {
                            const v = benchSortValue(m.bench, col.key);
                            const band = bandFor(v, columnValues[col.key]);
                            return (
                              <td
                                key={col.key}
                                data-testid="bench-cell"
                                data-bench={col.key}
                                data-band={band ?? ""}
                                className="whitespace-nowrap px-1.5 py-1.5 text-right tabular-nums"
                                title={
                                  v === null
                                    ? `${col.label}: not measured by Artificial Analysis`
                                    : `${col.label}: ${formatBench(v, col.unit)} — ${BAND_LABEL[band!]} (Artificial Analysis${m.bench ? `, ${m.bench.aa_name}` : ""})`
                                }
                              >
                                {v === null ? (
                                  <span className="text-brand-slate-300 dark:text-brand-slate-600">—</span>
                                ) : (
                                  <span
                                    className={
                                      "inline-block min-w-[3.25rem] rounded px-1.5 py-0.5 text-xs font-semibold " +
                                      BAND_CLASS[band!]
                                    }
                                  >
                                    {formatBench(v, col.unit)}
                                  </span>
                                )}
                              </td>
                            );
                          })}
                    </tr>
                    {isOpen && (
                      <tr
                        data-testid="model-detail"
                        className="bg-brand-slate-50/60 dark:bg-brand-slate-800/30"
                      >
                        <td />
                        <td colSpan={colSpan - 1} className="px-3 pb-4 pt-2">
                          <ModelDetail model={m} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-brand-slate-400 dark:text-brand-slate-500">
        Catalog snapshot {generatedAt}; prices are USD per 1M tokens. Benchmark figures are from{" "}
        <a
          href={AA_HOME}
          target="_blank"
          rel="noopener noreferrer"
          className="text-brand-accent hover:underline"
        >
          Artificial Analysis
        </a>{" "}
        (snapshot {benchmarksGeneratedAt}; {measuredCount} of {models.length} models measured) —
        one lab, one harness, so every column is comparable down the page. Score is the AA
        Index minus what the model&rsquo;s price predicts among its own cost tier (one market
        fit, a baseline per tier), in index points. <strong>The green ring beside an AA Index
        marks the cost/quality frontier</strong>: each ringed model scores higher than every other
        {scope ? ` ${scope} model` : " model in the catalog"} at its price or less (blended). A
        filter changes which models show, never a Score: the price lines are fitted over the whole
        catalog. A rating is a class, not a rank within it; sorting a category orders by
        letter, then by the AA Index. Ratings are curated by the project&rsquo;s daily automation;
        see the{" "}
        <a href="/docs" className="text-brand-accent hover:underline">
          docs
        </a>{" "}
        for the full method.
      </p>
    </div>
  );
}

// "Superseded by Opus 5.5 · leaves Oct 24" under a superseded model's name
// (update/supersede.py): hover or tap it for what the successor beats it on.
function SupersededTag({ model: m, successor }: { model: ModelRow; successor: ModelRow | null }) {
  const name = successor?.name ?? m.superseded_by ?? "";
  return (
    <span
      className="mt-0.5 block max-w-[11rem] whitespace-normal text-[11px] font-normal leading-4 text-brand-slate-500 dark:text-brand-slate-400"
      data-testid="superseded-tag"
      data-superseded-by={m.superseded_by ?? ""}
    >
      <HoverCard
        label={`${m.name} is superseded by ${name}. Show why`}
        card={<SupersededCard model={m} successor={successor} />}
        triggerTestId="superseded-trigger"
        cardTestId="superseded-card"
      >
        Superseded by {name}
      </HoverCard>
      {m.retires_on && <> · leaves {formatDay(m.retires_on)}</>}
    </span>
  );
}

// "2026-10-24" → "Oct 24".
function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

// The expanded row: what the model is best for, the full price card (input /
// output / cache-read / tier + the provider's pricing notes), and the benchmark
// figures the cron cited when it set the ratings — linkified to their sources.
function ModelDetail({ model: m }: { model: ModelRow }) {
  const tier = COST_TIER_DEFS[m.tier_cost];
  const notes = m.pricing_notes && m.pricing_notes !== "-" ? m.pricing_notes : "";
  return (
    <div className="grid grid-cols-1 gap-4 text-sm text-brand-slate-600 dark:text-brand-slate-300 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] md:gap-6">
      <div className="space-y-3">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            Best for
          </h4>
          <p className="mt-1 max-w-prose whitespace-normal">{m.best_for || "—"}</p>
        </div>
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
            Benchmarks cited
          </h4>
          <p className="mt-1 max-w-prose whitespace-normal text-xs leading-relaxed">
            <BenchmarkProse text={m.headline_benchmarks || "—"} />
          </p>
        </div>
      </div>
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
          Pricing (USD per 1M tokens)
        </h4>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 tabular-nums">
          <dt>Input</dt>
          <dd className="text-brand-slate-900 dark:text-brand-slate-50">
            {formatPrice(m.input_price_per_1m)}
          </dd>
          <dt>Output</dt>
          <dd className="text-brand-slate-900 dark:text-brand-slate-50">
            {formatPrice(m.output_price_per_1m)}
          </dd>
          <dt>Blended</dt>
          <dd className="text-brand-slate-900 dark:text-brand-slate-50">
            {formatBlended(blendedPrice(m.input_price_per_1m, m.output_price_per_1m))}{" "}
            <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
              (3 &times; input + 1 &times; output) &divide; 4
            </span>
          </dd>
          <dt>Cache read</dt>
          <dd className="text-brand-slate-900 dark:text-brand-slate-50">
            {m.cache_read_per_1m === null ? "not published" : formatPrice(m.cache_read_per_1m)}
          </dd>
          <dt>Cost tier</dt>
          <dd>
            <span className={BADGE_CLASS + " " + COST_TIER_COLORS[m.tier_cost]}>{tier.label}</span>{" "}
            <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
              {tier.definition}
            </span>
          </dd>
        </dl>
        {notes && (
          <p className="mt-2 whitespace-normal text-xs text-brand-slate-500 dark:text-brand-slate-400">
            <span className="font-semibold">Notes:</span> {notes}
          </p>
        )}
      </div>
    </div>
  );
}

function SortHeader({
  field,
  sortKey,
  dir,
  onSort,
  align = "left",
  className = "",
  detail,
}: {
  field: Exclude<SortKey, Category | BenchKey | "quality">;
  sortKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
  className?: string;
  // Extra sentence appended to the definition (e.g. live fit statistics).
  detail?: string;
}) {
  const def = FIELD_DEFS[field];
  const active = sortKey === field;
  return (
    <th
      className={
        "whitespace-nowrap px-3 py-2 font-semibold " +
        (align === "right" ? "text-right " : "text-left ") +
        className
      }
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <span
        className={
          "inline-flex items-center gap-1 " + (align === "right" ? "flex-row-reverse" : "")
        }
      >
        <button
          type="button"
          onClick={() => onSort(field)}
          className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-brand-accent"
        >
          {def.label}
          <SortArrow active={active} dir={dir} />
        </button>
        <FieldInfo
          fullName={def.fullName}
          definition={detail ? `${def.definition} ${detail}` : def.definition}
          url={def.url}
          align={align}
        />
      </span>
    </th>
  );
}

// The last few category columns sit at the table's right edge, where a
// left-anchored popover would be clipped by the scroll wrapper.
const RIGHT_EDGE_CATEGORIES = new Set<Category>(CATEGORY_ORDER.slice(-3));

function CategoryHeader({
  cat,
  sortKey,
  dir,
  onSort,
}: {
  cat: Category;
  sortKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  const def = CATEGORY_DEFS[cat];
  const active = sortKey === cat;
  const figureKey = CATEGORY_FIGURE[cat];
  const figure = figureKey ? GRID_COLUMN_BY_KEY[figureKey] : null;
  const definition = figure
    ? DERIVED_CATEGORIES.has(cat)
      ? `${def.definition} Letters here are DERIVED from ${figure.label} (Artificial Analysis) as the gap to the category leader: S ≤ 5, A ≤ 20, B ≤ 35, C ≤ 50 points, else D. A ringed letter is editorial (AA has not measured that model).`
      : `${def.definition} Editorial rating; the ${figure.label} column in the Benchmark scores view is first-party-endpoint throughput and is shown for reference only.`
    : `${def.definition} No single-source public benchmark covers this category; the rating is editorial.`;
  return (
    <th
      className="w-14 px-1 py-2 text-center align-bottom font-semibold"
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <span className="inline-flex flex-col items-center gap-0.5">
        <button
          type="button"
          onClick={() => onSort(cat)}
          aria-label={`Sort by ${def.label}`}
          className="inline-flex items-center gap-0.5 uppercase leading-tight tracking-wide hover:text-brand-accent"
        >
          {def.short ?? def.label}
          <SortArrow active={active} dir={dir} />
        </button>
        <FieldInfo
          fullName={def.fullName}
          definition={definition}
          url={figure ? figure.url : def.url}
          align={RIGHT_EDGE_CATEGORIES.has(cat) ? "right" : "left"}
        />
      </span>
    </th>
  );
}

// The grid omits the Intelligence Index column because the ratings/benchmarks
// views share the AA Index column to its left.
const GRID_BODY_COLUMNS: BenchColumn[] = GRID_COLUMNS.filter(
  (c) => c.key !== "artificial_analysis_intelligence_index",
);

function BenchHeader({
  col,
  sortKey,
  dir,
  onSort,
  align,
}: {
  col: BenchColumn;
  sortKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align: "left" | "right";
}) {
  const active = sortKey === col.key;
  return (
    <th
      className="whitespace-nowrap px-2 py-2 text-right font-semibold"
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <span className="inline-flex flex-row-reverse items-center gap-1">
        <button
          type="button"
          onClick={() => onSort(col.key)}
          aria-label={`Sort by ${col.label}`}
          className="inline-flex items-center gap-0.5 uppercase tracking-wide hover:text-brand-accent"
        >
          {col.short}
          <SortArrow active={active} dir={dir} />
        </button>
        <FieldInfo
          fullName={col.label}
          definition={`${col.definition} Source: Artificial Analysis.`}
          url={col.url}
          align={align}
        />
      </span>
    </th>
  );
}

function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return null;
  return dir === "asc" ? (
    <ArrowUp className="h-3 w-3 text-brand-accent" />
  ) : (
    <ArrowDown className="h-3 w-3 text-brand-accent" />
  );
}

function FieldInfo({
  fullName,
  definition,
  url,
  align = "left",
}: {
  fullName: string;
  definition: string;
  url?: string;
  align?: "left" | "right";
}) {
  return (
    <GlossaryTerm definition={`${fullName} — ${definition}`} url={url} align={align}>
      <Info className="h-3 w-3 text-brand-slate-400" aria-hidden />
      <span className="sr-only">{fullName} definition</span>
    </GlossaryTerm>
  );
}

function BenchmarkProse({ text }: { text: string }) {
  return (
    <span className="leading-relaxed">
      {segmentRationale(text).map((segment, i) =>
        segment.term && segment.definition ? (
          <GlossaryTerm key={i} definition={segment.definition} url={segment.url}>
            {segment.text}
          </GlossaryTerm>
        ) : (
          <Fragment key={i}>{segment.text}</Fragment>
        ),
      )}
    </span>
  );
}
