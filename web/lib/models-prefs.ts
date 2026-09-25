// web/lib/models-prefs.ts
//
// The /models view a visitor last chose (Provider, Jurisdiction, Cost tier,
// Group by, and Ratings / Benchmark scores), kept in a first-party cookie so
// the page opens the way they left it. A cookie rather than localStorage
// because the server reads it: the first render already carries the
// visitor's view, so there is no flash of the default table and no hydration
// mismatch. The cookie holds only those choices, scoped to /models.
//
// parsePrefs treats the cookie as untrusted input and falls back field by
// field; a choice the catalog no longer offers (a provider that left) falls
// back to "all" in filtersFromPrefs. savePrefs is the one client-only export.
import type { CostTier } from "@/lib/catalog-fields";
import type { CatalogFilters } from "@/lib/catalog-filter";

export const PREFS_COOKIE = "roadmodel_models_view";
const PREFS_PATH = "/models";
const ONE_YEAR = 60 * 60 * 24 * 365;

export type Grouping = "tier" | "quality";
export type View = "ratings" | "benchmarks";

export interface ModelsPrefs {
  // "all", or one provider label ("Anthropic").
  provider: string;
  // The jurisdictions the visitor UNchecked. Kept as the excluded set so a
  // jurisdiction the catalog adds later starts checked, like the rest.
  hideJurisdictions: string[];
  cost: "all" | CostTier;
  groupBy: Grouping;
  view: View;
}

export const DEFAULT_PREFS: ModelsPrefs = {
  provider: "all",
  hideJurisdictions: [],
  cost: "all",
  groupBy: "tier",
  view: "ratings",
};

const COSTS: readonly string[] = ["all", "low", "medium", "high", "very-high"];

export function parsePrefs(raw: string | null | undefined): ModelsPrefs {
  if (!raw) return DEFAULT_PREFS;
  let value: unknown;
  try {
    // Next hands the server the decoded value; document.cookie is encoded.
    value = JSON.parse(raw.startsWith("%") ? decodeURIComponent(raw) : raw);
  } catch {
    return DEFAULT_PREFS;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return DEFAULT_PREFS;
  const o = value as Record<string, unknown>;
  return {
    provider: typeof o.provider === "string" && o.provider.length <= 64 ? o.provider : "all",
    hideJurisdictions: Array.isArray(o.hideJurisdictions)
      ? o.hideJurisdictions.filter((c): c is string => typeof c === "string" && c.length <= 16).slice(0, 32)
      : [],
    cost: typeof o.cost === "string" && COSTS.includes(o.cost) ? (o.cost as ModelsPrefs["cost"]) : "all",
    groupBy: o.groupBy === "quality" ? "quality" : "tier",
    view: o.view === "benchmarks" ? "benchmarks" : "ratings",
  };
}

// The saved choices as filters over today's catalog.
export function filtersFromPrefs(
  prefs: ModelsPrefs,
  providers: readonly string[],
  jurisdictions: readonly string[],
): CatalogFilters {
  return {
    provider: providers.includes(prefs.provider) ? prefs.provider : "all",
    jurisdictions: new Set(jurisdictions.filter((c) => !prefs.hideJurisdictions.includes(c))),
    cost: prefs.cost,
  };
}

export function prefsFromFilters(
  f: CatalogFilters,
  jurisdictions: readonly string[],
): Pick<ModelsPrefs, "provider" | "hideJurisdictions" | "cost"> {
  return {
    provider: f.provider,
    hideJurisdictions: jurisdictions.filter((c) => !f.jurisdictions.has(c)),
    cost: f.cost,
  };
}

// Client only: merge a change into the saved choices. The table (Group by,
// view) and the explorer (filters) each save their own part. A browser that
// blocks cookies still gets a working page; it just forgets.
export function savePrefs(patch: Partial<ModelsPrefs>): void {
  try {
    const hit = document.cookie.split("; ").find((c) => c.startsWith(`${PREFS_COOKIE}=`));
    const current = parsePrefs(hit ? decodeURIComponent(hit.slice(PREFS_COOKIE.length + 1)) : null);
    const value = encodeURIComponent(JSON.stringify({ ...current, ...patch }));
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${PREFS_COOKIE}=${value}; Path=${PREFS_PATH}; Max-Age=${ONE_YEAR}; SameSite=Lax${secure}`;
  } catch {
    // Cookies unavailable.
  }
}
