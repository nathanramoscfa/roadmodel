// web/lib/catalog-models.ts
//
// Server-only adapter: reads data/catalog.json and projects it to the small,
// serializable ModelRow[] the /models page passes to the client table. Importing
// catalog.json here (not in the client component) keeps it out of the client
// bundle — the same pattern as lib/api-providers.ts and lib/subscriptions.ts.
import catalog from "@/data/catalog.json";

import type { Category, CostTier, ModelRow, Rating } from "@/lib/catalog-fields";

interface RawModel {
  id: string;
  name: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  cache_read_per_1m: number | null;
  tier_cost: string;
  tiers: Record<string, string>;
  jurisdiction: string;
  headline_benchmarks?: string;
  pricing_notes?: string;
  best_for?: string;
}

const MODELS = (catalog as { models?: RawModel[] }).models ?? [];

export function getModelRows(): ModelRow[] {
  return MODELS.map((m) => ({
    id: m.id,
    name: m.name,
    input_price_per_1m: m.input_price_per_1m,
    output_price_per_1m: m.output_price_per_1m,
    cache_read_per_1m: m.cache_read_per_1m ?? null,
    tier_cost: m.tier_cost as CostTier,
    tiers: m.tiers as Record<Category, Rating>,
    jurisdiction: m.jurisdiction,
    headline_benchmarks: m.headline_benchmarks ?? "",
    pricing_notes: m.pricing_notes ?? "",
    best_for: m.best_for ?? "",
  }));
}

// "2026-06-21T12:53:54Z" → "2026-06-21 12:53 UTC". Falls back to the raw value.
export function getCatalogGeneratedAt(): string {
  const raw = (catalog as { generated_at_utc?: string }).generated_at_utc ?? "";
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(raw);
  return m ? `${m[1]} ${m[2]} UTC` : raw;
}
