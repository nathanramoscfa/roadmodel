// scripts/probe-fable-cachebust.ts
// Runs the HLE Fable-5 trigger with a UNIQUE nonce each call (forces a fresh
// generation past any warm-instance/prompt memoization) to confirm the 0.2.29
// rationale fix live: Quality should be Fable 5 with NO "outside your access".

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { randomUUID } from "node:crypto";
import { deriveGateToken } from "../web/lib/gate";

const BASE = "https://roadmodel.ai";
const MARKERS = ["outside your access", "not recommendable", "was unavailable", "is unavailable"];

function need(n: string): string {
  const v = process.env[n];
  if (!v) {
    throw new Error("Required diagnostic configuration is unavailable.");
  }
  return v;
}

async function mint(): Promise<string> {
  const url = need("SUPABASE_URL");
  const admin = createClient(url, need("SUPABASE_SERVICE_ROLE_KEY"), { auth: { persistSession: false } });
  const { data, error } = await admin.auth.admin.generateLink({ type: "magiclink", email: need("ROADMODEL_DOGFOOD_EMAIL") });
  const th = data?.properties?.hashed_token;
  if (error || !th) {
    throw new Error("Diagnostic session could not be created.");
  }
  let cap: { name: string; value: string }[] = [];
  const ssr = createServerClient(url, need("NEXT_PUBLIC_SUPABASE_ANON_KEY"), {
    cookies: { getAll: () => [], setAll: (cs) => (cap = cs.map(({ name, value }) => ({ name, value }))) },
  });
  const { error: v } = await ssr.auth.verifyOtp({ type: "magiclink", token_hash: th });
  if (v || !cap.length) {
    throw new Error("Diagnostic session could not be verified.");
  }
  return cap.map((c) => `${c.name}=${c.value}`).join("; ");
}

async function main() {
  need("ROADMODEL_DOGFOOD_EMAIL");
  const gate = `roadmodel_gate=${await deriveGateToken(need("SITE_PASSWORD"))}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const cookie = `${gate}; ${await mint()}`;
  for (let i = 0; i < 4; i++) {
    const nonce = randomUUID();
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
    const candidate = best?.rationale_sections?.pick;
    const pick = typeof candidate === "string" ? candidate : "";
    const bad = MARKERS.filter((m) => pick.toLowerCase().includes(m));
    console.log(`\n[run ${i + 1}] status=${res.status} quality_present=${best !== undefined}`);
    console.log(`   pick_length=${pick.length}`);
    console.log(`   contradiction: ${bad.length ? bad.join(", ") : "NONE ✅"}`);
  }
}

main().catch(() => {
  console.error("Diagnostic run failed.");
  process.exitCode = 1;
});
