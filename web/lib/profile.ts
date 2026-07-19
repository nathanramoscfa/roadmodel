// web/lib/profile.ts
//
// Server-side profile helpers for Phase 4 Step 2. Downstream Steps
// 4 + 6 consume getAllowedJurisdictions() at engine-resolution
// time without re-reading the full row on every call.

import type { SupabaseClient } from "@supabase/supabase-js";

import { createSupabaseServerClient } from "./auth";
import { isE2eAuthEnabled } from "./e2e-mode";

export { isE2eAuthEnabled };

// Catalog-derived (issue #152): subscription ids now come from
// catalog.json's subscription_tiers (see web/lib/subscriptions.ts), so the
// set isn't a fixed compile-time union. Stored values are validated against
// the catalog-derived id set in /api/profile.
export type SubscriptionId = string;

// Catalog-derived (Phase 4.8, #260): provider ids the user reaches via their
// own API key (billing per-token / subscription-or-key). Validated against
// the catalog-derived id set in /api/profile. A boolean signal per provider —
// never the API key itself.
export type ApiProviderId = string;

export type BudgetPriority = "cheap" | "balanced" | "best";

// Consumption-headroom effort axis: whether the recommender keeps reasoning
// EFFORT maxed across all three picks or scales it down the Cost/Balanced/
// Quality ladder. `auto` derives from the user's funded tier price (top consumer
// band => uncapped); `uncapped`/`capped` are explicit overrides. Governs effort
// level only, never which model is chosen.
export type ConsumptionHeadroom = "auto" | "uncapped" | "capped";

export type JurisdictionCode =
  | "us"
  | "eu"
  | "uk"
  | "ca"
  | "au"
  | "jp"
  | "kr"
  | "cn"
  | "ru"
  | "unknown";

export interface Profile {
  user_id: string;
  subscriptions: SubscriptionId[];
  // Phase 4.8 (#260) — providers the user reaches via their own API key.
  // Additive; defaults to [] for pre-4.8 rows.
  api_providers: ApiProviderId[];
  budget_priority: BudgetPriority;
  // Effort-axis control (additive; defaults to 'auto' for pre-existing rows).
  consumption_headroom: ConsumptionHeadroom;
  allowed_jurisdictions: JurisdictionCode[];
  onboarded_at: string | null;
  created_at: string;
  updated_at: string;
  // Phase 4 Step 6 — per-user frontier-roadmap override. Tri-state:
  // null honors env default, true forces frontier on, false forces
  // frontier off. Phase 5 paid-frontier rollout populates this.
  frontier_roadmap_override: boolean | null;
}

export const DEFAULT_PROFILE = {
  subscriptions: [] as SubscriptionId[],
  api_providers: [] as ApiProviderId[],
  budget_priority: "balanced" as BudgetPriority,
  consumption_headroom: "auto" as ConsumptionHeadroom,
  // Default INCLUDES cn (#445): Chinese open-weight models (DeepSeek, GLM via
  // z.ai) are mainstream, so they're available by default. Users opt IN to
  // hiding higher-risk jurisdictions via the "restrict to low-risk" toggle,
  // which narrows to LOW_RISK_JURISDICTIONS (the 7 below without cn). ru /
  // unknown remain opt-in through the custom jurisdiction picker.
  allowed_jurisdictions: [
    "us",
    "eu",
    "uk",
    "ca",
    "au",
    "jp",
    "kr",
    "cn",
  ] as JurisdictionCode[],
};

export class ProfileMissingError extends Error {
  readonly status = 404;
  constructor(message: string = "profile_missing") {
    super(message);
    this.name = "ProfileMissingError";
  }
}

const e2eProfiles = new Map<string, Profile>();

export function e2eGetProfile(userId: string): Profile | null {
  return e2eProfiles.get(userId) ?? null;
}

export function e2eUpsertProfile(
  userId: string,
  row: Omit<
    Profile,
    | "user_id"
    | "created_at"
    | "updated_at"
    | "frontier_roadmap_override"
    | "consumption_headroom"
  > & {
    frontier_roadmap_override?: boolean | null;
    consumption_headroom?: ConsumptionHeadroom;
  },
): Profile {
  const existing = e2eProfiles.get(userId);
  const now = new Date().toISOString();
  const profile: Profile = {
    user_id: userId,
    subscriptions: row.subscriptions,
    api_providers: row.api_providers,
    budget_priority: row.budget_priority,
    consumption_headroom: row.consumption_headroom ?? "auto",
    allowed_jurisdictions: row.allowed_jurisdictions,
    onboarded_at: row.onboarded_at,
    created_at: existing?.created_at ?? now,
    updated_at: now,
    frontier_roadmap_override: row.frontier_roadmap_override ?? null,
  };
  e2eProfiles.set(userId, profile);
  return profile;
}

export function e2eClearProfiles(userId?: string): void {
  // When no userId is passed, clear everything — preserves the
  // original "wipe-all" behavior callers like the unauthenticated
  // /api/test/e2e-reset rely on. With a userId, only that user's
  // row is removed, which lets cross-spec resets stay scoped and
  // avoid races on profiles seeded by a parallel Playwright
  // worker.
  if (!userId) {
    e2eProfiles.clear();
    return;
  }
  e2eProfiles.delete(userId);
}

function mapRow(row: Record<string, unknown>): Profile {
  const override = row.frontier_roadmap_override;
  return {
    user_id: String(row.user_id),
    subscriptions: (row.subscriptions ?? []) as SubscriptionId[],
    api_providers: (row.api_providers ?? []) as ApiProviderId[],
    budget_priority: row.budget_priority as BudgetPriority,
    consumption_headroom: (row.consumption_headroom ??
      "auto") as ConsumptionHeadroom,
    allowed_jurisdictions: (row.allowed_jurisdictions ??
      DEFAULT_PROFILE.allowed_jurisdictions) as JurisdictionCode[],
    onboarded_at: (row.onboarded_at as string | null) ?? null,
    created_at: String(row.created_at),
    updated_at: String(row.updated_at),
    frontier_roadmap_override:
      typeof override === "boolean" ? override : null,
  };
}

async function supabaseForProfile(): Promise<SupabaseClient> {
  return createSupabaseServerClient();
}

export async function getProfile(userId: string): Promise<Profile | null> {
  if (isE2eAuthEnabled()) {
    return e2eGetProfile(userId);
  }
  const supabase = await supabaseForProfile();
  const { data, error } = await supabase
    .from("profiles")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();
  if (error || !data) {
    return null;
  }
  return mapRow(data as Record<string, unknown>);
}

export async function requireProfile(userId: string): Promise<Profile> {
  const profile = await getProfile(userId);
  if (!profile) {
    throw new ProfileMissingError();
  }
  return profile;
}

export function isOnboarded(profile: Profile | null): boolean {
  return profile?.onboarded_at != null;
}

export async function getAllowedJurisdictions(
  userId: string,
): Promise<JurisdictionCode[]> {
  const profile = await getProfile(userId);
  if (!profile) {
    return [...DEFAULT_PROFILE.allowed_jurisdictions];
  }
  return profile.allowed_jurisdictions;
}
