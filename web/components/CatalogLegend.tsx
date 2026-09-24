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
  DERIVATION_BANDS,
  DERIVED_CATEGORIES,
  GRID_COLUMN_BY_KEY,
  QUALITY_BAND_WIDTH,
  type BenchKey,
} from "@/lib/benchmark-grid";
import { RATING_SCALE } from "@/lib/glossary";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_COLORS,
  COST_TIER_DEFS,
  COST_TIER_DOT,
  JURISDICTION_DEFS,
  RATING_COLORS,
  type CostTier,
  type Rating,
} from "@/lib/catalog-fields";

// The four derived categories and the bands, read from the same constants the
// letters are derived with — so this sentence cannot go stale when a band or an
// evidence benchmark changes (a new AA version renames Terminal-Bench, say).
const DERIVED_EVIDENCE: string = CATEGORY_ORDER.filter(
  (c) => DERIVED_CATEGORIES.has(c) && CATEGORY_FIGURE[c],
)
  .map((c) => GRID_COLUMN_BY_KEY[CATEGORY_FIGURE[c] as BenchKey].label)
  .join(", ");
const DERIVED_NAMES: string = CATEGORY_ORDER.filter((c) => DERIVED_CATEGORIES.has(c)).join(", ");
const BAND_RULE: string = DERIVATION_BANDS.map((b) => `${b.letter} within ${b.max}`).join(", ");

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
            A rating is a class several models can share. The <strong>{DERIVED_NAMES}</strong>{" "}
            letters are <em>derived</em> from one Artificial Analysis benchmark each ({DERIVED_EVIDENCE})
            as the gap to the category leader &mdash; {BAND_RULE} points, else D &mdash; and refresh
            with the data. The rest are editorial;
            a <span className="rounded px-1 ring-1 ring-inset ring-brand-slate-400/60">ringed</span>{" "}
            letter is editorial because AA has not measured that model. The{" "}
            <strong>AA Index</strong> column is the one published composite.{" "}
            <strong>Score</strong> is the cost-adjusted figure: the AA Index minus what a
            model&rsquo;s price predicts <em>among its own cost tier</em>, from one market fit
            over every measured model (index against log&nbsp;price, with a baseline per tier),
            in index points &mdash; positive means more intelligence than a same-tier model at
            that price usually delivers. It is the <strong>default sort</strong>, which groups the
            table by cost tier so each model is read against its own price band: the best buy at
            your budget. <strong>Group by &rarr; Quality</strong> regroups it into{" "}
            {QUALITY_BAND_WIDTH}-point AA Index bands, cheapest first: the cheapest way to each
            level. The header shows the fit&rsquo;s n, R&sup2; and residual σ; gaps smaller than σ
            are ties. The Score compares a model with its own tier; the frontier ring (above) compares the
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
