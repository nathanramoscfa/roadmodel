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
