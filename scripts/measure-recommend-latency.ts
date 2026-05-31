// scripts/measure-recommend-latency.ts
//
// Phase 4 Step 7 — maintainer-run latency sweep against production
// /api/recommend. Issues N requests over a configurable window,
// reads back the per-request audit_log.latency_ms breakdown via a
// Supabase service-role query, and prints P50 / P95 / P99 for
// every span plus a markdown table copy-pastable into
// docs/phase04-latency-findings.md.
//
// Usage (the wrapper fetches required secrets from the macOS login
// keychain — see scripts/with-prod-secrets.sh for the one-time seed
// commands; web/node_modules supplies @supabase/supabase-js and tsx
// since there is no root package.json):
//
//   cd web
//   ../scripts/with-prod-secrets.sh node node_modules/.bin/tsx \
//       ../scripts/measure-recommend-latency.ts                \
//       --target https://roadmodel.ai                          \
//       --requests 50 --window-seconds 600
//
// Required env vars (the wrapper exports them all; this script
// reads four): ROADMODEL_LATENCY_BYPASS_TOKEN, SITE_PASSWORD,
// SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
//
// Exits non-zero on the first failed request so upstream errors
// surface immediately rather than getting buried in the markdown
// table.

import { createClient } from "@supabase/supabase-js";
import { createHash } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";

// Pre-baked prompt mix — three representative task descriptions
// chosen to span Phase 3's coverage: a creative-writing ask, a
// coding ask, and a planning ask. The mix is deterministic
// (round-robin) so sweep reruns are comparable.
const PROMPT_MIX: readonly string[] = [
  "Write a short story about a robot learning to garden.",
  "Help me build a small Python CLI that fetches weather data and caches it.",
  "Draft a one-week study plan for someone preparing for a graduate-level " +
    "linear algebra exam.",
];

interface Args {
  target: string;
  requests: number;
  windowSeconds: number;
}

function parseArgs(): Args {
  const args = process.argv.slice(2);
  const out: Args = {
    target: process.env.ROADMODEL_LATENCY_TARGET ?? "https://roadmodel.ai",
    requests: 50,
    windowSeconds: 600,
  };
  for (let i = 0; i < args.length; i += 1) {
    const flag = args[i];
    const next = args[i + 1];
    if (flag === "--target" && next) {
      out.target = next;
      i += 1;
    } else if (flag === "--requests" && next) {
      out.requests = Number.parseInt(next, 10);
      i += 1;
    } else if (flag === "--window-seconds" && next) {
      out.windowSeconds = Number.parseInt(next, 10);
      i += 1;
    } else {
      console.error(`unknown flag: ${flag}`);
      process.exit(64);
    }
  }
  if (!Number.isFinite(out.requests) || out.requests <= 0) {
    console.error("--requests must be a positive integer");
    process.exit(64);
  }
  if (!Number.isFinite(out.windowSeconds) || out.windowSeconds <= 0) {
    console.error("--window-seconds must be a positive integer");
    process.exit(64);
  }
  return out;
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    console.error(`missing required env var: ${name}`);
    process.exit(64);
  }
  return value;
}

// Mirror of web/lib/gate.ts deriveGateToken — the gate cookie is
// sha256("roadmodel-gate-v1:" + password), set on /api/gate's
// successful POST. We derive it locally so the script can attach
// the cookie on the first /api/recommend call without going
// through the /api/gate redirect dance.
function deriveGateToken(password: string): string {
  return createHash("sha256")
    .update(`roadmodel-gate-v1:${password}`)
    .digest("hex");
}

interface RequestRecord {
  prompt: string;
  startedAt: number;
  wallClockMs: number;
  status: number;
  ok: boolean;
  responseTimingHeader: string | null;
}

async function runSweep(args: Args): Promise<RequestRecord[]> {
  const bypassToken = requireEnv("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const sitePassword = process.env.SITE_PASSWORD;
  const gateCookie = sitePassword
    ? `roadmodel_gate=${deriveGateToken(sitePassword)}`
    : undefined;

  const records: RequestRecord[] = [];
  const intervalMs = (args.windowSeconds * 1000) / args.requests;
  const baseStart = Date.now();

  for (let i = 0; i < args.requests; i += 1) {
    const prompt = PROMPT_MIX[i % PROMPT_MIX.length];
    const expectedStart = baseStart + i * intervalMs;
    const wait = expectedStart - Date.now();
    if (wait > 0) {
      await sleep(wait);
    }

    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-roadmodel-bypass": bypassToken,
      "user-agent": "roadmodel-latency-sweep/1.0",
    };
    if (gateCookie) {
      headers.cookie = gateCookie;
    }

    const startedAt = Date.now();
    const wall = performance.now();
    const url = new URL("/api/recommend", args.target).toString();
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ task_description: prompt }),
    });
    const wallClockMs = performance.now() - wall;

    const responseTimingHeader = response.headers.get("X-Roadmodel-Timing");
    const ok = response.ok;
    if (!ok) {
      const body = await response.text();
      console.error(
        `request ${i + 1}/${args.requests} failed (status=${response.status})`,
      );
      console.error(body.slice(0, 1000));
      process.exit(1);
    }
    // Drain the body so the connection can be reused / closed
    // cleanly even though the script ignores the payload itself.
    await response.text();
    records.push({
      prompt,
      startedAt,
      wallClockMs,
      status: response.status,
      ok,
      responseTimingHeader,
    });
    process.stdout.write(
      `[${i + 1}/${args.requests}] ${response.status} ${Math.round(
        wallClockMs,
      )}ms\n`,
    );
  }
  return records;
}

interface AuditLatencyRow {
  total_ms?: number;
  dispatch_ms?: number;
  scoring_ms?: number;
  provider_ms?: number;
  service_scoring_ms?: number;
  service_provider_ms?: number;
  render_ms?: number;
  cold_start_ms?: number;
}

async function fetchAuditRows(
  supabaseUrl: string,
  serviceRoleKey: string,
  sweepStart: number,
): Promise<AuditLatencyRow[]> {
  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false },
  });
  const { data, error } = await supabase
    .from("audit_log")
    .select("latency_ms")
    .eq("route", "/api/recommend")
    .eq("outcome", "ok")
    .gte("ts", new Date(sweepStart).toISOString())
    .order("ts", { ascending: true });
  if (error) {
    console.error("supabase audit_log query failed", error);
    process.exit(1);
  }
  return (data ?? [])
    .map((row) => row.latency_ms as AuditLatencyRow | null)
    .filter((row): row is AuditLatencyRow => row !== null);
}

function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(
    sorted.length - 1,
    Math.floor((p / 100) * sorted.length),
  );
  return sorted[idx];
}

type SpanKey = keyof AuditLatencyRow;
const SPANS: readonly SpanKey[] = [
  "total_ms",
  "dispatch_ms",
  "scoring_ms",
  "provider_ms",
  "service_scoring_ms",
  "service_provider_ms",
  "render_ms",
  "cold_start_ms",
] as const;

function printMarkdown(
  rows: AuditLatencyRow[],
  records: RequestRecord[],
): void {
  console.log("");
  console.log(`### Sweep summary`);
  console.log("");
  console.log(`- Requests issued: ${records.length}`);
  console.log(`- Audit rows fetched: ${rows.length}`);
  console.log("");
  console.log("| Span | P50 (ms) | P95 (ms) | P99 (ms) | n |");
  console.log("| --- | --- | --- | --- | --- |");
  for (const span of SPANS) {
    const values = rows
      .map((row) => row[span])
      .filter((v): v is number => typeof v === "number");
    const p50 = percentile(values, 50);
    const p95 = percentile(values, 95);
    const p99 = percentile(values, 99);
    console.log(
      `| ${span} | ${p50 ?? "—"} | ${p95 ?? "—"} | ${p99 ?? "—"} | ${
        values.length
      } |`,
    );
  }
  console.log("");
  const wallValues = records.map((r) => r.wallClockMs);
  console.log(
    `Client-side wall clock — P50 ${Math.round(percentile(wallValues, 50) ?? 0)}ms, ` +
      `P95 ${Math.round(percentile(wallValues, 95) ?? 0)}ms, ` +
      `P99 ${Math.round(percentile(wallValues, 99) ?? 0)}ms`,
  );
}

async function main(): Promise<void> {
  const args = parseArgs();
  const supabaseUrl = requireEnv("SUPABASE_URL");
  const serviceRoleKey = requireEnv("SUPABASE_SERVICE_ROLE_KEY");

  console.log(
    `# Roadmodel latency sweep — target=${args.target} requests=${args.requests} ` +
      `window=${args.windowSeconds}s`,
  );
  const sweepStart = Date.now();
  const records = await runSweep(args);

  // Audit writes are background-fired (writeAudit is `void`-ed in
  // the route handler), so give the queue a moment to flush
  // before we query for the rows. 10s is generous; in practice
  // the inserts hit Supabase within a few hundred ms each.
  console.log("");
  console.log("Waiting 10s for audit_log inserts to settle…");
  await sleep(10_000);

  const rows = await fetchAuditRows(supabaseUrl, serviceRoleKey, sweepStart);
  printMarkdown(rows, records);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
