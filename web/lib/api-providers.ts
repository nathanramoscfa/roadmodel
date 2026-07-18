// web/lib/api-providers.ts
//
// Catalog-derived API / pay-per-token provider options for the Settings +
// onboarding "API access" picker (Phase 4.8 T1, issue #260). A provider
// appears here when it has at least one access method reachable via the
// user's OWN direct API key — billing `per-token` or `subscription-or-key`
// — so the list auto-follows the daily catalog refresh (the same
// catalog-derivation pattern subscriptions.ts uses). Cursor, whose only
// billing is `subscription-pool` (no bring-your-own-key path), is correctly
// excluded.
//
// This captures only a per-provider boolean SIGNAL ("I use this provider's
// API"); roadmodel never stores the user's API keys.
//
// Server-only: importing catalog.json keeps it out of the client bundle.
// Pages call getApiProviderOptions() and pass the small result to the client
// form as a prop.
import catalog from "@/data/catalog.json";

export interface ApiProviderOption {
  // Provider id as it appears in catalog access_methods (lowercase, e.g.
  // "anthropic"). Stored verbatim in profile.api_providers.
  id: string;
  // Display name for the picker (e.g. "Anthropic").
  label: string;
  // Provider's home jurisdiction (catalog `provider_jurisdiction`, e.g. "us",
  // "eu", "cn"). Lets the Settings form hide higher-risk providers when the
  // "restrict to low-risk jurisdictions" filter is on (#445). "unknown" when
  // the catalog omits it.
  jurisdiction: string;
}

interface AccessMethod {
  provider: string;
  billing: string;
  provider_jurisdiction?: string;
}

// Billing kinds that mean "reachable with the user's own API key /
// pay-per-token". `subscription-included` and `subscription-pool` are
// subscription-only and do NOT count as an API path.
const API_BILLING: ReadonlySet<string> = new Set([
  "per-token",
  "subscription-or-key",
]);

// Display names for known providers; the fallback capitalizes the id so a
// newly-federated provider still renders a sane label before it's added here.
const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  mistral: "Mistral",
  deepseek: "DeepSeek",
  xai: "xAI",
  zai: "z.ai",
  groq: "Groq",
  cursor: "Cursor",
};

function providerLabel(id: string): string {
  return PROVIDER_LABELS[id] ?? id.charAt(0).toUpperCase() + id.slice(1);
}

const METHODS: AccessMethod[] =
  (catalog as { access_methods?: AccessMethod[] }).access_methods ?? [];

// Distinct API-path providers, in first-seen catalog order (access_methods is
// sorted by id at build time, so this is deterministic).
export function getApiProviderOptions(): ApiProviderOption[] {
  const seen = new Set<string>();
  const options: ApiProviderOption[] = [];
  for (const method of METHODS) {
    if (!API_BILLING.has(method.billing)) continue;
    if (seen.has(method.provider)) continue;
    seen.add(method.provider);
    options.push({
      id: method.provider,
      label: providerLabel(method.provider),
      jurisdiction: method.provider_jurisdiction ?? "unknown",
    });
  }
  return options;
}

// Valid id set for server-side validation (e.g. /api/profile).
export const API_PROVIDER_IDS: ReadonlySet<string> = new Set(
  getApiProviderOptions().map((o) => o.id),
);
