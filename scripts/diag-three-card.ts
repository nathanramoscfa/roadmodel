// scripts/diag-three-card.ts  (LOCAL behavioral check — not committed)
//
// Confirms PR #320 end-to-end: a SINGLE /api/recommend submit now returns all
// three budget priorities (Cost / Balanced / Quality) as one payload
// ({ recommendations[], primary }). Mints a founder session + gate cookie +
// latency bypass, fires the prompt once, and prints the three cards.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/diag-three-card.ts [BASE_URL] [PROMPT_FILE]

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const PROMPT_FILE =
  process.argv[3] ??
  "/private/tmp/claude-501/-Users-nathanramos-roadmodel/209aa634-18c4-4993-b193-9b9c9bf7861c/scratchpad/equity-prompt.txt";
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

const LABEL: Record<string, string> = {
  cheap: "Cost",
  balanced: "Balanced",
  best: "Quality",
};

interface Pick {
  priority: string;
  model?: string;
  platform?: string;
  settings?: Record<string, unknown>;
  session_cost_estimate?: { total_usd?: number };
}
interface Multi {
  recommendations?: Pick[];
  primary?: string;
}

async function main(): Promise<void> {
  const task = readFileSync(PROMPT_FILE, "utf8").trim();
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const cookie = `${gate}; ${await mintAuthCookie()}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");

  console.log(`Prompt: ${PROMPT_FILE} (${task.length} chars)`);
  console.log(`Base:   ${BASE}\n`);

  const t0 = performance.now();
  const res = await fetch(new URL("/api/recommend", BASE), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie,
      "x-roadmodel-bypass": bypass,
      "user-agent": "rm-threecard-diag/1.0",
    },
    body: JSON.stringify({ task_description: task }),
  });
  const ms = Math.round(performance.now() - t0);
  const raw = await res.text();
  console.log(`POST /api/recommend -> ${res.status} in ${ms}ms\n`);
  if (res.status !== 200) {
    console.error(`non-200: ${raw.slice(0, 400)}`);
    process.exit(1);
  }
  const data = JSON.parse(raw) as Multi;
  const recs = data.recommendations ?? [];
  console.log(`primary (highlighted): ${data.primary} (${LABEL[data.primary ?? ""]})`);
  console.log(`cards returned: ${recs.length}\n`);

  const sigs = new Set<string>();
  for (const r of recs) {
    const s = r.settings ?? {};
    const effort = s.effort ?? s.intelligence ?? "-";
    const star = r.priority === data.primary ? " ★" : "";
    console.log(
      `  [${(LABEL[r.priority] ?? r.priority).padEnd(8)}]${star}  model=${String(r.model).padEnd(18)} ` +
        `platform=${String(r.platform).padEnd(12)} effort=${String(effort).padEnd(6)} ` +
        `thinking=${String(s.thinking ?? "-").padEnd(4)} cost=$${r.session_cost_estimate?.total_usd ?? "-"}`,
    );
    sigs.add(`${r.model}|${effort}|${s.thinking}`);
  }

  console.log("");
  if (recs.length !== 3) {
    console.log(`⚠️  expected 3 cards, got ${recs.length}.`);
  } else if (sigs.size === 1) {
    console.log(
      "ℹ️  all three cards are the SAME pick — valid on a prompt where even cost-optimizing lands on the frontier model (an honest 'they converge' signal).",
    );
  } else {
    console.log(
      `✅ THREE-CARD DIVERGENCE — ${sigs.size} distinct (model, effort, thinking) signatures in ONE request.`,
    );
  }
}

main().catch((e) => {
  console.error("ERROR", e);
  process.exit(1);
});
