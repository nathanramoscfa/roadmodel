// web/app/api/profile/route.ts
import { NextResponse } from "next/server";
import { z } from "zod";

import { AuthError, createSupabaseServerClient, requireSession } from "@/lib/auth";
import {
  DEFAULT_PROFILE,
  e2eUpsertProfile,
  getProfile,
  isE2eAuthEnabled,
  type ApiProviderId,
  type BudgetPriority,
  type JurisdictionCode,
  type SubscriptionId,
} from "@/lib/profile";
import { API_PROVIDER_IDS } from "@/lib/api-providers";
import { SUBSCRIPTION_IDS } from "@/lib/subscriptions";

const jurisdictionEnum = z.enum([
  "us",
  "eu",
  "uk",
  "ca",
  "au",
  "jp",
  "kr",
  "cn",
  "ru",
  "unknown",
]);

// Every field is OPTIONAL so this is a true PATCH: a caller may send any
// subset and the rest is preserved from the existing row (see the merge in
// PATCH). The inline /recommend budget control sends only `budget_priority`;
// onboarding / settings still send the full body (merge == replace for them).
const patchSchema = z.object({
  // Catalog-derived id set (issue #152), validated server-side rather than
  // a fixed enum so it tracks catalog.json's subscription_tiers.
  subscriptions: z
    .array(z.string().refine((id) => SUBSCRIPTION_IDS.has(id)))
    .optional(),
  // Catalog-derived API-provider id set (Phase 4.8, #260); same server-side
  // validation pattern as subscriptions. Boolean signal only — no keys.
  api_providers: z
    .array(z.string().refine((id) => API_PROVIDER_IDS.has(id)))
    .optional(),
  budget_priority: z.enum(["cheap", "balanced", "best"]).optional(),
  allowed_jurisdictions: z.array(jurisdictionEnum).min(1).optional(),
  skip: z.boolean().default(false),
});

export async function PATCH(req: Request): Promise<Response> {
  let user;
  try {
    user = await requireSession();
  } catch (err) {
    if (err instanceof AuthError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad_input" }, { status: 400 });
  }

  const parsed = patchSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "bad_input" }, { status: 400 });
  }

  const payload = parsed.data;
  // True PATCH: merge only the provided fields over the existing profile (or
  // sane defaults for a brand-new row). A partial update — e.g. the inline
  // budget-priority control on /recommend sending only `budget_priority` —
  // must NOT reset the user's subscriptions / jurisdictions to defaults.
  const existing = await getProfile(user.id);
  const base = existing ?? DEFAULT_PROFILE;
  const row = {
    subscriptions: (payload.subscriptions ??
      base.subscriptions) as SubscriptionId[],
    api_providers: (payload.api_providers ??
      base.api_providers) as ApiProviderId[],
    budget_priority: (payload.budget_priority ??
      base.budget_priority) as BudgetPriority,
    allowed_jurisdictions: (payload.allowed_jurisdictions ??
      base.allowed_jurisdictions) as JurisdictionCode[],
    onboarded_at: new Date().toISOString(),
  };

  if (isE2eAuthEnabled()) {
    const profile = e2eUpsertProfile(user.id, row);
    return NextResponse.json(profile);
  }

  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("profiles")
    .upsert({
      user_id: user.id,
      ...row,
    })
    .select("*")
    .single();

  if (error || !data) {
    console.error("profile upsert failed", error);
    return NextResponse.json(
      { error: "profile_save_failed" },
      { status: 500 },
    );
  }

  return NextResponse.json(data);
}
