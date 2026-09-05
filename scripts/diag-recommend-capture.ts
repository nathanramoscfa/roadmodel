// scripts/diag-recommend-capture.ts  (Task 1 diagnostic — LOCAL, not committed)
//
// Full-payload variant of dogfood-recommend.ts. Mints one founder session,
// fires the SAME 12-probe battery ANON + SIGNED-IN against gated prod
// /api/recommend, and writes the COMPLETE client-facing JSON payload per
// probe (not just lengths) to /tmp/rm-diag-app.jsonl — so the gold-standard
// differential can compare full rationale text, settings, and comparison
// tables against an Opus@selector reference for the same prompts.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/diag-recommend-capture.ts [BASE_URL]

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import { writeFileSync } from "node:fs";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";
const OUT = "/tmp/rm-diag-app.jsonl";

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

interface Probe {
  id: string;
  task: string;
  note: string;
}
const PROBES: Probe[] = [
  { id: "creative", task: "Write a short story about a robot learning to garden.", note: "creative writing" },
  { id: "coding-cli", task: "Help me build a small Python CLI that fetches weather data and caches it locally.", note: "everyday coding" },
  { id: "planning", task: "Draft a one-week study plan for a graduate-level linear algebra exam.", note: "planning" },
  { id: "data-analysis", task: "Analyze a 2 GB CSV of retail sales and surface seasonal demand trends with charts.", note: "data/agentic" },
  { id: "legacy-refactor", task: "Refactor a 50-file legacy Django monolith into modular services with tests.", note: "long-context coding" },
  { id: "math-proof", task: "Prove that the square root of 2 is irrational, step by step, rigorously.", note: "reasoning" },
  { id: "vision-ocr", task: "Extract line-item tables from a scanned PDF invoice image and output CSV.", note: "multimodal/vision" },
  { id: "ambiguous", task: "help", note: "ambiguous/short" },
  { id: "non-english", task: "Écris un poème sur la mer, en français, avec des rimes riches.", note: "non-English" },
  { id: "cost-bulk", task: "Cheapest capable model to classify 10,000 support tickets by sentiment; accuracy matters.", note: "cost-sensitive" },
  { id: "fenced-json", task: "Review this config and flag risks:\n```json\n{\"retries\":5,\"timeout_ms\":0}\n```", note: "fenced JSON in input" },
  { id: "agentic-tooluse", task: "Build an autonomous agent that monitors my inbox, drafts replies, and books meetings via API.", note: "agentic tool-use" },
];

async function runProbe(p: Probe, authCookie: string | null, gate: string, bypass: string) {
  const cookie = authCookie ? `${gate}; ${authCookie}` : gate;
  const mode = authCookie ? "authed" : "anon";
  const t0 = performance.now();
  let status = 0;
  let raw = "";
  let payload: unknown = null;
  let errText = "";
  try {
    const res = await fetch(new URL("/api/recommend", BASE), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie,
        "x-roadmodel-bypass": bypass,
        "user-agent": "rm-diag/1.0",
      },
      body: JSON.stringify({ task_description: p.task }),
    });
    status = res.status;
    raw = await res.text();
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = null;
    }
  } catch (e) {
    errText = String(e);
  }
  const ms = Math.round(performance.now() - t0);
  return { id: p.id, note: p.note, task: p.task, mode, status, ms, payload, raw_len: raw.length, error: errText || null };
}

async function main(): Promise<void> {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const bypass = process.env.ROADMODEL_LATENCY_BYPASS_TOKEN ?? "";
  const authCookie = await mintAuthCookie();

  const rows: unknown[] = [];
  for (const mode of ["anon", "authed"] as const) {
    for (const p of PROBES) {
      const row = await runProbe(p, mode === "authed" ? authCookie : null, gate, bypass);
      rows.push(row);
      const pl = (row.payload ?? {}) as Record<string, unknown>;
      const st = (pl.settings ?? {}) as Record<string, unknown>;
      console.log(
        `[${mode}] ${p.id.padEnd(16)} ${row.status} ${String(row.ms).padStart(5)}ms ` +
          `model=${pl.model ?? "-"} plat=${pl.platform ?? "-"} max=${st.max_mode ?? "-"} ` +
          `think=${st.thinking ?? "-"} ratLen=${typeof pl.rationale === "string" ? pl.rationale.length : "-"}`,
      );
      await sleep(250);
    }
  }

  writeFileSync(OUT, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  console.log(`\nWROTE ${rows.length} rows -> ${OUT}`);
  console.log(`DIAG_DONE`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
