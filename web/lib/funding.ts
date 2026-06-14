// web/lib/funding.ts
//
// Funding-aware cost annotation for the recommender edge (Phase 4.8 T2,
// issues #260 / #163). Given the recommended model and the user's declared
// funding — held subscriptions + enabled API providers — compute the user's
// CHEAPEST reachable path and a short note to append to the rationale.
//
// Deterministic + catalog-derived. It NEVER changes which model is selected
// (the maintainer decision is consider-all, surface-the-cheaper, never gate);
// it only annotates the recommendation the LLM already returned. Runs purely
// at the web edge — no service / prompt / package change.
import catalog from "@/data/catalog.json";

import {
  fundedSurfacesForSubscription,
  getSubscriptionOptions,
} from "./subscriptions";

interface CatalogModel {
  id: string;
  name: string;
  output_price_per_1m: number | null;
}

interface CatalogMethod {
  id: string;
  provider: string;
  billing: string;
  supports_models: string[];
}

const MODELS: CatalogModel[] =
  (catalog as { models?: CatalogModel[] }).models ?? [];
const METHODS: CatalogMethod[] =
  (catalog as { access_methods?: CatalogMethod[] }).access_methods ?? [];

// Billing kinds reachable with the user's own API key (mirror api-providers.ts).
const API_BILLING: ReadonlySet<string> = new Set([
  "per-token",
  "subscription-or-key",
]);

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  mistral: "Mistral",
  deepseek: "DeepSeek",
  xai: "xAI",
  cursor: "Cursor",
};

// Map both the catalog display name and the id to the model id, since the
// recommender canonicalizes its `model` to the catalog display name (#174)
// but supports_models is keyed by id.
const NAME_TO_ID = new Map<string, string>();
for (const m of MODELS) {
  NAME_TO_ID.set(m.name, m.id);
  NAME_TO_ID.set(m.id, m.id);
}
const ID_TO_MODEL = new Map(MODELS.map((m) => [m.id, m]));
const METHOD_BY_ID = new Map(METHODS.map((m) => [m.id, m]));
// Strip the catalog's " ($NNN)" name disambiguator for a clean note
// (mirrors the picker's display treatment in ProfilePreferencesForm).
const SUB_LABEL = new Map(
  getSubscriptionOptions().map((o) => [
    o.id,
    o.label.replace(/\s*\(\$[\d.,]+\)\s*$/, ""),
  ]),
);

const MONEY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

function providerLabel(id: string): string {
  return PROVIDER_LABELS[id] ?? id;
}

// Compute the user's cheapest funded path to `modelName` and return a short
// note, or null when the user has declared no funding that reaches the model
// (in which case the recommendation is shown without a funding line — never
// suppressed). A held subscription ($0 marginal) always beats an API path.
export function fundingNoteForModel(
  modelName: string,
  subscriptions: readonly string[],
  apiProviders: readonly string[],
): string | null {
  const id = NAME_TO_ID.get(modelName);
  if (!id) return null;

  const reaching = METHODS.filter((m) => m.supports_models.includes(id));
  if (reaching.length === 0) return null;
  const reachingIds = new Set(reaching.map((m) => m.id));

  // 1. Cheapest possible: a held subscription that funds a reaching surface.
  for (const sub of subscriptions) {
    const funded = fundedSurfacesForSubscription(sub);
    if (funded.some((surface) => reachingIds.has(surface))) {
      const label = SUB_LABEL.get(sub) ?? sub;
      return `You have a $0 path to ${modelName} via your ${label} subscription.`;
    }
  }

  // 2. Otherwise: an API provider the user enabled that reaches the model.
  const enabled = new Set(apiProviders);
  const apiMethod = reaching.find(
    (m) => API_BILLING.has(m.billing) && enabled.has(m.provider),
  );
  if (apiMethod) {
    const out = ID_TO_MODEL.get(id)?.output_price_per_1m;
    const costPart =
      typeof out === "number" ? ` (~${MONEY.format(out)}/M output)` : "";
    return `Cheapest for you: ${modelName} via your ${providerLabel(
      apiMethod.provider,
    )} API${costPart}.`;
  }

  return null;
}

// Phase 4.8 T3 (#260 / #163). Re-rank + relabel the recommended model's
// per-platform cost rows to the REQUESTING user's funding, so the cost table
// shows THEIR subscription-$0 vs API-pay-per-token tradeoff instead of the
// service's bundled (founder) funding. Each row gains `your_cost` (display
// string) + `funded` (boolean); rows are reordered funded-first, then by cost.
//
// Deterministic + catalog-derived; runs at the web edge (no service/package
// change). When the user has declared NO funding (anon), rows are returned
// unchanged so the table keeps the service's existing funding column exactly
// as before — mirroring fundingNoteForModel's "no note for anon" posture.
export function personalizeComparison(
  rows: readonly Record<string, unknown>[],
  subscriptions: readonly string[],
  apiProviders: readonly string[],
): Record<string, unknown>[] {
  if ((subscriptions.length === 0 && apiProviders.length === 0) || rows.length === 0) {
    return [...rows];
  }

  // Funded access-method surface -> the held subscription that funds it (first
  // wins), for the "$0 · <subscription>" label.
  const subForSurface = new Map<string, string>();
  for (const sub of subscriptions) {
    const label = SUB_LABEL.get(sub) ?? sub;
    for (const surface of fundedSurfacesForSubscription(sub)) {
      if (!subForSurface.has(surface)) subForSurface.set(surface, label);
    }
  }
  const enabledApi = new Set(apiProviders);

  const RANK_FUNDED = 0;
  const RANK_API = 1;
  const RANK_UNFUNDED = 2;

  const annotated = rows.map((row) => {
    const platformId =
      typeof row.platform_id === "string" ? row.platform_id : "";
    const modelId =
      typeof row.model_id === "string"
        ? row.model_id
        : typeof row.model === "string"
          ? (NAME_TO_ID.get(row.model) ?? "")
          : "";

    let rank: number = RANK_UNFUNDED;
    let yourCost = "pay-per-token (not funded)";
    let funded = false;

    const sub = subForSurface.get(platformId);
    if (sub) {
      rank = RANK_FUNDED;
      funded = true;
      yourCost = `$0 · ${sub}`;
    } else {
      const method = METHOD_BY_ID.get(platformId);
      if (
        method &&
        API_BILLING.has(method.billing) &&
        enabledApi.has(method.provider)
      ) {
        rank = RANK_API;
        const out = modelId
          ? ID_TO_MODEL.get(modelId)?.output_price_per_1m
          : undefined;
        const rate =
          typeof out === "number" ? `~${MONEY.format(out)}/M out` : "pay-per-token";
        yourCost = `${rate} · your ${providerLabel(method.provider)} API`;
      }
    }
    const personalizedRow: Record<string, unknown> = {
      ...row,
      your_cost: yourCost,
      funded,
    };
    return { row: personalizedRow, rank };
  });

  annotated.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    const at =
      typeof a.row.total_usd === "number" ? a.row.total_usd : Number.POSITIVE_INFINITY;
    const bt =
      typeof b.row.total_usd === "number" ? b.row.total_usd : Number.POSITIVE_INFINITY;
    return at - bt;
  });

  return annotated.map((a) => a.row);
}
