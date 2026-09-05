// scripts/probe-fable-trigger.ts
//
// Finds a prompt whose QUALITY pick is Fable 5 (post Opus-anchor rule, Fable 5
// only wins when the task SPECIFICALLY favors its strengths: HLE-extreme
// reasoning + Terminal-Bench Hard agentic). Fires each candidate signed-in
// (frontier) and prints the QUALITY pick + whether it's Fable 5.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/probe-fable-trigger.ts

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";

const BASE = "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";

const CANDIDATES: { id: string; task: string }[] = [
  {
    id: "hle-extreme",
    task:
      "Answer a battery of Humanity's-Last-Exam-grade closed-ended questions spanning graduate " +
      "mathematics, theoretical physics, and molecular biology — frontier, expert-only problems " +
      "where only the single most capable reasoning model succeeds. Maximize raw reasoning " +
      "capability; cost and latency are no object.",
  },
  {
    id: "terminal-hard",
    task:
      "Autonomously complete the hardest end-to-end terminal tasks with no human help: from a bare " +
      "shell, diagnose and repair a broken multi-service build, resolve obscure toolchain and " +
      "linker failures, and get the full test suite green — maximum agentic command-line capability " +
      "is the binding constraint.",
  },
  {
    id: "hle-research",
    task:
      "Attack an open research-frontier problem in theoretical computer science: propose and rigorously " +
      "justify a novel result at the edge of what is known, the hardest possible expert reasoning where " +
      "peak model capability is the only thing that matters.",
  },
  {
    id: "terminal-agentic-max",
    task:
      "Act as a fully autonomous terminal agent on the single hardest agentic coding benchmark: plan, " +
      "execute, and self-verify a long chain of interdependent shell + code operations across a large " +
      "repo, recovering from failures without any human intervention. Peak agentic-terminal capability required.",
  },
];

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
  const { data, error } = await admin.auth.admin.generateLink({ type: "magiclink", email: EMAIL });
  const tokenHash = data?.properties?.hashed_token;
  if (error || !tokenHash) {
    console.error("generateLink failed", error);
    process.exit(1);
  }
  let captured: { name: string; value: string }[] = [];
  const ssr = createServerClient(url, need("NEXT_PUBLIC_SUPABASE_ANON_KEY"), {
    cookies: { getAll: () => [], setAll: (cs) => (captured = cs.map(({ name, value }) => ({ name, value }))) },
  });
  const { error: vErr } = await ssr.auth.verifyOtp({ type: "magiclink", token_hash: tokenHash });
  if (vErr || captured.length === 0) {
    console.error("verifyOtp failed", vErr);
    process.exit(1);
  }
  return captured.map((c) => `${c.name}=${c.value}`).join("; ");
}

interface Pick {
  priority?: string;
  model?: string;
  settings?: Record<string, unknown> | null;
  rationale_sections?: Record<string, string> | null;
}
interface Payload {
  recommendations?: Pick[];
}

async function main() {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const cookie = `${gate}; ${await mintAuthCookie()}`;
  for (const c of CANDIDATES) {
    const res = await fetch(`${BASE}/api/recommend`, {
      method: "POST",
      headers: { "content-type": "application/json", cookie, "X-Roadmodel-Bypass": bypass },
      body: JSON.stringify({ task_description: c.task }),
    });
    let p: Payload | null = null;
    try {
      p = JSON.parse(await res.text()) as Payload;
    } catch {
      p = null;
    }
    const best = (p?.recommendations ?? []).find((r) => r.priority === "best");
    const model = best?.model ?? "?";
    const hit = /fable/i.test(model) ? "  <<< FABLE 5" : "";
    console.log(`\n[${c.id}] QUALITY = ${model}${hit}`);
    if (best?.rationale_sections?.pick) console.log(`   PICK: ${best.rationale_sections.pick}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
