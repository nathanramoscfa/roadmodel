// web/components/CostComparison.tsx
interface CostComparisonProps {
  comparisonTable: Record<string, unknown>[];
}

function rowModel(row: Record<string, unknown>): string {
  const name = row.model_name ?? row.model;
  return typeof name === "string" ? name : "—";
}

function rowPlatform(row: Record<string, unknown>): string {
  const name = row.platform_name ?? row.platform;
  return typeof name === "string" ? name : "—";
}

function per1kCost(row: Record<string, unknown>): string {
  const input = row.input_tokens;
  const output = row.output_tokens;
  const total = row.total_usd;
  if (
    typeof input === "number" &&
    typeof output === "number" &&
    typeof total === "number" &&
    input + output > 0
  ) {
    const per1k = (total / (input + output)) * 1000;
    return `$${per1k.toFixed(4)}`;
  }
  if (typeof total === "number") {
    return `$${total.toFixed(4)} (session)`;
  }
  return "—";
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

  const showModelColumn = comparisonTable.length > 1;
  // Personalized rows carry a `your_cost` string (Phase 4.8 T3). When present,
  // the column shows the user's own cost; otherwise it shows generic funding.
  const personalized = comparisonTable.some(
    (row) => typeof row.your_cost === "string",
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[280px] text-left text-sm">
        <thead>
          <tr className="border-b border-brand-slate-200 dark:border-brand-slate-700 text-brand-slate-600 dark:text-brand-slate-300">
            {showModelColumn ? (
              <th className="py-2 pr-3 font-medium">Model</th>
            ) : null}
            <th className="py-2 pr-3 font-medium">Platform</th>
            <th className="py-2 pr-3 font-medium">Per 1k tokens</th>
            <th className="py-2 font-medium">{personalized ? "Your cost" : "Funding"}</th>
          </tr>
        </thead>
        <tbody>
          {comparisonTable.map((row, index) => (
            <tr
              key={`${rowModel(row)}-${index}`}
              className="border-b border-brand-slate-100"
            >
              {showModelColumn ? (
                <td className="py-2 pr-3 text-brand-slate-900 dark:text-brand-slate-50">
                  {rowModel(row)}
                </td>
              ) : null}
              <td className="py-2 pr-3 text-brand-slate-700 dark:text-brand-slate-200">
                {rowPlatform(row)}
              </td>
              <td className="py-2 pr-3 text-brand-slate-700 dark:text-brand-slate-200">
                {per1kCost(row)}
              </td>
              <td className="py-2 text-brand-slate-600 dark:text-brand-slate-300">
                {fundingCell(row, personalized)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
