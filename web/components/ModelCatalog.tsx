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
//     as a colored dot), AA Index, then seven letter cells. Under each letter
//     sits that category's UNIFORM figure from lib/benchmark-grid.ts (the same
//     Artificial Analysis column for every row, so the small numbers compare
//     across rows); categories without a single-source benchmark stay letters
//     only. Sorting a category orders by letter, then by that figure, then by
//     AA Index, then by name.
//   Benchmark scores — the full AA grid: one column per evaluation, every value
//     on that column's scale, "—" only where AA has not measured the model.
// Cache-read price, tier name, pricing notes, "best for", and the benchmarks
// the cron cited (mixed sources — evidence for the letters, not a scale) live
// in the expanded row so they add no width. Fits a 1024px viewport.
"use client";

import { Fragment, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Info } from "lucide-react";

import { RATING_SCALE, segmentRationale } from "@/lib/glossary";
import {
  AA_HOME,
  benchSortValue,
  CATEGORY_FIGURE,
  formatBench,
  GRID_COLUMN_BY_KEY,
  GRID_COLUMNS,
  type BenchColumn,
  type BenchKey,
} from "@/lib/benchmark-grid";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_COLORS,
  COST_TIER_DEFS,
  COST_TIER_DOT,
  FIELD_DEFS,
  formatPrice,
  jurisdictionDef,
  modelProvider,
  RATING_COLORS,
  RATING_RANK,
  type Category,
  type ModelRow,
} from "@/lib/catalog-fields";
import { GlossaryTerm } from "./GlossaryTerm";

const RATING_MEANING: Record<string, string> = Object.fromEntries(
  RATING_SCALE.map((r) => [r.rating, r.meaning]),
);

type SortKey =
  | "name"
  | "provider"
  | "jurisdiction"
  | "input_price_per_1m"
  | "output_price_per_1m"
  | "aa_index"
  | Category
  | BenchKey;
type SortDir = "asc" | "desc";
type View = "ratings" | "benchmarks";

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

// Within one letter of a category column: that category's uniform figure
// (the same AA column for every row), then the AA Index; the caller falls
// through to the name.
function categoryTieBreak(a: ModelRow, b: ModelRow, cat: Category, dir: 1 | -1): number {
  const key = CATEGORY_FIGURE[cat];
  if (key) {
    const t = compareNullable(benchSortValue(a.bench, key), benchSortValue(b.bench, key), dir);
    if (t !== 0) return t;
  }
  return compareNullable(a.aa_index, b.aa_index, dir);
}

function isCategory(key: SortKey): key is Category {
  return (CATEGORY_ORDER as string[]).includes(key);
}

export function ModelCatalog({
  models,
  generatedAt,
  benchmarksGeneratedAt,
  measuredCount,
}: {
  models: ModelRow[];
  generatedAt: string;
  benchmarksGeneratedAt: string;
  measuredCount: number;
}) {
  const [view, setView] = useState<View>("ratings");
  const [sortKey, setSortKey] = useState<SortKey>("output_price_per_1m");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [search, setSearch] = useState("");
  const [provider, setProvider] = useState("all");
  const [juris, setJuris] = useState("all");
  const [cost, setCost] = useState("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const providers = useMemo(
    () =>
      Array.from(new Set(models.map((m) => m.provider).filter((p): p is string => p !== null))).sort(
        (a, b) => a.localeCompare(b),
      ),
    [models],
  );
  const jurisdictions = useMemo(
    () => Array.from(new Set(models.map((m) => m.jurisdiction))).sort(),
    [models],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = models.filter((m) => {
      if (provider !== "all" && m.provider !== provider) return false;
      if (juris !== "all" && m.jurisdiction !== juris) return false;
      if (cost !== "all" && m.tier_cost !== cost) return false;
      if (
        needle &&
        !m.name.toLowerCase().includes(needle) &&
        !(m.provider ?? "").toLowerCase().includes(needle) &&
        !m.headline_benchmarks.toLowerCase().includes(needle)
      )
        return false;
      return true;
    });
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (isBenchKey(sortKey)) {
        const t = compareNullable(benchSortValue(a.bench, sortKey), benchSortValue(b.bench, sortKey), dir);
        if (t !== 0) return t;
        return a.name.localeCompare(b.name);
      }
      const av = valueFor(a, sortKey);
      const bv = valueFor(b, sortKey);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      if (isCategory(sortKey)) {
        const tie = categoryTieBreak(a, b, sortKey, dir);
        if (tie !== 0) return tie;
      }
      return a.name.localeCompare(b.name);
    });
  }, [models, search, provider, juris, cost, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    setSortDir(nextDir(key, sortKey, sortDir));
    setSortKey(key);
  }

  function switchView(v: View) {
    setView(v);
    // A sort on a column the other view does not show would be invisible;
    // fall back to the shared default.
    const hiddenInGrid = ["provider", "jurisdiction", "input_price_per_1m"].includes(sortKey);
    if ((v === "benchmarks" && (isCategory(sortKey) || hiddenInGrid)) || (v === "ratings" && isBenchKey(sortKey))) {
      setSortKey("output_price_per_1m");
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
      ? 7 + CATEGORY_ORDER.length
      : 4 + GRID_COLUMNS.length - 1;

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
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
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
          <label className={LABEL_CLASS}>
            Jurisdiction
            <select
              value={juris}
              onChange={(e) => setJuris(e.target.value)}
              aria-label="Filter by jurisdiction"
              className={INPUT_CLASS}
            >
              <option value="all">All</option>
              {jurisdictions.map((j) => (
                <option key={j} value={j}>
                  {j.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            Cost tier
            <select
              value={cost}
              onChange={(e) => setCost(e.target.value)}
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
        {view === "benchmarks" && (
          <>
            {" "}&middot; {measuredCount} measured by Artificial Analysis; &ldquo;&mdash;&rdquo; is
            not measured, never a zero
          </>
        )}
        . Click a column header to sort, a model name for its docs, and the chevron for pricing
        detail, best-for notes, and the benchmarks the curation cited.
      </p>

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
              rows.map((m) => {
                const provider = modelProvider(m.id);
                const isOpen = expanded.has(m.id);
                const tier = COST_TIER_DEFS[m.tier_cost];
                return (
                  <Fragment key={m.id}>
                    <tr
                      data-testid="model-row"
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
                        className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-brand-slate-900 dark:text-brand-slate-50"
                        title={
                          m.aa_index === null
                            ? "Not measured by Artificial Analysis"
                            : `${FIELD_DEFS.aa_index.fullName}: ${m.aa_index}`
                        }
                      >
                        {m.aa_index === null ? (
                          <span className="text-brand-slate-400 dark:text-brand-slate-500">—</span>
                        ) : (
                          m.aa_index
                        )}
                      </td>
                      {view === "ratings"
                        ? CATEGORY_ORDER.map((cat) => {
                            const r = m.tiers[cat];
                            const key = CATEGORY_FIGURE[cat];
                            const col = key ? GRID_COLUMN_BY_KEY[key] : null;
                            const v = key ? benchSortValue(m.bench, key) : null;
                            return (
                              <td key={cat} className="w-14 px-1 py-1.5 text-center align-top">
                                <span
                                  className={BADGE_CLASS + " " + RATING_COLORS[r]}
                                  title={`${CATEGORY_DEFS[cat].fullName}: ${r} — ${RATING_MEANING[r]}`}
                                >
                                  {r}
                                </span>
                                {col && (
                                  <span
                                    data-testid="cell-figure"
                                    data-bench={col.key}
                                    className={
                                      "mt-0.5 block text-[10px] leading-tight tabular-nums " +
                                      (v === null
                                        ? "text-brand-slate-300 dark:text-brand-slate-600"
                                        : "text-brand-slate-500 dark:text-brand-slate-400")
                                    }
                                    title={
                                      v === null
                                        ? `${col.label}: not measured by Artificial Analysis`
                                        : `${col.label}: ${formatBench(v, col.unit)} (Artificial Analysis)`
                                    }
                                  >
                                    {formatBench(v, col.unit)}
                                  </span>
                                )}
                              </td>
                            );
                          })
                        : GRID_BODY_COLUMNS.map((col) => {
                            const v = benchSortValue(m.bench, col.key);
                            return (
                              <td
                                key={col.key}
                                data-testid="bench-cell"
                                data-bench={col.key}
                                className={
                                  "whitespace-nowrap px-2 py-2 text-right tabular-nums " +
                                  (v === null
                                    ? "text-brand-slate-300 dark:text-brand-slate-600"
                                    : "text-brand-slate-800 dark:text-brand-slate-100")
                                }
                                title={
                                  v === null
                                    ? `${col.label}: not measured by Artificial Analysis`
                                    : `${col.label}: ${formatBench(v, col.unit)} (Artificial Analysis${m.bench ? `, ${m.bench.aa_name}` : ""})`
                                }
                              >
                                {formatBench(v, col.unit)}
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
        one lab, one harness, so every column is comparable down the page. A rating is a class,
        not a rank within it; sorting a category orders by letter, then by that category&rsquo;s
        figure, then by the AA Index. Ratings are curated by the project&rsquo;s daily automation;
        see the{" "}
        <a href="/docs" className="text-brand-accent hover:underline">
          docs
        </a>{" "}
        for the full method.
      </p>
    </div>
  );
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
}: {
  field: Exclude<SortKey, Category | BenchKey>;
  sortKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
  className?: string;
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
          definition={def.definition}
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
    ? `${def.definition} The figure under each letter is ${figure.label} (Artificial Analysis).`
    : `${def.definition} No single-source public benchmark covers this category, so it is rated by letter only.`;
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
