// web/tests/soak-health.spec.ts
//
// The soak's loud signal (scripts/soak-health.ts): when half or more of its
// requests fail, the recommender is down, the script exits 3, and the workflow
// fails its run and opens an incident issue. Pure tests, no server.

import { test, expect } from "@playwright/test";

import { DOWN_SHARE, EXIT_DOWN, healthLine, serviceHealth } from "../../scripts/soak-health";

test("every request failing is down, with the failing statuses named", () => {
  const h = serviceHealth(Array(36).fill(500));
  expect(h).toEqual({ down: true, failed: 36, total: 36, statuses: "500×36" });
  expect(healthLine(h)).toBe("SERVICE_HEALTH: DOWN (36 of 36 requests failed; statuses 500×36)");
  expect(EXIT_DOWN).toBe(3);
});

test("half failing is down; a few failures are not", () => {
  expect(DOWN_SHARE).toBe(0.5);
  const half = [...Array(18).fill(200), ...Array(17).fill(502), 0];
  const h = serviceHealth(half);
  expect(h.down).toBe(true);
  expect(h.statuses).toBe("502×17, 0×1");
  const few = serviceHealth([...Array(34).fill(200), 504, 504]);
  expect(few.down).toBe(false);
  expect(healthLine(few)).toBe("SERVICE_HEALTH: UP (2 of 36 requests failed; statuses 504×2)");
});

test("all answering is up; no requests at all is not an outage", () => {
  expect(healthLine(serviceHealth(Array(36).fill(200)))).toBe(
    "SERVICE_HEALTH: UP (0 of 36 requests failed)",
  );
  expect(serviceHealth([]).down).toBe(false);
});
