// scripts/probe-fable-cachebust.ts
// Runs the HLE Fable-5 trigger with a UNIQUE nonce each call (forces a fresh
// generation past any warm-instance/prompt memoization) to confirm the 0.2.29
// rationale fix live: Quality should be Fable 5 with NO "outside your access".

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";

const BASE = "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";
const MARKERS = ["outside your access", "not recommendable", "was unavailable", "is unavailable"];

function need(n: string): string {
  const v = process.env[n];
  if (!v) {
    console.error(`missing env ${n}`);
    process.exit(2);
  }
  return v;
}
const gateToken = (p: string) =>
  createHash("sha256").update(`roadmodel-gate-v1:${p}`).digest("hex");

async function mint(): Promise<string> {
  const url = need("SUPABASE_URL");
  const admin = createClient(url, need("SUPABASE_SERVICE_ROLE_KEY"), { auth: { persistSession: false } });
  const { data, error } = await admin.auth.admin.generateLink({ type: "magiclink", email: EMAIL });
  const th = data?.properties?.hashed_token;
  if (error || !th) {
    console.error("generateLink failed", error);
    process.exit(1);
  }
  let cap: { name: string; value: string }[] = [];
  const ssr = createServerClient(url, need("NEXT_PUBLIC_SUPABASE_ANON_KEY"), {
    cookies: { getAll: () => [], setAll: (cs) => (cap = cs.map(({ name, value }) => ({ name, value }))) },
  });
  const { error: v } = await ssr.auth.verifyOtp({ type: "magiclink", token_hash: th });
  if (v || !cap.length) {
    console.error("verifyOtp failed", v);
    process.exit(1);
  }
  return cap.map((c) => `${c.name}=${c.value}`).join("; ");
}

async function main() {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const cookie = `${gate}; ${await mint()}`;
  for (let i = 0; i < 4; i++) {
    const nonce = createHash("sha256").update(`${i}-${need("SITE_PASSWORD")}`).digest("hex").slice(0, 8);
    const task =
      `[ref ${nonce}] Answer the hardest Humanity's-Last-Exam (HLE) questions across graduate mathematics, ` +
      `theoretical physics, and molecular biology. ONLY the current HLE leaderboard leader is acceptable — a ` +
      `model scoring below ~50% on HLE is insufficient no matter its other benchmarks or cost. Maximize HLE ` +
      `accuracy above every other consideration; per-token cost is irrelevant.`;
    const res = await fetch(`${BASE}/api/recommend`, {
      method: "POST",
      headers: { "content-type": "application/json", cookie, "X-Roadmodel-Bypass": bypass },
      body: JSON.stringify({ task_description: task }),
    });
    let best: { model?: string; rationale_sections?: Record<string, string> | null } | undefined;
    try {
      const p = JSON.parse(await res.text()) as {
        recommendations?: { priority?: string; model?: string; rationale_sections?: Record<string, string> | null }[];
      };
      best = (p.recommendations ?? []).find((r) => r.priority === "best");
    } catch {
      best = undefined;
    }
    const pick = best?.rationale_sections?.pick ?? "";
    const bad = MARKERS.filter((m) => pick.toLowerCase().includes(m));
    console.log(`\n[run ${i + 1}] QUALITY = ${best?.model ?? "?"}`);
    console.log(`   PICK: ${pick}`);
    console.log(`   contradiction: ${bad.length ? bad.join(", ") : "NONE ✅"}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
