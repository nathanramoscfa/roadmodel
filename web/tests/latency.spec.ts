// web/tests/latency.spec.ts
//
// Phase 4 Step 7 — span-recording correctness coverage. Four
// scenarios:
//
//   1. A synthetic /api/recommend recording session against a
//      mocked upstream fetch produces all four spans
//      (dispatch_ms, scoring_ms, provider_ms, render_ms) with
//      non-negative ms values summing within 10% of total_ms.
//   2. The captured audit row carries latency_ms with the same
//      shape (matches the JSONB column comment in
//      infra/migrations/0005b_audit_log_latency.sql).
//   3. Cold-start detection — the first call after module
//      load reports cold_start_ms > 0; the second call reports
//      cold_start_ms === 0.
//   4. ingestServiceTimings parses the X-Roadmodel-Timing
//      header (well-formed key=value;key=value populates both
//      service_scoring_ms and service_provider_ms; a missing
//      header leaves both undefined).
//
// Tests 1 and 2 use a harness rather than a real HTTP call
// because the route handler's span recording happens inside
// the same process; an HTTP roundtrip via Playwright's
// webServer would put the audit sink in a different process
// from the server. The harness mirrors the production
// handler's exact span ordering so the contract still
// reflects the live shape.

import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import { _setAuditSinkForTest, writeAudit, type AuditEntry } from "../lib/audit";
import {
  _resetColdStartForTest,
  getTimings,
  ingestServiceTimings,
  recordTotal,
  runWithTimings,
  withSpan,
  type LatencyTimings,
} from "../lib/latency";

// Lightweight async sleep that resolves at least `ms` ms later,
// using setTimeout to ensure performance.now() advances. Used
// inside withSpan wrappers so the recorded duration is nonzero.
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Mirror of the production handler's span ordering. Exists in
// the test file to keep the harness explicit; if the production
// handler's order changes, this harness should be updated to
// match.
async function runSyntheticHandler(opts: {
  upstreamTimingHeader: string | null;
  upstreamDelayMs: number;
}): Promise<LatencyTimings> {
  let captured: AuditEntry | null = null;
  const prior = _setAuditSinkForTest((entry) => {
    captured = entry;
  });
  try {
    await runWithTimings(async () => {
      await withSpan("dispatch", async () => {
        await sleep(2);
      });
      await withSpan("provider", async () => {
        await sleep(opts.upstreamDelayMs);
      });
      ingestServiceTimings(opts.upstreamTimingHeader);
      await withSpan("render", async () => {
        await sleep(2);
      });
      await withSpan("scoring", async () => {
        // The production handler keeps this empty too — see
        // web/app/api/recommend/route.ts.
      });
      recordTotal();
      await writeAudit({
        ip_hash: "h1",
        ua_hash: "h2",
        route: "/api/recommend",
        outcome: "ok",
        latency_ms: getTimings(),
      });
    });
  } finally {
    _setAuditSinkForTest(prior);
  }
  if (!captured) {
    throw new Error("audit sink never received a row");
  }
  const auditRow = captured as AuditEntry;
  if (!auditRow.latency_ms) {
    throw new Error("audit row missing latency_ms");
  }
  return auditRow.latency_ms;
}

test("synthetic recommend records all four spans summing within 10% of total_ms", async () => {
  _resetColdStartForTest();
  const timings = await runSyntheticHandler({
    upstreamTimingHeader: "service_scoring_ms=3;service_provider_ms=8",
    upstreamDelayMs: 15,
  });

  for (const key of [
    "dispatch_ms",
    "scoring_ms",
    "provider_ms",
    "render_ms",
    "total_ms",
  ] as const) {
    expect(timings[key], `${key} should be recorded`).toBeDefined();
    expect(timings[key]!).toBeGreaterThanOrEqual(0);
  }

  const sumOfSpans =
    timings.dispatch_ms! +
    timings.scoring_ms! +
    timings.provider_ms! +
    timings.render_ms!;
  const total = timings.total_ms!;
  // Spans are wrapped sequentially in the harness, so their sum
  // should approximate total_ms. Allow a 10% tolerance to absorb
  // the tiny gaps between sequential withSpan boundaries (the
  // recorder uses performance.now() reads at span start and end,
  // and the test's setTimeout-driven sleeps are not millisecond-
  // exact).
  const drift = Math.abs(total - sumOfSpans);
  const tolerance = Math.max(1, Math.ceil(total * 0.1));
  expect(drift, `spans (${sumOfSpans}ms) should sum within 10% of total (${total}ms)`)
    .toBeLessThanOrEqual(tolerance);
});

test("audit row carries latency_ms JSONB with the documented shape", async () => {
  _resetColdStartForTest();
  const timings = await runSyntheticHandler({
    upstreamTimingHeader: "service_scoring_ms=4;service_provider_ms=10",
    upstreamDelayMs: 12,
  });

  // The migration's column comment documents an eight-key bag.
  // Every key that's present must be a finite non-negative
  // integer. Missing keys are allowed (Phase 4 leaves
  // service_* undefined when the upstream omits the header,
  // and Phase 9 dashboards add more keys forward-compat).
  const allowedKeys: ReadonlySet<keyof LatencyTimings> = new Set([
    "total_ms",
    "dispatch_ms",
    "scoring_ms",
    "provider_ms",
    "service_scoring_ms",
    "service_provider_ms",
    "render_ms",
    "cold_start_ms",
  ]);
  for (const key of Object.keys(timings)) {
    expect(allowedKeys.has(key as keyof LatencyTimings), `${key} is a documented latency_ms key`)
      .toBeTruthy();
    const value = timings[key as keyof LatencyTimings];
    expect(typeof value).toBe("number");
    expect(Number.isFinite(value as number)).toBeTruthy();
    expect((value as number) >= 0).toBeTruthy();
  }

  expect(timings.service_scoring_ms).toBe(4);
  expect(timings.service_provider_ms).toBe(10);
});

test("cold-start detection — first call > 0, subsequent === 0", async () => {
  _resetColdStartForTest();
  let firstColdStart: number | undefined;
  await runWithTimings(async () => {
    await withSpan("dispatch", async () => {
      await sleep(1);
    });
    firstColdStart = getTimings().cold_start_ms;
  });
  expect(firstColdStart).toBeDefined();
  expect(firstColdStart!).toBeGreaterThan(0);

  let secondColdStart: number | undefined;
  await runWithTimings(async () => {
    await withSpan("dispatch", async () => {
      await sleep(1);
    });
    secondColdStart = getTimings().cold_start_ms;
  });
  expect(secondColdStart).toBe(0);
});

test("ingestServiceTimings parses X-Roadmodel-Timing header", async () => {
  _resetColdStartForTest();
  let wellFormed: LatencyTimings | null = null;
  await runWithTimings(async () => {
    ingestServiceTimings("service_scoring_ms=42;service_provider_ms=123");
    wellFormed = getTimings();
  });
  expect(wellFormed).not.toBeNull();
  expect(wellFormed!.service_scoring_ms).toBe(42);
  expect(wellFormed!.service_provider_ms).toBe(123);

  let missing: LatencyTimings | null = null;
  await runWithTimings(async () => {
    ingestServiceTimings(null);
    missing = getTimings();
  });
  expect(missing).not.toBeNull();
  expect(missing!.service_scoring_ms).toBeUndefined();
  expect(missing!.service_provider_ms).toBeUndefined();

  let malformed: LatencyTimings | null = null;
  await runWithTimings(async () => {
    ingestServiceTimings("service_scoring_ms=abc;garbage;service_provider_ms=-5");
    malformed = getTimings();
  });
  expect(malformed).not.toBeNull();
  expect(malformed!.service_scoring_ms).toBeUndefined();
  expect(malformed!.service_provider_ms).toBeUndefined();
});
