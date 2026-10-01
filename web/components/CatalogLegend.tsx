// web/components/CatalogLegend.tsx
//
// The "How to read this" cheat sheet for /models: the two definitions readers
// trip on (the cost/quality frontier and the blended price), then the S→D
// rating scale, the seven rating categories, the cost-tier boundaries, and the
// jurisdiction codes — using the same badge colors as the table. It sits below
// the table and the charts (the page leads with the catalog itself), and the
// table's caption links here. A native <details> disclosure (open by default),
// so it needs no client JS. Data comes from the glossary + catalog-fields.
import {
  CATEGORY_FIGURE,
  COMPOSITE_DERIVATION,
  DERIVATION_BANDS,
  DERIVED_CATEGORIES,
  ESTIMATE_CEILING,
  GRID_COLUMN_BY_KEY,
  NEW_RELEASE_DAYS,
  QUALITY_BAND_WIDTH,
  RANK_DERIVATION,
  rankRuleText,
  type BenchKey,
} from "@/lib/benchmark-grid";
import { RATING_SCALE } from "@/lib/glossary";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_COLORS,
  COST_TIER_DEFS,
  COST_TIER_DOT,
  ESTIMATED_BADGE,
  JURISDICTION_DEFS,
  RATING_COLORS,
  RATING_OUTLINE_COLORS,
  type CostTier,
  type Rating,
} from "@/lib/catalog-fields";

// The four derived categories and the bands, read from the same constants the
// letters are derived with — so this sentence cannot go stale when a band or an
// evidence benchmark changes (a new AA version renames Terminal-Bench, say).
const DERIVED_EVIDENCE: string = CATEGORY_ORDER.filter(
  (c) => DERIVED_CATEGORIES.has(c) && (CATEGORY_FIGURE[c] || COMPOSITE_DERIVATION[c]),
)
  .map(
    (c) => COMPOSITE_DERIVATION[c]?.label ?? GRID_COLUMN_BY_KEY[CATEGORY_FIGURE[c] as BenchKey].label,
  )
  .join(", ");
const DERIVED_NAMES: string = CATEGORY_ORDER.filter((c) => DERIVED_CATEGORIES.has(c)).join(", ");
const BAND_RULE: string = DERIVATION_BANDS.map((b) => `${b.letter} within ${b.max}`).join(", ");
// The categories lettered by gap, and those lettered by rank (with the rule).
const GAP_NAMES: string = CATEGORY_ORDER.filter(
  (c) => DERIVED_CATEGORIES.has(c) && !RANK_DERIVATION[c],
).join(", ");
const RANK_RULES: string = CATEGORY_ORDER.filter((c) => RANK_DERIVATION[c])
  .map((c) => `${c} is the model's rank, holding the letter spread fixed (${rankRuleText(RANK_DERIVATION[c]!)})`)
  .join("; ");

const BADGE =
  "inline-flex min-w-[1.75rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold";

const SECTION_HEADING =
  "text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400";

export function CatalogLegend({ id }: { id?: string }) {
  return (
    <details
      open
      id={id}
      data-testid="catalog-legend"
      className="group scroll-mt-20 rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        How to read this table
        <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">
          show
        </span>
        <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">
          hide
        </span>
      </summary>

      <div className="grid grid-cols-1 gap-6 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700 md:grid-cols-2 xl:grid-cols-4">
        {/* The two definitions the figures depend on, called out. */}
        <div className="grid grid-cols-1 gap-3 md:col-span-2 lg:grid-cols-2 xl:col-span-4">
          <div
            className="rounded-lg border border-emerald-500/40 bg-emerald-50/70 px-4 py-3 text-sm leading-6 text-brand-slate-700 dark:bg-emerald-500/10 dark:text-brand-slate-200"
            data-testid="legend-frontier"
          >
            <p className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              <span
                aria-hidden
                className="mr-2 inline-block h-3 w-3 rounded-full border-2 border-emerald-500 align-middle"
              />
              Cost/quality frontier: the top score at every price
            </p>
            <p className="mt-1">
              A green ring marks a model that <strong>scores higher on the AA Index than every
              other model at its price or less</strong> (blended price). Lined up from cheapest to
              priciest, the ringed models trace the frontier: the top score each budget buys,
              drawn as a line in the frontier chart. The ring compares every model in the catalog;
              the Score compares a model with its own cost tier. Hover any AA Index for the top
              score at its price.
            </p>
          </div>
          <div
            className="rounded-lg border border-brand-slate-300 bg-white px-4 py-3 text-sm leading-6 text-brand-slate-700 dark:border-brand-slate-600 dark:bg-brand-slate-900/60 dark:text-brand-slate-200"
            data-testid="legend-blended"
          >
            <p className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              Blended price = (3 &times; input + 1 &times; output) &divide; 4
            </p>
            <p className="mt-1">
              <strong>One price per model</strong>: what 1M tokens cost when three of every four
              are input, the standard mix Artificial Analysis prices with. It always sits between
              the Input and Output columns, so it reads well below the output price: $5 input and
              $25 output blend to $10. Cost tiers are set by output price; the Score, the charts
              and the frontier all use the blended price.
            </p>
          </div>
        </div>

        {/* Rating scale */}
        <div>
          <h3 className={SECTION_HEADING}>Rating scale (per category)</h3>
          <dl className="mt-2 space-y-1.5">
            {RATING_SCALE.map((row) => (
              <div key={row.rating} className="flex items-start gap-2 text-sm">
                <dt>
                  <span className={BADGE + " " + RATING_COLORS[row.rating as Rating]}>
                    {row.rating}
                  </span>
                </dt>
                <dd className="text-brand-slate-600 dark:text-brand-slate-300">{row.meaning}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-brand-slate-500 dark:text-brand-slate-400">
            A rating is a class several models can share. A filled letter{" "}
            <span className={BADGE + " " + RATING_COLORS.A}>A</span> is <em>measured</em>: the{" "}
            <strong>{DERIVED_NAMES}</strong> letters are derived from one Artificial Analysis
            benchmark each ({DERIVED_EVIDENCE}) and refresh with the data: {GAP_NAMES} as the
            gap to the category leader &mdash; {BAND_RULE} points, else D; {RANK_RULES}. A
            dashed-outline letter{" "}
            <span className={BADGE + " " + ESTIMATED_BADGE + " " + RATING_OUTLINE_COLORS.A}>A</span>{" "}
            is <em>estimated</em>: the daily catalog automation sets it from each provider&rsquo;s
            published results, and a new model starts from its predecessor&rsquo;s letters. Every
            planning, multimodal and speed letter is an estimate, as is a derived category&rsquo;s
            letter for a model outside its benchmark&rsquo;s measured set; there an estimate stops
            at {ESTIMATE_CEILING}, since S takes a measurement. A <strong>New</strong>{" "}
            tag marks a model released in the last {NEW_RELEASE_DAYS} days (or, before Artificial
            Analysis lists it, added to this catalog in that time); it clears on its own, and the
            line above the table names each one.
            The <strong>AA Index</strong> column is the one published composite; hover it for the
            Artificial Analysis model it was measured as and that model&rsquo;s own benchmarks,
            ranked in this catalog, with a check that they bear the index out.{" "}
            <strong>Score</strong> is the cost-adjusted figure: the AA Index minus what a
            model&rsquo;s price predicts <em>among its own cost tier</em>, from one market fit
            over every measured model (index against log&nbsp;price, with a baseline per tier),
            in index points &mdash; positive means more intelligence than a same-tier model at
            that price usually delivers. It is the <strong>default sort</strong> inside every group,
            highest first. The table opens grouped by <strong>Quality</strong>:{" "}
            {QUALITY_BAND_WIDTH}-point AA Index bands, best first: the best buy at each level.{" "}
            <strong>Group by &rarr; Cost tier</strong> regroups it by price band, priciest first, so
            each model is read against its own tier: the best buy at your budget. The header shows
            the fit&rsquo;s n, R&sup2; and residual σ; gaps smaller than σ are ties. The Score compares a model with its own tier; the frontier ring (above) compares the
            whole catalog.
          </p>
        </div>

        {/* Categories */}
        <div>
          <h3 className={SECTION_HEADING}>The seven categories</h3>
          <dl className="mt-2 space-y-1 text-sm">
            {CATEGORY_ORDER.map((cat) => (
              <div key={cat} className="flex gap-2">
                <dt className="w-24 shrink-0 font-medium text-brand-slate-700 dark:text-brand-slate-200">
                  {CATEGORY_DEFS[cat].label}
                </dt>
                <dd className="text-brand-slate-600 dark:text-brand-slate-300">
                  {CATEGORY_DEFS[cat].definition}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Cost tiers */}
        <div>
          <h3 className={SECTION_HEADING}>Cost tiers (by output price)</h3>
          <dl className="mt-2 space-y-1.5 text-sm">
            {(["low", "medium", "high", "very-high"] as CostTier[]).map((t) => (
              <div key={t} className="flex items-center gap-2">
                <dt className="flex w-24 shrink-0 items-center gap-1.5">
                  <span
                    className={"inline-block h-2 w-2 shrink-0 rounded-full " + COST_TIER_DOT[t]}
                    aria-hidden
                  />
                  <span className={BADGE + " " + COST_TIER_COLORS[t]}>{COST_TIER_DEFS[t].label}</span>
                </dt>
                <dd className="text-brand-slate-600 dark:text-brand-slate-300">
                  {COST_TIER_DEFS[t].definition}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-brand-slate-500 dark:text-brand-slate-400">
            The dot beside each output price is its tier. A tier&rsquo;s header row also gives
            its blended range, which the Score is fitted on. Cache-read and blended prices and the
            provider&rsquo;s pricing notes are in the expanded row.
          </p>
          <p className="mt-3 text-xs text-brand-slate-500 dark:text-brand-slate-400" data-testid="legend-superseded">
            <strong className="text-brand-slate-700 dark:text-brand-slate-200">Superseded</strong>{" "}
            marks a model whose newer sibling, from the same maker, costs the same or less, scores
            higher on the AA Index, rates at least as high in every category, and runs on every
            platform that offers it. The tag names that successor and the day the model leaves the
            catalog, 30 days after it was first superseded.
          </p>
        </div>

        {/* Jurisdictions */}
        <div>
          <h3 className={SECTION_HEADING}>Jurisdictions</h3>
          <dl className="mt-2 space-y-1 text-sm">
            {(["us", "eu", "cn"] as const).map((code) => (
              <div key={code} className="flex gap-2">
                <dt className="w-10 shrink-0 font-medium uppercase text-brand-slate-700 dark:text-brand-slate-200">
                  {code}
                </dt>
                <dd className="text-brand-slate-600 dark:text-brand-slate-300">
                  {JURISDICTION_DEFS[code]}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-brand-slate-500 dark:text-brand-slate-400">
            The &ldquo;Benchmark scores&rdquo; view is the full Artificial Analysis grid, one
            column per evaluation, each cell colored by its quintile within that column on the
            same palette as the letters (green = top 20%, blue, grey, amber, rose = bottom 20%).
            Expand a row for the (mixed-source) figures the curation cited when it set the
            letters. Hover any header for a definition; click for the source.
          </p>
        </div>
      </div>
    </details>
  );
}
