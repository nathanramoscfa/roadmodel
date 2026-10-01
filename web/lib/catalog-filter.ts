// web/lib/catalog-filter.ts
//
// The /models filters (Provider, Jurisdiction, Weights, Cost tier), shared by
// the table and both chart panels so one choice narrows all three. PURE — no
// catalog import, safe for the client.
//
// The filters do two different jobs:
//   Provider, Jurisdiction and Weights say which models you would use at all.
//     They set the POOL the cost/quality frontier is drawn from: with China
//     unchecked, the ring goes to the best non-Chinese model at each price;
//     with Open weights chosen, to the best model you could run yourself; and
//     no card names an excluded model as the one that beats yours.
//   Cost tier is a price band to look at, not a model you rule out. It
//     narrows what is shown and leaves the frontier alone, so a cheaper tier's
//     model can still be named as the top score at a pricier tier's prices
//     (the page's point), and the cheapest model in a band is never ringed
//     just because the band starts there.
// The Score is never refitted: it measures a model against the whole market's
// price line, so a filter changes which models are drawn, never their Scores.
import { blendedPrice, frontierLeaders } from "@/lib/benchmark-grid";
import {
  COST_TIER_DEFS,
  JURISDICTION_DEFS,
  WEIGHTS_DEFS,
  type CostTier,
  type ModelRow,
  type Weights,
} from "@/lib/catalog-fields";

export interface CatalogFilters {
  // "all", or one provider label ("Anthropic").
  provider: string;
  // The jurisdiction codes to show; every one starts checked.
  jurisdictions: ReadonlySet<string>;
  // "all", or only the open- or closed-weight models.
  weights: "all" | Weights;
  cost: "all" | CostTier;
}

// The catalog's jurisdiction codes in the order the checkboxes show them: the
// definitions table's order (us, eu, cn, …), then any code it does not list.
export function jurisdictionCodes(rows: readonly Pick<ModelRow, "jurisdiction">[]): string[] {
  const known = Object.keys(JURISDICTION_DEFS);
  const rank = (c: string) => {
    const i = known.indexOf(c);
    return i === -1 ? known.length : i;
  };
  return Array.from(new Set(rows.map((r) => r.jurisdiction))).sort(
    (a, b) => rank(a) - rank(b) || a.localeCompare(b),
  );
}

export function allFilters(jurisdictions: readonly string[]): CatalogFilters {
  return { provider: "all", jurisdictions: new Set(jurisdictions), weights: "all", cost: "all" };
}

// "US + EU"; "none" when every box is unchecked.
export function jurisdictionLabel(codes: readonly string[], checked: ReadonlySet<string>): string {
  const on = codes.filter((c) => checked.has(c));
  return on.length === 0 ? "none" : on.map((c) => c.toUpperCase()).join(" + ");
}

function narrowsJurisdiction(f: CatalogFilters, codes: readonly string[]): boolean {
  return codes.some((c) => !f.jurisdictions.has(c));
}

// Does the model survive the Provider, Jurisdiction and Weights choices?
export function inPool(m: Pick<ModelRow, "provider" | "jurisdiction" | "open_weights">, f: CatalogFilters): boolean {
  return (
    (f.provider === "all" || m.provider === f.provider) &&
    f.jurisdictions.has(m.jurisdiction) &&
    (f.weights === "all" || m.open_weights === (f.weights === "open"))
  );
}

// Which models the frontier compares, as a modifier for "every ___ model":
// the weights choice ("open-weight"), then the provider when one is chosen
// (each provider sits in one jurisdiction), else the checked jurisdictions
// ("open-weight US + EU"); null when the pool is the whole catalog.
export function poolScope(f: CatalogFilters, codes: readonly string[]): string | null {
  const parts: string[] = [];
  if (f.weights !== "all") parts.push(WEIGHTS_DEFS[f.weights].scope);
  if (f.provider !== "all") parts.push(f.provider);
  else if (narrowsJurisdiction(f, codes)) parts.push(jurisdictionLabel(codes, f.jurisdictions));
  return parts.length === 0 ? null : parts.join(" ");
}

// Every active filter in a line ("US + EU · High cost"); null when none is.
export function filterSummary(f: CatalogFilters, codes: readonly string[]): string | null {
  const parts: string[] = [];
  if (f.provider !== "all") parts.push(f.provider);
  if (narrowsJurisdiction(f, codes)) parts.push(`Jurisdiction: ${jurisdictionLabel(codes, f.jurisdictions)}`);
  if (f.weights !== "all") parts.push(`${WEIGHTS_DEFS[f.weights].label} weights`);
  if (f.cost !== "all") parts.push(`${COST_TIER_DEFS[f.cost].label} cost`);
  return parts.length === 0 ? null : parts.join(" · ");
}

// The rows with the frontier recomputed over exactly these rows: fresh
// copies, each on the frontier or naming the model among them that beats it.
// The server marks the whole catalog this way; the page re-marks the pool.
export function withFrontier(rows: readonly ModelRow[]): ModelRow[] {
  const out = rows.map((r) => ({ ...r, value_frontier: false, value_beaten_by: null as string | null }));
  // Priced like the Score and the charts (blended), so every value figure on
  // the page reads one price per model.
  const leaders = frontierLeaders(
    out.map((r) => ({
      row: r,
      price: blendedPrice(r.input_price_per_1m, r.output_price_per_1m),
      index: r.aa_index,
    })),
  );
  for (const [p, leader] of leaders) {
    if (leader === p) p.row.value_frontier = true;
    else p.row.value_beaten_by = leader.row.id;
  }
  return out;
}
