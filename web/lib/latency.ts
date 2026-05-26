// web/lib/latency.ts
//
// Phase 4 Step 7 warm-path latency profiling. Three concerns,
// one module:
//
//   1. Per-request span recording. withSpan(name, fn) wraps an
//      async callable and accumulates its wall-clock duration
//      into a request-local timings map. The map is kept on an
//      AsyncLocalStorage instance so the route handler doesn't
//      have to thread a context object through every helper.
//
//   2. Upstream timing ingestion. ingestServiceTimings(header)
//      parses the FastAPI tier's X-Roadmodel-Timing response
//      header (key=value;key=value form) and merges the
//      decomposed service_scoring_ms + service_provider_ms
//      keys into the current request's timings map, so the
//      audit row's provider_ms isn't an opaque upstream blob.
//
//   3. Cold-start detection. A module-evaluation timestamp is
//      captured once per cold start. The first call after that
//      records cold_start_ms = (request_start - module_load_ts);
//      every subsequent call records 0. Phase 4 Step 7 keep-alive
//      decision (PR 7b/7d) keys on this signal directly.
//
// The Phase 9 observability work inherits all three concerns
// without retrofit — the audit_log.latency_ms jsonb column
// (migration 0005b) is the persisted contract.

import { AsyncLocalStorage } from "node:async_hooks";

// Mutable per-request timings bag. All fields are integer ms;
// every field is OPTIONAL so the audit-log writer's jsonb shape
// stays uniform regardless of which spans actually fired in a
// given request. Matches the column comment in
// infra/migrations/0005b_audit_log_latency.sql.
export interface LatencyTimings {
  total_ms?: number;
  dispatch_ms?: number;
  scoring_ms?: number;
  provider_ms?: number;
  service_scoring_ms?: number;
  service_provider_ms?: number;
  render_ms?: number;
  cold_start_ms?: number;
}

// Span names the recorder accepts. Constraining the union here
// (rather than typing the argument as plain `string`) keeps the
// audit-log jsonb shape stable: a typo in withSpan("disptach", ...)
// becomes a TS compile error instead of a silent schema drift.
export type SpanName =
  | "dispatch"
  | "scoring"
  | "provider"
  | "render";

interface InternalSpanRecord {
  start: number;
  end: number;
  duration: number;
}

interface RequestState {
  spans: Map<SpanName, InternalSpanRecord>;
  // Earliest span start across the request — used by recordTotal
  // to compute total_ms without depending on the recorder having
  // been wrapped at the exact handler entry point.
  earliestStart: number | null;
  // Latest span end across the request — same purpose.
  latestEnd: number | null;
  // Extra timings ingested from external sources (the FastAPI
  // service's X-Roadmodel-Timing header). Kept separate from
  // `spans` because they don't have a withSpan-style wrapper —
  // they arrive as already-computed ms values from the upstream.
  extras: Partial<LatencyTimings>;
  // Cold-start ms for THIS request, captured at runWithTimings
  // entry. 0 on warm calls; > 0 on the first call after the
  // module loaded.
  coldStartMs: number;
}

const als = new AsyncLocalStorage<RequestState>();

// Module-evaluation timestamp. Captured exactly once per cold
// start (per Node.js worker on Fluid Compute). The first
// request after the module loads sees the gap; subsequent
// requests inside the same instance see 0 because the gap is
// "used up" by the first invocation of runWithTimings.
const MODULE_LOAD_TS = performance.now();
let coldStartConsumed = false;

function nowMs(): number {
  return performance.now();
}

// Run `fn` inside a fresh request-scoped timings context. The
// handler in web/app/api/recommend/route.ts wraps its body in
// this so withSpan / getTimings / recordTotal / ingestServiceTimings
// can all find the active state via AsyncLocalStorage.
export function runWithTimings<T>(fn: () => Promise<T>): Promise<T> {
  const state: RequestState = {
    spans: new Map(),
    earliestStart: null,
    latestEnd: null,
    extras: {},
    coldStartMs: coldStartConsumed ? 0 : Math.round(nowMs() - MODULE_LOAD_TS),
  };
  coldStartConsumed = true;
  return als.run(state, fn);
}

function currentState(): RequestState | undefined {
  return als.getStore();
}

// Wrap an async callable and record its wall-clock duration
// under the given span name. If no runWithTimings context is
// active (test harness forgot to wrap, or a recorder call
// fired outside the route handler), the wrapper still executes
// fn and returns the result; it just doesn't record. This
// keeps the recorder safe to call from helper modules that
// might also be invoked from non-request contexts.
export async function withSpan<T>(
  name: SpanName,
  fn: () => Promise<T>,
): Promise<T> {
  const state = currentState();
  const start = nowMs();
  try {
    return await fn();
  } finally {
    const end = nowMs();
    if (state) {
      const duration = Math.max(0, end - start);
      const existing = state.spans.get(name);
      if (existing) {
        // If a span name fires twice in the same request (e.g.
        // retry path), accumulate. Phase 4 routes don't currently
        // do this, but Phase 9 dashboards interpret an accumulated
        // span as the same span — not two — so don't overwrite.
        state.spans.set(name, {
          start: existing.start,
          end,
          duration: existing.duration + duration,
        });
      } else {
        state.spans.set(name, { start, end, duration });
      }
      if (state.earliestStart === null || start < state.earliestStart) {
        state.earliestStart = start;
      }
      if (state.latestEnd === null || end > state.latestEnd) {
        state.latestEnd = end;
      }
    }
  }
}

// Parse the FastAPI service's timing header into the current
// request's timings map. Expected form:
//   "service_scoring_ms=12;service_provider_ms=4321"
// Unknown keys are ignored (forward-compat with future Phase 9
// dashboards that might add more service-side decomposition).
// Missing header or unparseable values are a no-op.
export function ingestServiceTimings(header: string | null): void {
  const state = currentState();
  if (!state || !header) {
    return;
  }
  for (const pair of header.split(";")) {
    const trimmed = pair.trim();
    if (!trimmed) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = Number.parseInt(trimmed.slice(eq + 1).trim(), 10);
    if (!Number.isFinite(value) || value < 0) continue;
    if (
      key === "service_scoring_ms" ||
      key === "service_provider_ms"
    ) {
      state.extras[key] = value;
    }
  }
}

// Materialize the current request's timings into the jsonb
// shape expected by audit_log.latency_ms. Call after every
// withSpan has settled; no-op outside a runWithTimings context.
export function getTimings(): LatencyTimings {
  const state = currentState();
  if (!state) {
    return {};
  }
  const out: LatencyTimings = {
    cold_start_ms: state.coldStartMs,
    ...state.extras,
  };
  for (const [name, record] of state.spans) {
    const key = (`${name}_ms`) as keyof LatencyTimings;
    out[key] = Math.round(record.duration);
  }
  if (state.earliestStart !== null && state.latestEnd !== null) {
    out.total_ms = Math.round(state.latestEnd - state.earliestStart);
  }
  return out;
}

// Finalize the request by computing total_ms across all recorded
// spans. Call once at the end of the handler, before reading
// getTimings() for the audit row. Idempotent — re-calling just
// recomputes the same value.
export function recordTotal(): void {
  const state = currentState();
  if (!state) return;
  if (state.earliestStart === null || state.latestEnd === null) {
    return;
  }
  // No-op: total_ms is derived from earliestStart/latestEnd at
  // getTimings() read time. This function exists as part of the
  // documented public surface so callers signal intent
  // ("I'm done recording spans for this request") and the
  // ordering contract is explicit.
}

// Exposed for tests that need to reset the cold-start latch
// between specs. Production never calls this. The MODULE_LOAD_TS
// is intentionally NOT reset — Node.js cannot rewind
// performance.now(), and the production semantic is "first
// request after module evaluation has cold_start_ms > 0".
export function _resetColdStartForTest(): void {
  coldStartConsumed = false;
}
