// web/tests/fixtures/seed-test-env.ts
//
// Side-effect-only module: seeds the Node-side env vars that
// web/lib/env.ts validates at module-evaluation time. Tests that
// statically import any module that transitively pulls in
// web/lib/env.ts (e.g. profile, auth, roadmap-prompts,
// roadmap-engine) must import THIS module first so the env block
// is populated before the Zod parse fires.
//
// In Playwright workers we control the import order via the
// static import graph: this module's top-level statements run
// during the worker's module-load phase, before any subsequent
// import sees env.ts. Importing it for side effects only —
// `import "./fixtures/seed-test-env";` — does the job.

const placeholders: Record<string, string> = {
  SUPABASE_URL: "https://ci-placeholder.supabase.co",
  SUPABASE_SERVICE_ROLE_KEY: "ci-placeholder-service-role-key",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "ci-placeholder-anon-key",
  GOOGLE_API_KEY: "ci-placeholder-google-api-key",
  // A dummy founder-exempt user_id so ratelimit.spec can exercise both
  // branches of isRateLimitExempt(). Can't match any real Supabase uid; only
  // affects in-process unit tests (E2E uses the webServer env, not this seed).
  RECOMMEND_RATELIMIT_EXEMPT_USER_IDS: "rl-exempt-test-uid",
};

for (const [key, value] of Object.entries(placeholders)) {
  if (!process.env[key]) {
    process.env[key] = value;
  }
}
