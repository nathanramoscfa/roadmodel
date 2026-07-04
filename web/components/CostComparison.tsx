// web/components/CostComparison.tsx
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

export function CostComparison({ comparisonTable }: CostComparisonProps) {
  if (comparisonTable.length === 0) {
    return null;
  }

  // The funding-rank comparison lists the SAME recommended model across
  // platforms, so a per-row "Model" column just repeats one name and steals the
  // width the "Your cost" column needs (forcing it to wrap 2-3 lines and pushing
  // the panel below the fold). Show it only if the rows actually span >1 model;
  // otherwise mirror the mock's 3-column Platform / Per 1k / Your cost table.
  const distinctModels = new Set(comparisonTable.map(rowModel)).size;
  const showModelColumn = distinctModels > 1;
  // Personalized rows carry a `your_cost` string (Phase 4.8 T3). When present,
  // the column shows the user's own cost; otherwise it shows generic funding.
  const personalized = comparisonTable.some(
    (row) => typeof row.your_cost === "string",
  );

  // Per-1k is the MODEL's API token rate, not a per-platform charge (access
  // methods carry no per-platform token pricing). When every row is the same
  // model it is identical across platforms — so we lift it OUT of the table and
  // show it once as a model-level rate, leaving "Your cost" as the genuine
  // per-platform column. Only when rows span multiple models (rare) does per-1k
  // vary per row and stay in the table.
  const apiRate = showModelColumn ? null : sharedApiRate(comparisonTable);
  const showPer1kColumn = apiRate === null;
  const poolBilled = hasPoolBilledRow(comparisonTable);
  // The last column is the genuine per-platform figure — the user's own cost
  // when personalized, else the generic funding source.
  const costColLabel = personalized ? "Your cost" : "Funding";

  return (
    <div className="overflow-x-auto">
      {apiRate ? (
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
          <tr className="border-b border-brand-slate-200 dark:border-brand-slate-700 text-brand-slate-600 dark:text-brand-slate-300">
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
            <tr
              key={`${rowModel(row)}-${index}`}
              className="border-b border-brand-slate-100"
            >
              {showModelColumn ? (
                <td className="py-1.5 pr-3 text-brand-slate-900 dark:text-brand-slate-50">
                  {rowModel(row)}
                </td>
              ) : null}
              <td className="py-1.5 pr-3 text-brand-slate-700 dark:text-brand-slate-200">
                {rowPlatform(row)}
              </td>
              {showPer1kColumn ? (
                <td className="py-1.5 pr-3 text-brand-slate-700 dark:text-brand-slate-200">
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
      {/* The per-1k is a MODEL-level token rate: a provider bills it identically
          across its OWN surfaces (Claude Code / claude.ai / its API), so it does
          not vary per platform. Third-party platforms (e.g. Cursor) bill by
          request/subscription pool, not per token, so "Your cost" — not the API
          rate — is what actually differs by platform. */}
      <p className="mt-2 text-xs leading-snug text-brand-slate-400 dark:text-brand-slate-500">
        {showPer1kColumn ? "Per 1k is the model's API token rate" : "The API rate is model-level"} — a
        provider bills it the same across its own surfaces (Claude Code, claude.ai,
        API).{" "}
        {poolBilled ? "Cursor and other" : "Third-party"} platforms bill by
        request/subscription pool, not per token, so{" "}
        <span className="font-medium">{costColLabel}</span> is what changes by platform.
      </p>
    </div>
  );
}
