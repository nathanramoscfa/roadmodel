// web/components/CostComparison.tsx
//
// What the selected pick costs this viewer on each platform that runs it.
// The model's token price is its own, the same on every platform that bills
// per token, so it is stated once above the table (its list prices, input and
// output); the table's column is the figure that does change by platform:
// the viewer's own cost there ($0 where a plan they hold covers it).
import { formatUsd } from "@/lib/benchmark-grid";
import {
  type CostRow,
  hasPoolBilledRow,
  per1kCost,
  rowModel,
  rowPlatform,
  sharedApiRate,
} from "@/lib/cost-format";

interface CostComparisonProps {
  comparisonTable: CostRow[];
  // The picked model's list prices, USD per 1M tokens, when the catalog has
  // them. Without them the table falls back to the session estimate's blended
  // rate per 1k tokens.
  listPrice?: { input: number; output: number } | null;
}

function subscriptionNote(row: Record<string, unknown>): string {
  const label = row.subscription_label;
  if (typeof label === "string" && label) {
    return label;
  }
  const funding = row.funding_source;
  if (funding === "subscription-included") {
    return "Subscription-funded";
  }
  return "Per-token";
}

// Phase 4.8 T3: when the edge has personalized the row to the user's funding it
// carries `your_cost` (display string) + `funded` (boolean). Render that instead
// of the generic funding label; otherwise fall back to subscriptionNote.
function yourCostText(row: Record<string, unknown>): string {
  return typeof row.your_cost === "string" ? row.your_cost : subscriptionNote(row);
}

function fundingCell(row: Record<string, unknown>, personalized: boolean) {
  if (!personalized) {
    return subscriptionNote(row);
  }
  if (row.funded === true) {
    return (
      <span className="font-medium text-green-600 dark:text-green-400">
        ✓ {yourCostText(row)}
      </span>
    );
  }
  return yourCostText(row);
}

const CELL_RULE = "border-b border-brand-slate-100 dark:border-brand-slate-700/70";

export function CostComparison({ comparisonTable, listPrice = null }: CostComparisonProps) {
  if (comparisonTable.length === 0) {
    return null;
  }

  // The funding-rank comparison lists the SAME recommended model across
  // platforms, so a per-row "Model" column just repeats one name and steals the
  // width the "Your cost" column needs. Show it only if the rows actually span
  // more than one model.
  const distinctModels = new Set(comparisonTable.map(rowModel)).size;
  const showModelColumn = distinctModels > 1;
  // Personalized rows carry a `your_cost` string (Phase 4.8 T3). When present,
  // the column shows the user's own cost; otherwise it shows generic funding.
  const personalized = comparisonTable.some(
    (row) => typeof row.your_cost === "string",
  );

  // The model's price is the MODEL's, not a per-platform charge, so for one
  // model it is stated once, above the table. A per-1k rate stays in the
  // table only when it varies by row (rows spanning several models, rare) or
  // nothing above the table states the price.
  const apiRate = showModelColumn || listPrice ? null : sharedApiRate(comparisonTable);
  const showPer1kColumn = showModelColumn || (!listPrice && apiRate === null);
  const poolBilled = hasPoolBilledRow(comparisonTable);
  // The last column is the genuine per-platform figure — the user's own cost
  // when personalized, else the generic funding source.
  const costColLabel = personalized ? "Your cost" : "Funding";

  return (
    <div className="overflow-x-auto">
      {!showModelColumn && listPrice ? (
        <p className="mb-2 text-sm text-brand-slate-600 dark:text-brand-slate-300" data-testid="cost-list-price">
          <span className="font-medium text-brand-slate-900 dark:text-brand-slate-50">
            {rowModel(comparisonTable[0])}
          </span>{" "}
          lists at{" "}
          <span className="font-medium tabular-nums text-brand-slate-900 dark:text-brand-slate-50">
            {formatUsd(listPrice.input)}
          </span>{" "}
          input and{" "}
          <span className="font-medium tabular-nums text-brand-slate-900 dark:text-brand-slate-50">
            {formatUsd(listPrice.output)}
          </span>{" "}
          output per 1M tokens.
        </p>
      ) : apiRate ? (
        <p className="mb-2 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          <span className="font-medium text-brand-slate-900 dark:text-brand-slate-50">
            {rowModel(comparisonTable[0])}
          </span>{" "}
          API rate:{" "}
          <span className="font-medium text-brand-slate-900 dark:text-brand-slate-50">
            {apiRate}
          </span>{" "}
          / 1k tokens
        </p>
      ) : null}
      <table className="w-full min-w-[240px] text-left text-sm">
        <thead>
          <tr className="border-b border-brand-slate-200 text-brand-slate-600 dark:border-brand-slate-700 dark:text-brand-slate-300">
            {showModelColumn ? (
              <th className="py-1.5 pr-3 font-medium">Model</th>
            ) : null}
            <th className="py-1.5 pr-3 font-medium">Platform</th>
            {showPer1kColumn ? (
              <th className="whitespace-nowrap py-1.5 pr-3 font-medium">Per 1k</th>
            ) : null}
            <th className="py-1.5 font-medium">{costColLabel}</th>
          </tr>
        </thead>
        <tbody>
          {comparisonTable.map((row, index) => (
            <tr key={`${rowModel(row)}-${index}`} className={CELL_RULE}>
              {showModelColumn ? (
                <td className="py-1.5 pr-3 text-brand-slate-900 dark:text-brand-slate-50">
                  {rowModel(row)}
                </td>
              ) : null}
              <td className="py-1.5 pr-3 text-brand-slate-700 dark:text-brand-slate-200">
                {rowPlatform(row)}
              </td>
              {showPer1kColumn ? (
                <td className="py-1.5 pr-3 tabular-nums text-brand-slate-700 dark:text-brand-slate-200">
                  {per1kCost(row)}
                </td>
              ) : null}
              <td className="py-1.5 text-brand-slate-600 dark:text-brand-slate-300">
                {fundingCell(row, personalized)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
        The token price is the model&rsquo;s own, the same on every platform that bills per token.{" "}
        <span className="font-medium">{costColLabel}</span> is what changes by platform
        {personalized ? ": $0 where a plan you hold covers it" : ""}.
        {poolBilled ? " Cursor draws from its plan's request pool." : ""}
      </p>
    </div>
  );
}
