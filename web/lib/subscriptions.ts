// web/lib/subscriptions.ts
//
// Catalog-derived subscription options for the onboarding + settings picker
// (issue #152). Replaces the hardcoded 3-item list (which were the founder's
// own subs) with every tier in catalog.json's subscription_tiers, so the
// picker is complete AND auto-follows the daily catalog refresh — the same
// catalog-derivation pattern model-routing.ts uses for pickFreeEngine().
//
// Server-only: importing catalog.json here (a large bundled file) keeps it
// out of the client bundle. Pages call getSubscriptionOptions() and pass the
// small result to the client form as a prop.
import catalog from "@/data/catalog.json";

export interface SubscriptionOption {
  id: string;
  label: string;
  provider: string;
}

interface SubscriptionTier {
  provider: string;
  tier: string;
  monthly_usd: number;
  surface_funded: string[];
  notes?: string;
}

// Preserve the three pre-#152 ids so already-saved profiles (and the
// onboarding/settings specs) keep matching after the switch to catalog
// derivation. Keyed by `${provider}|${tier}`.
const LEGACY_IDS: Record<string, string> = {
  "Anthropic|claude.ai Max ($200)": "claude-max",
  "Cursor|Cursor Ultra": "cursor-ultra",
  "OpenAI|ChatGPT Pro ($200)": "chatgpt-pro",
};

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/\+/g, " plus") // keep "Pro" vs "Pro+" distinct
    .replace(/\(\$(\d+)\)/g, "$1") // "($200)" -> "200"
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Display cleanup to official branding (the catalog stores "claude.ai Max").
function cleanLabel(tier: string): string {
  return tier.replace(/claude\.ai Max/i, "Claude Max");
}

function tierId(provider: string, tier: string): string {
  // Slug the CLEANED label so ids read cleanly (anthropic-claude-max-100,
  // not ...claude-ai-max-100). Deterministic + provider-namespaced.
  return (
    LEGACY_IDS[`${provider}|${tier}`] ??
    slugify(`${provider} ${cleanLabel(tier)}`)
  );
}

const TIERS: SubscriptionTier[] =
  (catalog as { subscription_tiers?: SubscriptionTier[] }).subscription_tiers ??
  [];

// Catalog order is preserved (groups appear in first-seen provider order).
export function getSubscriptionOptions(): SubscriptionOption[] {
  return TIERS.map((t) => ({
    id: tierId(t.provider, t.tier),
    label: cleanLabel(t.tier),
    provider: t.provider,
  }));
}

// Valid id set for server-side validation (e.g. /api/profile).
export const SUBSCRIPTION_IDS: ReadonlySet<string> = new Set(
  getSubscriptionOptions().map((o) => o.id),
);

// Lookup a tier's funded access surfaces by subscription id — the basis for
// the recommender cost tie-break wiring (#163).
export function fundedSurfacesForSubscription(id: string): string[] {
  const tier = TIERS.find((t) => tierId(t.provider, t.tier) === id);
  return tier?.surface_funded ?? [];
}
