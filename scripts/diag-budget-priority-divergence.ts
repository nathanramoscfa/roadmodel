// scripts/diag-budget-priority-divergence.ts  (LOCAL behavioral check — not committed)
//
// Confirms PR #319 end-to-end: the same complex prompt, fired at all three
// budget priorities (Cost/Balanced/Quality) as the signed-in founder, must now
// produce DIVERGENT recommendations (before the fix, Cost == Quality). Mints a
// founder session + gate cookie + latency bypass, then POSTs /api/recommend
// with budget_priority overridden in the BODY (no profile mutation) for each of
// cheap / balanced / best, and prints model + settings per priority.
//
// The prompt is read from a path arg (default: the scratchpad equity prompt) so
// no personal-detail prompt is committed to this public repo.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/diag-budget-priority-divergence.ts \
//       [BASE_URL] [PROMPT_FILE]

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const PROMPT_FILE =
  process.argv[3] ??
  "/private/tmp/claude-501/-Users-nathanramos-roadmodel/209aa634-18c4-4993-b193-9b9c9bf7861c/scratchpad/equity-prompt.txt";
// The frontier selector is non-deterministic, so a single shot per priority is
// noise. Sample N times per priority (default 5) and compare DISTRIBUTIONS.
const SAMPLES = Number(process.env.SAMPLES ?? "5");
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

const LABELS: Record<string, string> = {
  cheap: "Cost",
  balanced: "Balanced",
  best: "Quality",
};

interface Payload {
  model?: string;
  platform?: string;
  settings?: Record<string, unknown>;
  session_cost_estimate?: { total_usd?: number };
}

// The edge now fans out all three priorities in ONE response
// ({ recommendations: [{priority, model, settings, …}], primary }). Pull the
// pick whose priority matches the budget we sent; fall back to the legacy
// single-pick shape for older deploys.
function pickForBudget(parsed: unknown, budget: string): Payload | null {
  if (parsed && typeof parsed === "object") {
    const recs = (parsed as { recommendations?: unknown }).recommendations;
    if (Array.isArray(recs)) {
      const rec = recs.find(
        (r) => (r as { priority?: string }).priority === budget,
      ) as Payload | undefined;
      return rec ?? null;
    }
    return parsed as Payload;
  }
  return null;
}

// The prod selector caches by request; set BUST=1 to append a neutral unique
// marker per call so each sample is an INDEPENDENT cold draw (defeats the cache
// for a true distribution). Off by default (a warm cache is the real UX).
const BUST = process.env.BUST === "1";

async function fire(
  budget: string,
  task: string,
  cookie: string,
  bypass: string,
  nonce: string,
): Promise<{ budget: string; status: number; ms: number; payload: Payload | null }> {
  const body = BUST ? `${task}\n\n(internal ref: ${nonce})` : task;
  const t0 = performance.now();
  const res = await fetch(new URL("/api/recommend", BASE), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie,
      "x-roadmodel-bypass": bypass,
      "user-agent": "rm-budget-diag/1.0",
    },
    body: JSON.stringify({ task_description: body, budget_priority: budget }),
  });
  const ms = Math.round(performance.now() - t0);
  const raw = await res.text();
  let payload: Payload | null = null;
  try {
    payload = pickForBudget(JSON.parse(raw), budget);
  } catch {
    payload = null;
  }
  return { budget, status: res.status, ms, payload };
}

async function main(): Promise<void> {
  const task = readFileSync(PROMPT_FILE, "utf8").trim();
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const cookie = `${gate}; ${await mintAuthCookie()}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");

  console.log(`Prompt: ${PROMPT_FILE} (${task.length} chars)`);
  console.log(`Base:   ${BASE}   Samples/priority: ${SAMPLES}\n`);

  const means: Record<string, number> = {};
  // Sequential (not parallel) so the per-IP rate limiter and the engine cache
  // behave like a real session; founder is rate-limit exempt but keep it gentle.
  for (const budget of ["cheap", "balanced", "best"]) {
    const costs: number[] = [];
    const models: Record<string, number> = {};
    const efforts: Record<string, number> = {};
    for (let i = 0; i < SAMPLES; i++) {
      const r = await fire(budget, task, cookie, bypass, `${budget}-${i}-${BASE.length}`);
      const p = r.payload ?? {};
      const s = (p.settings ?? {}) as Record<string, unknown>;
      const model = String(p.model ?? "-");
      const effort = String(s.effort ?? s.intelligence ?? "-");
      const cost = p.session_cost_estimate?.total_usd ?? 0;
      costs.push(cost);
      models[model] = (models[model] ?? 0) + 1;
      efforts[effort] = (efforts[effort] ?? 0) + 1;
      console.log(
        `[${LABELS[budget].padEnd(8)}] #${i + 1} ${r.status} ${String(r.ms).padStart(6)}ms  ` +
          `model=${model.padEnd(12)} effort=${String(s.effort ?? s.intelligence ?? "-").padEnd(6)} ` +
          `thinking=${String(s.thinking ?? "-").padEnd(4)} cost=$${cost.toFixed(4)}`,
      );
    }
    const mean = costs.reduce((a, b) => a + b, 0) / (costs.length || 1);
    means[budget] = mean;
    const fmt = (o: Record<string, number>) =>
      Object.entries(o)
        .sort((a, b) => b[1] - a[1])
        .map(([k, n]) => `${k}×${n}`)
        .join(", ");
    console.log(
      `  -> ${LABELS[budget]} mean est. cost=$${mean.toFixed(4)}  models: ${fmt(models)}  effort: ${fmt(efforts)}\n`,
    );
  }

  console.log("=== Summary (mean session-cost estimate per priority) ===");
  console.log(`  Cost     (cheap)    $${means.cheap.toFixed(4)}`);
  console.log(`  Balanced (balanced) $${means.balanced.toFixed(4)}`);
  console.log(`  Quality  (best)     $${means.best.toFixed(4)}`);
  const ordered = means.cheap <= means.balanced && means.balanced <= means.best;
  console.log("");
  if (means.cheap < means.best) {
    console.log(
      `✅ LEVER WORKS — Cost trends cheaper than Quality ($${means.cheap.toFixed(4)} < $${means.best.toFixed(4)})` +
        (ordered ? ", and Cost ≤ Balanced ≤ Quality holds." : " (Balanced not strictly ordered — LLM noise)."),
    );
  } else {
    console.log(
      `⚠️  NO COST SEPARATION — Cost ($${means.cheap.toFixed(4)}) is not cheaper than Quality ($${means.best.toFixed(4)}).` +
        " Expected before the #319 service deploy; re-run after it lands.",
    );
  }
}

main().catch((e) => {
  console.error("ERROR", e);
  process.exit(1);
});
