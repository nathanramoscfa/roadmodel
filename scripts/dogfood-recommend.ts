// scripts/dogfood-recommend.ts
//
// Reusable recommender-only dogfooding harness. Mints one real authed
// session (founder), fires a curated battery of /api/recommend probes
// ANONYMOUS and SIGNED-IN against the gated prod app, and captures
// status + wall latency + parsed payload shape to a JSONL file for
// downstream (workflow) analysis. The only prod writes are the recommend
// calls themselves (each a cheap Gemini 2.5 Flash request).
//
// Run from web/ with NODE_PATH so the bare @supabase/* imports resolve
// against web/node_modules (this file lives in scripts/, a sibling of
// web/ — same pattern as scripts/measure-recommend-latency.ts):
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/dogfood-recommend.ts [BASE_URL]
//
// with-prod-secrets.sh exports the keychain secrets (SUPABASE_URL,
// SUPABASE_SERVICE_ROLE_KEY, NEXT_PUBLIC_SUPABASE_ANON_KEY, SITE_PASSWORD,
// ROADMODEL_LATENCY_BYPASS_TOKEN). Override the dogfood account with
// ROADMODEL_DOGFOOD_EMAIL. Output: a fresh private JSONL file.

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { deriveGateToken } from "../web/lib/gate";
import { createPrivateOutput } from "./private-diagnostic-output";
import { setTimeout as sleep } from "node:timers/promises";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "";

function need(n: string): string {
  const v = process.env[n];
  if (!v) {
    throw new Error("Required diagnostic configuration is missing.");
  }
  return v;
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
    throw new Error("Session generation failed.");
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
    throw new Error("Session verification failed.");
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
  { id: "fenced-json", task: "Review this config and flag risks:\n```json\n{\"retries\":5,\"timeout_ms\":0}\n```", note: "fenced JSON in input (#5-adjacent)" },
  { id: "whitespace", task: "   ", note: "whitespace-only edge" },
];

interface RecommendPayload {
  model?: string;
  platform?: string;
  session_cost_estimate?: { total_usd?: number };
  settings?: { rationale?: unknown };
  comparison_table?: unknown[];
}

interface Row {
  id: string;
  note: string;
  mode: "anon" | "authed";
  status: number;
  ok: boolean;
  ms: number;
  model: string | null;
  platform: string | null;
  cost_total_usd: number | null;
  comparison_rows: number | null;
  rationale_len: number | null;
  rationale_tail: string | null;
  raw_len: number;
  error: string | null;
}

async function runProbe(p: Probe, authCookie: string | null, gate: string, bypass: string): Promise<Row> {
  const cookie = authCookie ? `${gate}; ${authCookie}` : gate;
  const t0 = performance.now();
  let status = 0;
  let ok = false;
  let raw = "";
  let errText = "";
  let payload: RecommendPayload | null = null;
  try {
    const res = await fetch(new URL("/api/recommend", BASE), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie,
        "x-roadmodel-bypass": bypass,
        "user-agent": "rm-dogfood/1.0",
      },
      body: JSON.stringify({ task_description: p.task }),
    });
    status = res.status;
    ok = res.ok;
    raw = await res.text();
    try {
      payload = JSON.parse(raw) as RecommendPayload;
    } catch {
      payload = null;
    }
  } catch {
    errText = "request_failed";
  }
  const ms = Math.round(performance.now() - t0);
  const rationale =
    typeof payload?.settings?.rationale === "string" ? payload.settings.rationale : null;
  return {
    id: p.id,
    note: p.note,
    mode: authCookie ? "authed" : "anon",
    status,
    ok,
    ms,
    model: payload?.model ?? null,
    platform: payload?.platform ?? null,
    cost_total_usd: payload?.session_cost_estimate?.total_usd ?? null,
    comparison_rows: Array.isArray(payload?.comparison_table) ? payload.comparison_table.length : null,
    rationale_len: rationale ? rationale.length : null,
    rationale_tail: rationale ? rationale.slice(-70) : null,
    raw_len: raw.length,
    error: errText || (ok ? null : raw.slice(0, 240)),
  };
}

async function main(): Promise<void> {
  const output = createPrivateOutput({ prefix: "roadmodel-dogfood" });
  const OUT = output.path;
  try {
    const gate = `roadmodel_gate=${await deriveGateToken(need("SITE_PASSWORD"))}`;
    const bypass = process.env.ROADMODEL_LATENCY_BYPASS_TOKEN ?? "";
    const authCookie = await mintAuthCookie();

    const rows: Row[] = [];
    for (const mode of ["anon", "authed"] as const) {
      for (const p of PROBES) {
        const row = await runProbe(p, mode === "authed" ? authCookie : null, gate, bypass);
        rows.push(row);
        console.log(
          `[${mode}] ${p.id.padEnd(15)} ${row.status} ${String(row.ms).padStart(5)}ms ` +
            `cmp=${row.comparison_rows ?? "-"} rat=${row.rationale_len ?? "-"}`,
        );
        await sleep(250);
      }
    }

    output.write(rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    const fails = rows.filter((r) => !r.ok);
    const slow = rows.filter((r) => r.ms > 8000);
    console.log(`\nWROTE ${rows.length} rows -> ${OUT}`);
    console.log(`NON_200=${fails.length} SLOW_over_8s=${slow.length}`);
    console.log(`DOGFOOD_DONE`);
  } finally {
    output.close();
  }
}

main().catch(() => {
  console.error("Diagnostic run failed.");
  process.exitCode = 1;
});
