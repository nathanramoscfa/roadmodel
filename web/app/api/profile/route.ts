// web/app/api/profile/route.ts
import { NextResponse } from "next/server";
import { z } from "zod";

import { AuthError, createSupabaseServerClient, requireSession } from "@/lib/auth";
import {
  e2eUpsertProfile,
  isE2eAuthEnabled,
  type BudgetPriority,
  type JurisdictionCode,
  type SubscriptionId,
} from "@/lib/profile";
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

const patchSchema = z.object({
  // Catalog-derived id set (issue #152), validated server-side rather than
  // a fixed enum so it tracks catalog.json's subscription_tiers.
  subscriptions: z
    .array(z.string().refine((id) => SUBSCRIPTION_IDS.has(id)))
    .default([]),
  budget_priority: z
    .enum(["cheap", "balanced", "best"])
    .default("balanced"),
  allowed_jurisdictions: z
    .array(jurisdictionEnum)
    .min(1)
    .default(["us", "eu", "uk", "ca", "au", "jp", "kr"]),
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
  const row = {
    subscriptions: payload.subscriptions as SubscriptionId[],
    budget_priority: payload.budget_priority as BudgetPriority,
    allowed_jurisdictions:
      payload.allowed_jurisdictions as JurisdictionCode[],
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
