// web/tests/csp.spec.ts
//
// Regression guard for the nonce-based Content-Security-Policy set in
// web/middleware.ts. Loads pages in a real browser and asserts (a) the CSP
// header carries a per-request nonce and (b) nothing is CSP-blocked — a missing
// or mis-propagated nonce would surface as "Refused to execute…" console
// errors when the browser blocks Next's inline bootstrap/streaming scripts.

import { test, expect, type Page } from "@playwright/test";

const CSP_VIOLATION = /content security policy|refused to (execute|load|apply|connect)/i;

function collectViolations(page: Page): string[] {
  const violations: string[] = [];
  page.on("console", (m) => {
    if (CSP_VIOLATION.test(m.text())) violations.push(m.text());
  });
  page.on("pageerror", (e) => {
    if (CSP_VIOLATION.test(String(e))) violations.push(String(e));
  });
  return violations;
}

for (const path of ["/recommend", "/login"]) {
  test(`no CSP violations on ${path}`, async ({ page }) => {
    const violations = collectViolations(page);
    const resp = await page.goto(path, { waitUntil: "networkidle" });

    // Per-request nonce present in the policy.
    expect(resp?.headers()["content-security-policy"] ?? "").toContain("nonce-");
    // Page actually rendered (scripts weren't blocked into a blank page).
    await expect(page.locator("body")).not.toBeEmpty();
    expect(violations, `CSP violations on ${path}`).toEqual([]);
  });
}
