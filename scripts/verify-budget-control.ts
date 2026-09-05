// scripts/verify-budget-control.ts  (LOCAL verification — not committed)
//
// Behind-the-gate functional check of the inline budget-priority control
// (PR #317) against gated prod. Mints a founder session + gate cookie, then:
//   1. GET /recommend  — the Cost/Balanced/Quality control RENDERS and is
//      seeded from the profile (reads the SSR-checked radio = baseline B0).
//   2. PATCH /api/profile {budget_priority: B0}  — read the real subscriptions
//      S0 (merge returns the stored row).
//   3. PATCH {budget_priority: NEW != B0}  — assert budget changed AND
//      subscriptions === S0 (the merge preserves them on REAL Supabase; the
//      old full-replace would have wiped them to []).
//   4. GET /settings  — the new value is now the SSR-checked radio (sync).
//   5. PATCH {budget_priority: B0}  — RESTORE the founder's original value.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/verify-budget-control.ts [BASE_URL]

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";

function need(n: string): string {
  const v = process.env[n];
  if (!v) {
    console.error(`missing env ${n}`);
    process.exit(2);
  }
  return v;
}
function gateToken(p: string): string {
  return createHash("sha256").update(`roadmodel-gate-v1:${p}`).digest("hex");
}

async function mintAuthCookie(): Promise<string> {
  const url = need("SUPABASE_URL");
  const admin = createClient(url, need("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false },
  });
  const { data, error } = await admin.auth.admin.generateLink({
    type: "magiclink",
    email: EMAIL,
  });
  const tokenHash = data?.properties?.hashed_token;
  if (error || !tokenHash) {
    console.error("generateLink failed", error);
    process.exit(1);
  }
  let captured: { name: string; value: string }[] = [];
  const ssr = createServerClient(url, need("NEXT_PUBLIC_SUPABASE_ANON_KEY"), {
    cookies: {
      getAll: () => [],
      setAll: (cs) => {
        captured = cs.map(({ name, value }) => ({ name, value }));
      },
    },
  });
  const { error: vErr } = await ssr.auth.verifyOtp({
    type: "magiclink",
    token_hash: tokenHash,
  });
  if (vErr || captured.length === 0) {
    console.error("verifyOtp failed", vErr);
    process.exit(1);
  }
  return captured.map((c) => `${c.name}=${c.value}`).join("; ");
}

// The SSR-rendered budget radio that carries `checked` is the profile's value.
function checkedBudget(html: string): string | null {
  for (const tag of html.match(/<input[^>]*name="budget_priority"[^>]*>/g) ?? []) {
    if (/\schecked\b/.test(tag)) {
      return tag.match(/value="([^"]+)"/)?.[1] ?? null;
    }
  }
  return null;
}

const LABELS: Record<string, string> = { cheap: "Cost", balanced: "Balanced", best: "Quality" };

async function main() {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const cookie = `${gate}; ${await mintAuthCookie()}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const baseHeaders = { cookie, "x-roadmodel-bypass": bypass };
  const fail = (m: string) => {
    console.error(`FAIL: ${m}`);
    process.exit(1);
  };

  // 1. /recommend renders the control + is seeded from the profile.
  const recRes = await fetch(`${BASE}/recommend`, { headers: baseHeaders });
  const recHtml = await recRes.text();
  console.log(`1. GET /recommend -> ${recRes.status}`);
  if (recRes.status !== 200) fail(`/recommend not 200 (gate/auth?) — ${recRes.status}`);
  for (const needle of ['aria-label="Budget priority"', ">Cost<", ">Balanced<", ">Quality<"]) {
    if (!recHtml.includes(needle)) fail(`/recommend HTML missing: ${needle}`);
  }
  const b0 = checkedBudget(recHtml);
  if (!b0) fail("could not read the seeded (checked) budget on /recommend");
  console.log(`   control renders (Cost/Balanced/Quality); seeded value = ${b0} (${LABELS[b0!]})`);

  const patch = async (value: string) => {
    const r = await fetch(`${BASE}/api/profile`, {
      method: "PATCH",
      headers: { ...baseHeaders, "content-type": "application/json" },
      body: JSON.stringify({ budget_priority: value }),
    });
    const body = (await r.json()) as { budget_priority?: string; subscriptions?: string[] };
    return { status: r.status, body };
  };

  // 2. Read real subscriptions (S0) via a no-op budget PATCH (budget := B0).
  const p0 = await patch(b0!);
  if (p0.status !== 200) fail(`baseline PATCH not 200 — ${p0.status}`);
  const s0 = p0.body.subscriptions ?? [];
  console.log(`2. PATCH {budget: ${b0}} -> 200; stored subscriptions = [${s0.join(", ")}]`);

  // 3. Budget-only change to NEW — the MERGE must preserve S0 on real Supabase.
  const nv = b0 === "best" ? "cheap" : "best";
  const p1 = await patch(nv);
  console.log(`3. PATCH {budget: ${nv}} -> ${p1.status}; budget=${p1.body.budget_priority}; subs=[${(p1.body.subscriptions ?? []).join(", ")}]`);
  if (p1.status !== 200) fail(`budget PATCH not 200 — ${p1.status}`);
  if (p1.body.budget_priority !== nv) fail(`budget did not change to ${nv}`);
  const s1 = p1.body.subscriptions ?? [];
  if (JSON.stringify(s1) !== JSON.stringify(s0)) {
    fail(`MERGE BROKEN: subscriptions changed across a budget-only PATCH ([${s0}] -> [${s1}])`);
  }
  console.log(`   MERGE OK — subscriptions preserved across a budget-only PATCH (${s0.length} sub(s)).`);

  // 4. /settings reflects the new choice (sync recommend -> settings).
  const setRes = await fetch(`${BASE}/settings`, { headers: baseHeaders });
  const setBudget = checkedBudget(await setRes.text());
  console.log(`4. GET /settings -> ${setRes.status}; checked budget = ${setBudget} (${LABELS[setBudget ?? ""]})`);
  if (setBudget !== nv) fail(`/settings did not reflect the inline change (got ${setBudget}, want ${nv})`);

  // 5. Restore the founder's original value.
  const pr = await patch(b0!);
  console.log(`5. RESTORE PATCH {budget: ${b0}} -> ${pr.status}; budget=${pr.body.budget_priority}`);
  if (pr.status !== 200 || pr.body.budget_priority !== b0) fail("restore failed — founder budget left changed!");
  if (JSON.stringify(pr.body.subscriptions ?? []) !== JSON.stringify(s0)) fail("restore changed subscriptions!");

  console.log("\n✅ PASS — inline budget control renders, persists, syncs to Settings, and the PATCH merge preserves subscriptions on real Supabase. Original value restored.");
}

main().catch((e) => {
  console.error("ERROR", e);
  process.exit(1);
});
