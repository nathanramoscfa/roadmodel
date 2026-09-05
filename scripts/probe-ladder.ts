// scripts/probe-ladder.ts
//
// Diagnostic for the "Quality=Fable 5, Opus skipped" ladder complaint. Mints a
// founder session and fires a pyfinlab-style long-context financial-audit task
// against gated prod signed-in (frontier gpt-5-mini) N times, printing all three
// picks + their settings + the full rationale sections + backup — so we can see
// whether the top rung is a non-deterministic Fable 5 / Opus 4.8 coin-flip and
// read the exact (contradictory) rationale.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/probe-ladder.ts [N] [BASE_URL]

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";

const N = Number(process.argv[2] ?? "3");
const BASE = process.argv[3] ?? "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";

// Faithful reconstruction of the pyfinlab task class: a long-context, planning-
// heavy financial pipeline audit inside a real repo.
const TASK = [
  "<task><mission>In the pyfinlab repo (Windows; conda env `pyfinlab` at",
  "C:\\Users\\Admin\\miniconda3\\envs\\pyfinlab), perform a comprehensive,",
  "long-context audit of the entire performance-review recommendation pipeline:",
  "read every module across the repo, trace data flow from ingestion through the",
  "factor models to the reporting layer, identify correctness and numerical-",
  "stability risks in a critical financial pipeline, and produce a step-by-step",
  "remediation plan with verification steps.</mission></task>",
].join(" ");

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

interface Pick {
  priority?: string;
  model?: string;
  platform?: string;
  settings?: Record<string, unknown> | null;
  rationale_sections?: Record<string, string> | null;
  backup?: { model?: string; platform?: string } | null;
}
interface Payload {
  primary?: string;
  recommendations?: Pick[];
}

async function run(i: number, cookie: string, bypass: string) {
  const res = await fetch(`${BASE}/api/recommend`, {
    method: "POST",
    headers: { "content-type": "application/json", cookie, "X-Roadmodel-Bypass": bypass },
    body: JSON.stringify({ task_description: TASK }),
  });
  const raw = await res.text();
  let p: Payload | null = null;
  try {
    p = JSON.parse(raw) as Payload;
  } catch {
    p = null;
  }
  console.log(`\n########## RUN ${i + 1} (status ${res.status}) ##########`);
  if (!p) {
    console.log("non-JSON:", raw.slice(0, 300));
    return;
  }
  for (const rec of p.recommendations ?? []) {
    const eff = rec.settings
      ? (rec.settings.effort ?? rec.settings.intelligence ?? rec.settings.thinking ?? "")
      : "";
    console.log(
      `\n[${(rec.priority ?? "?").toUpperCase()}] ${rec.model} — ${rec.platform}` +
        (eff ? `  (effort/thinking: ${eff})` : ""),
    );
    if (rec.backup?.model) console.log(`   backup: ${rec.backup.model}`);
    const rs = rec.rationale_sections;
    if (rs) {
      for (const k of ["task", "pick", "run", "effort"]) {
        if (rs[k]) console.log(`   ${k.toUpperCase()}: ${rs[k]}`);
      }
    }
  }
}

async function main() {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const authCookie = await mintAuthCookie();
  const cookie = `${gate}; ${authCookie}`;
  for (let i = 0; i < N; i++) await run(i, cookie, bypass);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
