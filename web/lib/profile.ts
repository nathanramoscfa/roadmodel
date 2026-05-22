// web/lib/profile.ts
//
// Server-side profile helpers for Phase 4 Step 2. Downstream Steps
// 4 + 6 consume getAllowedJurisdictions() at engine-resolution
// time without re-reading the full row on every call.

import type { SupabaseClient } from "@supabase/supabase-js";

import { createSupabaseServerClient } from "./auth";

export type SubscriptionId =
  | "claude-max"
  | "cursor-ultra"
  | "chatgpt-pro";

export type BudgetPriority = "cheap" | "balanced" | "best";

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
  budget_priority: BudgetPriority;
  allowed_jurisdictions: JurisdictionCode[];
  onboarded_at: string | null;
  created_at: string;
  updated_at: string;
}

export const DEFAULT_PROFILE = {
  subscriptions: [] as SubscriptionId[],
  budget_priority: "balanced" as BudgetPriority,
  allowed_jurisdictions: [
    "us",
    "eu",
    "uk",
    "ca",
    "au",
    "jp",
    "kr",
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

export function isE2eAuthEnabled(): boolean {
  return process.env.ROADMODEL_E2E_AUTH === "1";
}

export function e2eGetProfile(userId: string): Profile | null {
  return e2eProfiles.get(userId) ?? null;
}

export function e2eUpsertProfile(
  userId: string,
  row: Omit<Profile, "user_id" | "created_at" | "updated_at">,
): Profile {
  const existing = e2eProfiles.get(userId);
  const now = new Date().toISOString();
  const profile: Profile = {
    user_id: userId,
    subscriptions: row.subscriptions,
    budget_priority: row.budget_priority,
    allowed_jurisdictions: row.allowed_jurisdictions,
    onboarded_at: row.onboarded_at,
    created_at: existing?.created_at ?? now,
    updated_at: now,
  };
  e2eProfiles.set(userId, profile);
  return profile;
}

export function e2eClearProfiles(): void {
  e2eProfiles.clear();
}

function mapRow(row: Record<string, unknown>): Profile {
  return {
    user_id: String(row.user_id),
    subscriptions: (row.subscriptions ?? []) as SubscriptionId[],
    budget_priority: row.budget_priority as BudgetPriority,
    allowed_jurisdictions: (row.allowed_jurisdictions ??
      DEFAULT_PROFILE.allowed_jurisdictions) as JurisdictionCode[],
    onboarded_at: (row.onboarded_at as string | null) ?? null,
    created_at: String(row.created_at),
    updated_at: String(row.updated_at),
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
