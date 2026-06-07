// scripts/soak-recommend.ts
//
// Phase 4.5 Stream C — the committed recommender SOAK harness. Mints one founder
// session, fires a probe battery against gated prod /api/recommend ANON (free
// tier, twice each for determinism) and SIGNED-IN (frontier tier), then scores
// the result against the DETERMINISTIC subset of the Phase 4.5 quality BAR. The
// subtler quality calls (model-pick vs gold, the LLM-judge "would an Opus@selector
// user accept this") are the AI layer (the gold-differential Workflow), run
// separately; everything here is rule-based and needs no AI API.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/soak-recommend.ts [BASE_URL]
//
// Exit code 0 = all deterministic bar checks pass; 1 = a regression (so the
// scheduled cron can fail/report). Output JSONL: /tmp/rm-soak-recommend.jsonl.

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Model display-name → cost tier (very-high/high/medium/low), from the bundled
// catalog. Used by the B7 tier-stability check. Resolved relative to this
// script so it works regardless of cwd (local from web/, or the CI cron).
const MODEL_TIER: Record<string, string> = (() => {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const cat = JSON.parse(
      readFileSync(join(here, "..", "web", "data", "catalog.json"), "utf8"),
    ) as { models: { name?: string; tier_cost?: string }[] };
    const map: Record<string, string> = {};
    for (const m of cat.models) if (m.name && m.tier_cost) map[m.name] = m.tier_cost;
    return map;
  } catch {
    return {};
  }
})();
// Unknown models fall back to their own name as the "tier" so a flip to an
// unrecognized model still trips the check rather than silently passing.
const modelTier = (name: string | null): string =>
  (name && MODEL_TIER[name]) || `?${name}`;

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";
const OUT = "/tmp/rm-soak-recommend.jsonl";

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

interface Probe {
  id: string;
  task: string;
}
const PROBES: Probe[] = [
  { id: "creative", task: "Write a short story about a robot learning to garden." },
  { id: "coding-cli", task: "Help me build a small Python CLI that fetches weather data and caches it locally." },
  { id: "planning", task: "Draft a one-week study plan for a graduate-level linear algebra exam." },
  { id: "data-analysis", task: "Analyze a 2 GB CSV of retail sales and surface seasonal demand trends with charts." },
  { id: "legacy-refactor", task: "Refactor a 50-file legacy Django monolith into modular services with tests." },
  { id: "math-proof", task: "Prove that the square root of 2 is irrational, step by step, rigorously." },
  { id: "vision-ocr", task: "Extract line-item tables from a scanned PDF invoice image and output CSV." },
  { id: "ambiguous", task: "help" },
  { id: "non-english", task: "Écris un poème sur la mer, en français, avec des rimes riches." },
  { id: "cost-bulk", task: "Cheapest capable model to classify 10,000 support tickets by sentiment; accuracy matters." },
  { id: "fenced-json", task: 'Review this config and flag risks: a JSON config {"retries":5,"timeout_ms":0}' },
  { id: "agentic-tooluse", task: "Build an autonomous agent that monitors my inbox, drafts replies, and books meetings via API." },
];

// Deterministic defect signatures (mirror the Task-1 + T-measure analysis).
const LEAK = /##\s|\bDay\s*1\b|Morning\s*\(|Step\s*1:|```|\n\s*[-*]\s+\w|Majestueuse|ravisse|\n\d+\.\s/m;
const THINK_PROSE = /thinking is set to|THINKING is set|thinking level|reasoning is set/i;
const NO_THINK_PLATFORMS = new Set(["Cursor", "xAI API"]);
// Models that should NOT route to the Cursor pool when a $0 dedicated sub funds them.
const CLAUDE_RE = /opus|sonnet|haiku|claude/i;
const GPT_RE = /gpt-/i;

interface Row {
  id: string;
  mode: "anon" | "authed";
  iter: number;
  status: number;
  ms: number;
  model: string | null;
  platform: string | null;
  thinking: string | null;
  conversation: string | null;
  rationale: string;
}

async function runProbe(p: Probe, authCookie: string | null, gate: string, bypass: string, iter: number): Promise<Row> {
  const cookie = authCookie ? `${gate}; ${authCookie}` : gate;
  const mode = authCookie ? "authed" : "anon";
  const t0 = performance.now();
  let status = 0;
  let payload: Record<string, unknown> = {};
  try {
    const res = await fetch(new URL("/api/recommend", BASE), {
      method: "POST",
      headers: { "content-type": "application/json", cookie, "x-roadmodel-bypass": bypass, "user-agent": "rm-soak/1.0" },
      body: JSON.stringify({ task_description: p.task }),
    });
    status = res.status;
    try {
      payload = JSON.parse(await res.text());
    } catch {
      payload = {};
    }
  } catch {
    /* network error → status 0 */
  }
  const ms = Math.round(performance.now() - t0);
  const settings = (payload.settings ?? {}) as Record<string, unknown>;
  const thinking = (settings.thinking ?? settings.effort ?? settings.intelligence ?? null) as string | null;
  return {
    id: p.id,
    mode,
    iter,
    status,
    ms,
    model: (payload.model ?? null) as string | null,
    platform: (payload.platform ?? null) as string | null,
    thinking,
    conversation: (payload.conversation ?? null) as string | null,
    rationale: typeof payload.rationale === "string" ? payload.rationale : "",
  };
}

function pctile(xs: number[], p: number): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
}

interface Check {
  id: string;
  bar: string;
  pass: boolean;
  detail: string;
}

function score(rows: Row[]): Check[] {
  const ok = rows.filter((r) => r.status === 200);
  const anon = ok.filter((r) => r.mode === "anon");
  const authed = ok.filter((r) => r.mode === "authed");
  const checks: Check[] = [];

  // B0 — every call succeeded.
  const non200 = rows.filter((r) => r.status !== 200);
  checks.push({ id: "all-200", bar: "B0", pass: non200.length === 0, detail: `${non200.length} non-200` });

  // B1 — no task-execution leak.
  const leaks = ok.filter((r) => LEAK.test(r.rationale));
  checks.push({ id: "no-task-leak", bar: "B1", pass: leaks.length === 0, detail: leaks.map((r) => `${r.mode}/${r.id}`).join(",") || "clean" });

  // B3 — platform = funded surface (Claude not on Cursor; GPT not on per-token OpenAI API).
  const platErr = ok.filter(
    (r) =>
      (CLAUDE_RE.test(r.model ?? "") && r.platform === "Cursor") ||
      (GPT_RE.test(r.model ?? "") && r.platform === "OpenAI API"),
  );
  checks.push({ id: "platform-funded", bar: "B3", pass: platErr.length === 0, detail: platErr.map((r) => `${r.id}:${r.model}/${r.platform}`).join(",") || "clean" });

  // B4 — THINKING N/A on no-thinking surfaces (structured field).
  const thinkErr = ok.filter((r) => NO_THINK_PLATFORMS.has(r.platform ?? "") && r.thinking !== null && r.thinking !== "N/A");
  checks.push({ id: "thinking-na-cursor", bar: "B4", pass: thinkErr.length === 0, detail: thinkErr.map((r) => `${r.id}:${r.thinking}`).join(",") || "clean" });

  // B5 — no dropped output field (conversation present on every 200).
  const noConv = ok.filter((r) => r.conversation === null);
  checks.push({ id: "conversation-present", bar: "B5", pass: noConv.length === 0, detail: `${noConv.length} missing` });

  // B7 — determinism, recalibrated to TIER-stability (2026-06-07). Exact-model
  // determinism is too strict for a recommender: a vague prompt legitimately
  // ties several tier-appropriate models (e.g. Opus 4.8 vs Gemini 3.1 Pro for
  // "creative"). What must be stable run-to-run is the quality TIER, not the
  // exact model. The exact-model flip is kept as a non-blocking watch.
  const byId: Record<string, Row[]> = {};
  for (const r of anon) (byId[r.id] ||= []).push(r);
  const tierFlaky = Object.entries(byId).filter(
    ([, rs]) => rs.length >= 2 && new Set(rs.map((r) => modelTier(r.model))).size > 1,
  );
  checks.push({ id: "determinism-tier", bar: "B7", pass: tierFlaky.length === 0, detail: tierFlaky.map(([id]) => id).join(",") || "tier-stable" });
  const modelFlaky = Object.entries(byId).filter(
    ([, rs]) => rs.length >= 2 && new Set(rs.map((r) => `${r.model}|${r.platform}`)).size > 1,
  );
  checks.push({ id: "watch:exact-model-flip", bar: "B7", pass: true, detail: modelFlaky.map(([id]) => id).join(",") || "stable" });

  // B8 — free-tier latency P50<=3s / P95<=5s.
  const aMs = anon.map((r) => r.ms);
  const aP50 = pctile(aMs, 50);
  const aP95 = pctile(aMs, 95);
  checks.push({ id: "latency-free", bar: "B8", pass: aP50 <= 3000 && aP95 <= 5000, detail: `P50=${aP50}ms P95=${aP95}ms` });

  // B9 — frontier latency P50<=8s / P95<=15s (provisional).
  const uMs = authed.map((r) => r.ms);
  const uP50 = pctile(uMs, 50);
  const uP95 = pctile(uMs, 95);
  checks.push({ id: "latency-frontier", bar: "B9", pass: uP50 <= 8000 && uP95 <= 15000, detail: `P50=${uP50}ms P95=${uP95}ms` });

  // Tier-active — frontier is engaged (signed-in meaningfully slower than free).
  checks.push({ id: "tier-active", bar: "T3b", pass: uP50 > aP50 + 1500, detail: `frontier P50 ${uP50} vs free ${aP50}` });

  // Residual watch (NON-blocking, reported): thinking-prose on Cursor (#188), Ultracode on refactor (#189).
  const prose = ok.filter((r) => NO_THINK_PLATFORMS.has(r.platform ?? "") && THINK_PROSE.test(r.rationale));
  checks.push({ id: "watch:thinking-prose", bar: "#188", pass: true, detail: `${prose.length} prose slips (non-blocking)` });

  return checks;
}

async function main(): Promise<void> {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const bypass = process.env.ROADMODEL_LATENCY_BYPASS_TOKEN ?? "";
  const authCookie = await mintAuthCookie();

  const rows: Row[] = [];
  // anon twice (determinism) + authed once (frontier).
  for (const iter of [1, 2]) {
    for (const p of PROBES) {
      rows.push(await runProbe(p, null, gate, bypass, iter));
      await sleep(200);
    }
  }
  for (const p of PROBES) {
    rows.push(await runProbe(p, authCookie, gate, bypass, 1));
    await sleep(200);
  }

  writeFileSync(OUT, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");

  const checks = score(rows);
  const blocking = checks.filter((c) => !c.id.startsWith("watch:"));
  const failed = blocking.filter((c) => !c.pass);
  console.log(`\n=== SOAK SCORECARD (${rows.length} calls -> ${OUT}) ===`);
  for (const c of checks) {
    const tag = c.id.startsWith("watch:") ? "WATCH" : c.pass ? "PASS " : "FAIL ";
    console.log(`  [${tag}] ${c.bar.padEnd(4)} ${c.id.padEnd(22)} ${c.detail}`);
  }
  console.log(`\nRESULT: ${failed.length === 0 ? "PASS" : "FAIL"} (${blocking.length - failed.length}/${blocking.length} blocking checks)`);
  console.log("SOAK_DONE");
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
