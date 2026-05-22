// web/lib/e2e-mode.ts
//
// Defense-in-depth gate for E2E-only code paths: the auth-bypass
// branch in web/middleware.ts, the in-memory profile store in
// web/lib/profile.ts, the /api/test/* routes, the rate-limit
// fail-open fallback, and the mock recommender swap in
// /api/recommend.
//
// Returns true only when BOTH signals agree:
//   - process.env.ROADMODEL_E2E_AUTH === "1" (explicit opt-in)
//   - process.env.VERCEL is unset (NOT running on a Vercel runtime)
//
// Vercel sets VERCEL=1 in every deployment runtime — Production,
// Preview, Development, and local `vercel dev`. Requiring its
// absence means a single misconfigured env-var scope (per the
// roadmodel memory of past Vercel CLI scope confusion) cannot
// open the bypass on its own; only Playwright + GitHub Actions
// + local `next start` runtimes can flip it on.

export function isE2eAuthEnabled(): boolean {
  if (process.env.VERCEL === "1") {
    return false;
  }
  return process.env.ROADMODEL_E2E_AUTH === "1";
}
