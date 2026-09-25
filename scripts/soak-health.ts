// scripts/soak-health.ts
//
// Is the recommender answering at all? The soak's quality bar (B0–B9) is
// report-only: it misses on known residuals most days, so its tracking issue
// stays open and nobody reads it as an alarm. That is how every production
// recommendation failing from 2026-09-21 to 2026-09-24 went unnoticed. This is
// the separate, loud signal: when at least DOWN_SHARE of the soak's requests
// fail, the recommender is down, and .github/workflows/recommend-soak.yml
// fails its run and opens an incident issue that closes itself on recovery.

export const DOWN_SHARE = 0.5;

export interface ServiceHealth {
  down: boolean;
  failed: number;
  total: number;
  // The failing statuses, most frequent first: "500×36", "502×3, 0×1".
  // 0 is a request that never got a response (a network error).
  statuses: string;
}

export function serviceHealth(statuses: number[]): ServiceHealth {
  const failing = statuses.filter((s) => s !== 200);
  const counts = new Map<number, number>();
  for (const s of failing) counts.set(s, (counts.get(s) ?? 0) + 1);
  const breakdown = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .map(([status, n]) => `${status}×${n}`)
    .join(", ");
  return {
    down: statuses.length > 0 && failing.length >= statuses.length * DOWN_SHARE,
    failed: failing.length,
    total: statuses.length,
    statuses: breakdown,
  };
}

// The one line the workflow reads: "SERVICE_HEALTH: DOWN (36 of 36 requests
// failed; statuses 500×36)" or "SERVICE_HEALTH: UP (0 of 36 requests failed)".
export function healthLine(h: ServiceHealth): string {
  const detail = h.failed > 0 ? `; statuses ${h.statuses}` : "";
  return `SERVICE_HEALTH: ${h.down ? "DOWN" : "UP"} (${h.failed} of ${h.total} requests failed${detail})`;
}

// The soak's exit code: 3 when the recommender is down (the workflow fails
// the run), else the quality bar's own 0 (met) or 1 (missed, report-only).
export const EXIT_DOWN = 3;
