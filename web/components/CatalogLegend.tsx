// web/components/CatalogLegend.tsx
//
// The "How to read this" cheat sheet for /models: the S→D rating scale, the seven
// rating categories, the cost-tier boundaries, and the jurisdiction codes — using
// the same badge colors as the table. A native <details> disclosure (open by
// default), so it needs no client JS. Data comes from the glossary + catalog-fields.
import { RATING_SCALE } from "@/lib/glossary";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_COLORS,
  COST_TIER_DEFS,
  JURISDICTION_DEFS,
  RATING_COLORS,
  type CostTier,
  type Rating,
} from "@/lib/catalog-fields";

const BADGE =
  "inline-flex min-w-[1.75rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold";

const SECTION_HEADING =
  "text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400";

export function CatalogLegend() {
  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
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

      <div className="grid grid-cols-1 gap-6 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700 md:grid-cols-2">
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
                <dt className="w-24 shrink-0">
                  <span className={BADGE + " " + COST_TIER_COLORS[t]}>{COST_TIER_DEFS[t].label}</span>
                </dt>
                <dd className="text-brand-slate-600 dark:text-brand-slate-300">
                  {COST_TIER_DEFS[t].definition}
                </dd>
              </div>
            ))}
          </dl>
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
            Benchmark names in the &ldquo;Benchmark scores&rdquo; view are clickable — hover for a
            definition, click for the source leaderboard. Full list at the bottom of the page.
          </p>
        </div>
      </div>
    </details>
  );
}
