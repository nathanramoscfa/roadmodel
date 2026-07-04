// web/lib/cost-format.ts
//
// Pure helpers for the "Your cost by platform" table (CostComparison). Kept out
// of the component so the honest-pricing decisions — per-1k is a MODEL-level API
// token rate, not a per-platform charge — are unit-testable in isolation.

export type CostRow = Record<string, unknown>;

export function rowModel(row: CostRow): string {
  const name = row.model_name ?? row.model;
  return typeof name === "string" ? name : "—";
}

export function rowPlatform(row: CostRow): string {
  const name = row.platform_name ?? row.platform;
  return typeof name === "string" ? name : "—";
}

// The model's blended per-1k token rate for this row. It is derived from the
// model's own input/output token prices (NOT the platform), so for one model it
// is identical across platform rows — see sharedApiRate.
export function per1kCost(row: CostRow): string {
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

// A row is "pool-billed" when its platform charges by request/subscription pool
// rather than passing the model's per-token API rate through (e.g. Cursor). For
// those platforms the model's per-1k token rate is NOT what the platform bills,
// so the table leans on "Your cost" and the footnote instead of implying a
// per-token charge that doesn't apply.
export function hasPoolBilledRow(table: CostRow[]): boolean {
  return table.some((row) => row.funding_source === "subscription-pool");
}

// The single model-level API rate when the table is one model across platforms
// (the funding-rank default): the per-1k is the MODEL's blended token rate, so
// it is identical on every row — showing it per-row falsely implies platforms
// charge different token rates. Returns the shared rate string, or null when the
// rows don't share one (multiple models, or missing/session-only token data), in
// which case the caller keeps the per-row Per-1k column.
export function sharedApiRate(table: CostRow[]): string | null {
  if (table.length === 0) {
    return null;
  }
  const rates = new Set<string>();
  for (const row of table) {
    const rate = per1kCost(row);
    if (rate === "—" || rate.includes("(session)")) {
      return null;
    }
    rates.add(rate);
  }
  return rates.size === 1 ? [...rates][0] : null;
}
