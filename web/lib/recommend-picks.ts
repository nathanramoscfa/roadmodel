// web/lib/recommend-picks.ts
//
// What /recommend shows about a PICKED model beyond the recommender's own
// answer: the same facts /models shows for it (cost tier, AA Intelligence
// Index, Score, the cost/quality frontier, the seven S→D letters and whether
// each was measured or estimated), so a pick reads in the catalog's own terms.
// Built on the server from the catalog rows and handed to the client as a
// slim, name-keyed table: the recommender names models by display name
// ("Sonnet 5.5"), and the service ships through PyPI while the catalog ships
// with the web, so a name can briefly differ in spelling ("Claude 4.5 Haiku"
// vs "Haiku 4.5"). nameKey makes both spellings meet.

import {
  CATEGORY_FIGURE,
  COMPOSITE_DERIVATION,
  DERIVED_CATEGORIES,
  benchSortValue,
  blendedPrice,
  compositeScores,
} from "./benchmark-grid";
import { CATEGORY_ORDER, type Category, type ModelRow } from "./catalog-fields";

// Sorted word tokens without the maker prefix: "Claude Haiku 4.5", "Haiku 4.5"
// and "claude-4.5-haiku" all key the same (lib/funding.ts does the same).
export function nameKey(name: string): string {
  return name
    .toLowerCase()
    .split(/[\s_-]+/)
    .filter((t) => t && t !== "claude")
    .sort()
    .join(" ");
}

// Per category, whether a model's letter was MEASURED (derived from an
// Artificial Analysis figure) or estimated by the catalog automation: the
// same rule as the /models ratings cells.
export function measuredCategories(models: readonly ModelRow[]): Map<string, Category[]> {
  const out = new Map<string, Category[]>(models.map((m) => [m.id, []]));
  for (const cat of CATEGORY_ORDER) {
    if (!DERIVED_CATEGORIES.has(cat)) continue;
    const composite = COMPOSITE_DERIVATION[cat];
    if (composite) {
      const scores = compositeScores(models, composite.parts);
      for (const m of models) if (scores.has(m.id)) out.get(m.id)?.push(cat);
      continue;
    }
    const key = CATEGORY_FIGURE[cat];
    if (!key) continue;
    for (const m of models) if (benchSortValue(m.bench, key) !== null) out.get(m.id)?.push(cat);
  }
  return out;
}

// A catalog row without its long prose fields: enough for the hover cards
// /models uses (FrontierPointCard and friends), small enough to ship to the
// client for every model.
export type SlimRow = ModelRow;

export interface PicksData {
  // nameKey(display name or id) -> model id
  keys: Record<string, string>;
  rows: Record<string, SlimRow>;
  measured: Record<string, Category[]>;
}

export function picksData(models: readonly ModelRow[]): PicksData {
  const measured = measuredCategories(models);
  const keys: Record<string, string> = {};
  const rows: Record<string, SlimRow> = {};
  const basis: Record<string, Category[]> = {};
  for (const m of models) {
    keys[nameKey(m.name)] = m.id;
    keys[nameKey(m.id)] = m.id;
    rows[m.id] = { ...m, headline_benchmarks: "", pricing_notes: "", best_for: "" };
    basis[m.id] = measured.get(m.id) ?? [];
  }
  return { keys, rows, measured: basis };
}

export function rowForPick(data: PicksData, model: string | null | undefined): SlimRow | null {
  if (!model) return null;
  const id = data.keys[nameKey(model)];
  return id ? (data.rows[id] ?? null) : null;
}

export function blendedOf(row: Pick<ModelRow, "input_price_per_1m" | "output_price_per_1m">): number {
  return blendedPrice(row.input_price_per_1m, row.output_price_per_1m);
}
