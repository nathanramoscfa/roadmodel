// scripts/probe-funding-lanes.ts
//
// Phase 4.11 live lane probe (V6.5): five requests against production, one per
// funding lane, then a check that ONLY the founder's call spent the operator's
// money. It is the hands-off authenticated recipe of probe-ladder.ts and the
// Step 2 flow: a throwaway uninvited user is created through the Supabase admin
// API and deleted in a finally block, the founder session is minted from a
// magic link, and nothing is typed or pasted.
//
//   1. signed-out free text                → 402 funding_required, with options
//   2. the uninvited probe account         → 402 funding_required
//   3. a bogus visitor key                 → 401 visitor_key_rejected
//   4. an anonymous Quick pick (keyless)   → 200, three rungs
//   5. the founder, no bypass header       → 200, the operator lane
//
// Then, from the ledger and the spend counter: probes 1-4 leave the counter
// where it was and write no funded_by 'operator' row; probe 5 writes exactly
// one, and the counter moves by that row's cost_usd.
//
// Run from the repo root (the wrapper reads every secret from the keychain):
//   NODE_PATH="$(pwd)/web/node_modules" scripts/with-prod-secrets.sh \
//       node web/node_modules/.bin/tsx scripts/probe-funding-lanes.ts [BASE_URL]
//
// Output is the lane, the status code and PASS/FAIL per probe. No cookie, key,
// user id or response body is printed. Exit 0 = every assertion held.

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash, randomBytes } from "node:crypto";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const FOUNDER_EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";
// numeric(10,6) rounds a cost to six places; the counter adds the raw float.
const COST_TOLERANCE = 1e-6;
const SETTLE_MS = 30_000;

function need(name: string): string {
  const v = process.env[name];
  if (!v) {
    console.error(`missing env ${name} (run under scripts/with-prod-secrets.sh)`);
    process.exit(2);
  }
  return v;
}

const SUPABASE_URL = need("SUPABASE_URL");
const SERVICE_KEY = need("SUPABASE_SERVICE_ROLE_KEY");
const ANON_KEY = need("NEXT_PUBLIC_SUPABASE_ANON_KEY");
const GATE = `roadmodel_gate=${createHash("sha256").update(`roadmodel-gate-v1:${need("SITE_PASSWORD")}`).digest("hex")}`;
// The keychain may hold either the REST URL (https://...) or the TCP form
// (rediss://default:<password>@host:6379). Upstash serves REST on the same
// host, so only the hostname is kept: the URL's own credentials are dropped
// and never sent, printed or logged.
const REDIS_BASE = (() => {
  const raw = need("UPSTASH_REDIS_URL");
  if (raw.startsWith("http")) return raw.replace(/\/$/, "");
  try {
    return `https://${new URL(raw).hostname}`;
  } catch {
    // Not the error itself: Node attaches the offending input to it.
    console.error("UPSTASH_REDIS_URL is neither an https URL nor a redis URL");
    process.exit(2);
  }
})();
const REDIS_TOKEN = need("UPSTASH_REDIS_TOKEN");

// The only errors whose text is printed. Anything else (a fetch TypeError can
// carry the request URL, credentials included) is reported by class name only.
class ProbeError extends Error {}

const admin = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { persistSession: false } });

async function sessionCookieFor(email: string): Promise<string> {
  const { data, error } = await admin.auth.admin.generateLink({ type: "magiclink", email });
  const tokenHash = data?.properties?.hashed_token;
  if (error || !tokenHash) throw new ProbeError("generateLink failed");
  let captured: { name: string; value: string }[] = [];
  const ssr = createServerClient(SUPABASE_URL, ANON_KEY, {
    cookies: {
      getAll: () => [],
      setAll: (cs) => {
        captured = cs.map(({ name, value }) => ({ name, value }));
      },
    },
  });
  const { error: vErr } = await ssr.auth.verifyOtp({ type: "magiclink", token_hash: tokenHash });
  if (vErr || captured.length === 0) throw new ProbeError("verifyOtp failed");
  return captured.map((c) => `${c.name}=${c.value}`).join("; ");
}

function utcDay(): string {
  return new Date().toISOString().slice(0, 10);
}

// The operator's spend counter for today (web/lib/spend-guard.ts), or null
// when today's counter has not been seeded yet.
async function readCounter(): Promise<number | null> {
  const res = await fetch(`${REDIS_BASE}/get/spend:${utcDay()}`, {
    headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
  });
  const body = (await res.json()) as { result: string | number | null };
  return body.result === null || body.result === undefined ? null : Number(body.result);
}

interface LedgerRow {
  id: number;
  cost_usd: string | number | null;
  funded_by: string | null;
  user_id: string | null;
  outcome: string;
}

async function ledger(sinceIso: string): Promise<LedgerRow[]> {
  const q = new URLSearchParams({
    select: "id,cost_usd,funded_by,user_id,outcome",
    ts: `gte.${sinceIso}`,
    order: "id",
  });
  const res = await fetch(`${SUPABASE_URL}/rest/v1/audit_log?${q}`, {
    headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` },
  });
  if (!res.ok) throw new ProbeError(`audit_log read ${res.status}`);
  return (await res.json()) as LedgerRow[];
}

// The operator's spend the ledger holds for today: operator rows plus the
// unstamped history the spend guard also sums.
async function ledgerOperatorSpend(): Promise<number> {
  const start = new Date();
  start.setUTCHours(0, 0, 0, 0);
  const rows = await ledger(start.toISOString());
  return rows
    .filter((r) => r.funded_by === "operator" || r.funded_by === null)
    .reduce((sum, r) => sum + (Number(r.cost_usd) || 0), 0);
}

interface Outcome {
  lane: string;
  status: number;
  ok: boolean;
  detail?: string;
}
const results: Outcome[] = [];

function record(lane: string, status: number, ok: boolean, detail?: string): void {
  results.push({ lane, status, ok, detail });
  console.log(`[${ok ? "PASS" : "FAIL"}] ${lane.padEnd(24)} status ${status}${detail ? `  ${detail}` : ""}`);
}

async function post(path: string, headers: Record<string, string>, body: unknown): Promise<{ status: number; json: unknown }> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  let json: unknown = null;
  try {
    json = await res.json();
  } catch {
    json = null;
  }
  return { status: res.status, json };
}

const FREE_TEXT = { task_description: "Probe: which model should rename a variable across a small repo?" };

async function main(): Promise<void> {
  const probeStart = new Date().toISOString();
  const probeEmail = `roadmodel-lane-probe-${randomBytes(6).toString("hex")}@example.com`;
  let probeUserId: string | null = null;

  try {
    const created = await admin.auth.admin.createUser({ email: probeEmail, email_confirm: true });
    probeUserId = created.data.user?.id ?? null;
    if (created.error || !probeUserId) throw new ProbeError("probe user not created");
    const probeCookie = await sessionCookieFor(probeEmail);
    const founderCookie = await sessionCookieFor(FOUNDER_EMAIL);

    const counterBefore = await readCounter();
    const ledgerBefore = await ledgerOperatorSpend();

    // 1. Signed out, free text: no lane funds it.
    const p1 = await post("/api/recommend", { cookie: GATE }, FREE_TEXT);
    const p1Options = Array.isArray((p1.json as { options?: unknown } | null)?.options);
    record("signed-out free text", p1.status, p1.status === 402 && p1Options, "expect 402 + options");

    // 2. The uninvited account.
    const p2 = await post("/api/recommend", { cookie: `${GATE}; ${probeCookie}` }, FREE_TEXT);
    record("uninvited account", p2.status, p2.status === 402, "expect 402");

    // 3. A bogus visitor key: shaped like one, assembled at runtime, never real.
    const bogus = ["sk", "x".repeat(48)].join("-");
    const p3 = await post(
      "/api/recommend",
      { cookie: GATE, "X-Roadmodel-Visitor-Key": bogus, "X-Roadmodel-Visitor-Provider": "openai" },
      FREE_TEXT,
    );
    const p3Error = (p3.json as { error?: unknown } | null)?.error;
    record("bogus visitor key", p3.status, p3.status === 401 && p3Error === "visitor_key_rejected", "expect 401 visitor_key_rejected");

    // 4. An anonymous Quick pick.
    const p4 = await post(
      "/api/recommend/keyless",
      { cookie: GATE },
      { category: "coding", complexity: "medium", novel: false, budget_priority: "balanced" },
    );
    const rungs = (p4.json as { rungs?: unknown[] } | null)?.rungs;
    record("keyless Quick pick", p4.status, p4.status === 200 && Array.isArray(rungs) && rungs.length === 3, "expect 200 + 3 rungs");

    // Probes 1-4 must not have moved the operator's counter.
    const counterMid = await readCounter();
    const unchanged = counterMid === counterBefore;
    record("counter after lanes 1-4", 0, unchanged, unchanged ? "unchanged" : "MOVED");

    // 5. The founder, no bypass header: the one call the operator pays for.
    const p5 = await post("/api/recommend", { cookie: `${GATE}; ${founderCookie}` }, FREE_TEXT);
    record("founder", p5.status, p5.status === 200, "expect 200");

    // The audit write and the counter increment both run after the response.
    let operatorRows: LedgerRow[] = [];
    let counterAfter: number | null = counterMid;
    const deadline = Date.now() + SETTLE_MS;
    while (Date.now() < deadline) {
      operatorRows = (await ledger(probeStart)).filter((r) => r.funded_by === "operator");
      counterAfter = await readCounter();
      if (operatorRows.length >= 1 && (counterAfter ?? 0) !== (counterMid ?? 0)) break;
      await new Promise((r) => setTimeout(r, 1_500));
    }
    // One more beat, so a second (wrong) row would have landed too.
    await new Promise((r) => setTimeout(r, 2_000));
    operatorRows = (await ledger(probeStart)).filter((r) => r.funded_by === "operator");
    counterAfter = await readCounter();

    record("operator rows", operatorRows.length, operatorRows.length === 1, "expect exactly 1 (the founder's)");
    const probeRows = operatorRows.filter((r) => r.user_id === probeUserId).length;
    record("operator rows, probe user", probeRows, probeRows === 0, "expect 0");

    const rowCost = Number(operatorRows[0]?.cost_usd) || 0;
    // A counter that was missing before is seeded from the ledger on the
    // founder's first guard check; compare against what the ledger held then.
    const base = counterBefore ?? ledgerBefore;
    const delta = (counterAfter ?? 0) - base;
    const matches = rowCost > 0 && Math.abs(delta - rowCost) <= COST_TOLERANCE;
    record("counter delta = row cost", 0, matches, `delta ${delta.toFixed(6)} vs cost ${rowCost.toFixed(6)}`);
  } finally {
    if (probeUserId) await admin.auth.admin.deleteUser(probeUserId).catch(() => undefined);
  }

  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} lane assertions held`);
  process.exit(failed === 0 ? 0 : 1);
}

main().catch((e: unknown) => {
  console.error(`probe aborted: ${e instanceof ProbeError ? e.message : e instanceof Error ? e.name : "unknown"}`);
  process.exit(1);
});
