// web/components/ModelCatalog.tsx
//
// The interactive catalog table for /models: client-side sort + filter, a toggle
// between the S→D ratings columns and the benchmark-score column, header tooltips
// (field name + definition + source via GlossaryTerm), per-cell hovertext, and
// benchmark names auto-linkified through the glossary (segmentRationale). Pure
// presentation — the server page passes the rows; no catalog import here.
"use client";

import { Fragment, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Info } from "lucide-react";

import { RATING_SCALE, segmentRationale } from "@/lib/glossary";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_COLORS,
  COST_TIER_DEFS,
  COST_TIER_RANK,
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
  | "jurisdiction"
  | "input_price_per_1m"
  | "output_price_per_1m"
  | "cache_read_per_1m"
  | "tier_cost"
  | Category;
type SortDir = "asc" | "desc";
type View = "ratings" | "benchmarks";

const INPUT_CLASS =
  "rounded-md border border-brand-slate-300 dark:border-brand-slate-700 " +
  "bg-white dark:bg-brand-slate-800 px-3 py-2 text-sm shadow-sm " +
  "focus:border-brand-accent focus:outline-none focus:ring-1 focus:ring-brand-accent";

const BADGE_CLASS =
  "inline-flex min-w-[2rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold";

function nextDir(key: SortKey, active: SortKey, dir: SortDir): SortDir {
  if (key === active) return dir === "asc" ? "desc" : "asc";
  // New column: text sorts A→Z, everything numeric/ranked sorts best-first.
  return key === "name" || key === "jurisdiction" ? "asc" : "desc";
}

function valueFor(row: ModelRow, key: SortKey): number | string {
  switch (key) {
    case "name":
      return row.name.toLowerCase();
    case "jurisdiction":
      return row.jurisdiction;
    case "input_price_per_1m":
      return row.input_price_per_1m;
    case "output_price_per_1m":
      return row.output_price_per_1m;
    case "cache_read_per_1m":
      return row.cache_read_per_1m ?? -1;
    case "tier_cost":
      return COST_TIER_RANK[row.tier_cost];
    default:
      return RATING_RANK[row.tiers[key]];
  }
}

export function ModelCatalog({
  models,
  generatedAt,
}: {
  models: ModelRow[];
  generatedAt: string;
}) {
  const [view, setView] = useState<View>("ratings");
  const [sortKey, setSortKey] = useState<SortKey>("output_price_per_1m");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [search, setSearch] = useState("");
  const [juris, setJuris] = useState("all");
  const [cost, setCost] = useState("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const jurisdictions = useMemo(
    () => Array.from(new Set(models.map((m) => m.jurisdiction))).sort(),
    [models],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = models.filter((m) => {
      if (juris !== "all" && m.jurisdiction !== juris) return false;
      if (cost !== "all" && m.tier_cost !== cost) return false;
      if (
        needle &&
        !m.name.toLowerCase().includes(needle) &&
        !m.headline_benchmarks.toLowerCase().includes(needle)
      )
        return false;
      return true;
    });
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = valueFor(a, sortKey);
      const bv = valueFor(b, sortKey);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return a.name.localeCompare(b.name);
    });
  }, [models, search, juris, cost, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    setSortDir(nextDir(key, sortKey, sortDir));
    setSortKey(key);
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const leftColSpan = 6; // chevron + model + juris + input + output + cost
  const colSpan = leftColSpan + (view === "ratings" ? CATEGORY_ORDER.length : 1) + 1; // + cache

  return (
    <div data-testid="model-catalog">
      {/* Controls */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <label className="flex flex-col gap-1 text-xs font-medium text-brand-slate-600 dark:text-brand-slate-300">
            Search
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Model or benchmark…"
              aria-label="Search models or benchmarks"
              className={INPUT_CLASS + " sm:w-56"}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-brand-slate-600 dark:text-brand-slate-300">
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
          <label className="flex flex-col gap-1 text-xs font-medium text-brand-slate-600 dark:text-brand-slate-300">
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
              ["ratings", "Pricing & ratings"],
              ["benchmarks", "Benchmark scores"],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              type="button"
              data-testid={`view-${v}`}
              aria-pressed={view === v}
              onClick={() => setView(v)}
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
        Showing <span className="font-semibold">{rows.length}</span> of {models.length} models.
        Click a column header to sort; click a model name for its docs; hover any label or
        benchmark for its definition and source.
      </p>

      {/* Table */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-brand-slate-200 dark:border-brand-slate-700">
        <table className="w-full min-w-[860px] border-collapse text-left text-sm">
          <thead className="bg-brand-slate-50 text-xs uppercase tracking-wide text-brand-slate-500 dark:bg-brand-slate-800/60 dark:text-brand-slate-400">
            <tr className="border-b border-brand-slate-200 dark:border-brand-slate-700">
              <th className="w-8 px-2 py-2" aria-hidden />
              <SortHeader field="name" sortKey={sortKey} dir={sortDir} onSort={toggleSort} />
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
              <SortHeader
                field="output_price_per_1m"
                sortKey={sortKey}
                dir={sortDir}
                onSort={toggleSort}
                align="right"
              />
              <SortHeader
                field="cache_read_per_1m"
                sortKey={sortKey}
                dir={sortDir}
                onSort={toggleSort}
                align="right"
              />
              <SortHeader field="tier_cost" sortKey={sortKey} dir={sortDir} onSort={toggleSort} />
              {view === "ratings" ? (
                CATEGORY_ORDER.map((cat) => (
                  <CategoryHeader
                    key={cat}
                    cat={cat}
                    sortKey={sortKey}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                ))
              ) : (
                <th className="px-3 py-2 font-semibold">
                  <span className="inline-flex items-center gap-1">
                    {FIELD_DEFS.benchmarks.label}
                    <FieldInfo
                      fullName={FIELD_DEFS.benchmarks.fullName}
                      definition={FIELD_DEFS.benchmarks.definition}
                      url={FIELD_DEFS.benchmarks.url}
                    />
                  </span>
                </th>
              )}
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
                return (
                  <Fragment key={m.id}>
                    <tr
                      data-testid="model-row"
                      className="align-middle hover:bg-brand-slate-50 dark:hover:bg-brand-slate-800/40"
                    >
                      <td className="px-2 py-2">
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
                      <td className="whitespace-nowrap px-3 py-2 font-medium text-brand-slate-900 dark:text-brand-slate-50">
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
                      <td className="px-3 py-2">
                        <GlossaryTerm definition={jurisdictionDef(m.jurisdiction)}>
                          <span className="text-xs font-medium uppercase text-brand-slate-600 dark:text-brand-slate-300">
                            {m.jurisdiction}
                          </span>
                        </GlossaryTerm>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-brand-slate-700 dark:text-brand-slate-200">
                        {formatPrice(m.input_price_per_1m)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-brand-slate-900 dark:text-brand-slate-50">
                        {formatPrice(m.output_price_per_1m)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
                        {formatPrice(m.cache_read_per_1m)}
                      </td>
                      <td className="px-3 py-2">
                        <GlossaryTerm definition={COST_TIER_DEFS[m.tier_cost].definition}>
                          <span className={BADGE_CLASS + " " + COST_TIER_COLORS[m.tier_cost]}>
                            {COST_TIER_DEFS[m.tier_cost].label}
                          </span>
                        </GlossaryTerm>
                      </td>
                      {view === "ratings" ? (
                        CATEGORY_ORDER.map((cat) => {
                          const r = m.tiers[cat];
                          return (
                            <td key={cat} className="px-2 py-2 text-center">
                              <span
                                className={BADGE_CLASS + " " + RATING_COLORS[r]}
                                title={`${CATEGORY_DEFS[cat].fullName}: ${r} — ${RATING_MEANING[r]}`}
                              >
                                {r}
                              </span>
                            </td>
                          );
                        })
                      ) : (
                        <td className="px-3 py-2 text-brand-slate-700 dark:text-brand-slate-200">
                          <BenchmarkCell text={m.headline_benchmarks} />
                        </td>
                      )}
                    </tr>
                    {isOpen && (
                      <tr className="bg-brand-slate-50/60 dark:bg-brand-slate-800/30">
                        <td />
                        <td
                          colSpan={colSpan - 1}
                          className="px-3 pb-4 pt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300"
                        >
                          <p>
                            <span className="font-semibold text-brand-slate-700 dark:text-brand-slate-200">
                              Best for:
                            </span>{" "}
                            {m.best_for}
                          </p>
                          {m.pricing_notes && m.pricing_notes !== "-" && (
                            <p className="mt-1.5 text-xs text-brand-slate-500 dark:text-brand-slate-400">
                              <span className="font-semibold">Pricing notes:</span>{" "}
                              {m.pricing_notes}
                            </p>
                          )}
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
        Catalog snapshot {generatedAt}. Prices are USD per 1M tokens. Ratings and benchmarks are
        curated by the project&rsquo;s daily automation; see the{" "}
        <a href="/docs" className="text-brand-accent hover:underline">
          docs
        </a>{" "}
        for the full method.
      </p>
    </div>
  );
}

function SortHeader({
  field,
  sortKey,
  dir,
  onSort,
  align = "left",
}: {
  field: Exclude<SortKey, Category>;
  sortKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const def = FIELD_DEFS[field];
  const active = sortKey === field;
  return (
    <th
      className={"px-3 py-2 font-semibold " + (align === "right" ? "text-right" : "text-left")}
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
        <FieldInfo fullName={def.fullName} definition={def.definition} url={def.url} />
      </span>
    </th>
  );
}

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
  return (
    <th
      className="px-2 py-2 text-center font-semibold"
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <span className="inline-flex items-center gap-0.5">
        <button
          type="button"
          onClick={() => onSort(cat)}
          className="inline-flex items-center gap-0.5 uppercase tracking-wide hover:text-brand-accent"
        >
          {def.label}
          <SortArrow active={active} dir={dir} />
        </button>
        <FieldInfo fullName={def.fullName} definition={def.definition} url={def.url} />
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
}: {
  fullName: string;
  definition: string;
  url?: string;
}) {
  return (
    <GlossaryTerm definition={`${fullName} — ${definition}`} url={url}>
      <Info className="h-3 w-3 text-brand-slate-400" aria-hidden />
      <span className="sr-only">{fullName} definition</span>
    </GlossaryTerm>
  );
}

function BenchmarkCell({ text }: { text: string }) {
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
