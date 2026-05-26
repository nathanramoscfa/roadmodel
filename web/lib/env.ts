// web/lib/env.ts
import { z } from "zod";

const ENV_README =
  'infra/README.md "Environment variables"';

const envSchema = z.object({
  NEXT_PUBLIC_SITE_URL: z
    .string()
    .min(1)
    .default("https://staging.roadmodel.ai"),
  SUPABASE_URL: z.string().min(1),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
  // Supabase publishable (anon) key — shipped to the browser via
  // the NEXT_PUBLIC_ prefix. .min(1) because Supabase treats an
  // empty key as anonymous and silently degrades to anon mode;
  // failing Zod validation at boot beats discovering it via a
  // broken login flow in production. Seeded in Vercel scopes
  // Production, Preview, and the staging Custom Env.
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z.string().min(1),
  // Optional until the maintainer seeds them on roadmodel-web Vercel
  // env vars (preview + staging + production). When unset, the
  // Step 6 rate limiter fails open with a startup warning — see
  // web/lib/ratelimit.ts. Flip to .min(1) in the follow-up PR that
  // lands the seeded values; same for ROADMODEL_IP_SALT.
  UPSTASH_REDIS_URL: z.string().optional(),
  UPSTASH_REDIS_TOKEN: z.string().optional(),
  // Google Generative AI key. One key, three call sites:
  //   1. Gemini 2.5 Flash on /api/recommend  (Phase 3 — via the
  //      roadmodel-api FastAPI service which carries its own copy of
  //      this key in a separate Vercel project's env scope).
  //   2. Gemini 2.5 Flash on /api/roadmap    (Phase 4 — this scope;
  //      consumed by web/lib/gemini-client.ts).
  //   3. Gemini 3 Flash on /api/roadmap      (Phase 4 FAIL escalation
  //      — same SDK call, same caching API, same key, model-string
  //      swap only).
  // Single Google provider-side billing meter for all three (see
  // docs/cost-ceilings.md). .min(1) so boot fails loudly if the key
  // is missing on any roadmodel-web scope rather than discovering
  // it via a 500 from the first roadmap turn in production.
  GOOGLE_API_KEY: z.string().min(1),
  // Phase 5 paid-frontier rollout gate. Step 6 wires this in
  // false-by-default; Phase 5 flips it on (per Vercel scope) to
  // light up the Anthropic frontier branch. Defaulted false so a
  // missing var on any scope behaves as a Phase 4 deployment.
  // Reserved — DO NOT flip true in Phase 4 (the roadmap-engine
  // wrapper throws "Phase 5 scope" on the frontier branch).
  FRONTIER_ROADMAP_ENABLED: z.coerce.boolean().default(false),
  // Phase 4 Step 7 — temporary env-gated bypass for the
  // maintainer-run latency sweep. When SET and the inbound
  // request carries an X-Roadmodel-Bypass header whose value
  // matches via constant-time comparison, withRateLimit skips
  // the Upstash check. When UNSET the header is ignored — there
  // is no fail-open default. Removed (along with the env var,
  // the withRateLimit branch, and the bypassed_rate_limit audit
  // outcome) in PR 7c after the post-fix sweep lands.
  ROADMODEL_LATENCY_BYPASS_TOKEN: z.string().optional(),
});

function requireVar(name: string): string {
  const value = process.env[name];
  if (value === undefined || value === "") {
    throw new Error(
      `Missing environment variable ${name}. See ${ENV_README}.`,
    );
  }
  return value;
}

export const env = envSchema.parse({
  NEXT_PUBLIC_SITE_URL:
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://staging.roadmodel.ai",
  SUPABASE_URL: requireVar("SUPABASE_URL"),
  SUPABASE_SERVICE_ROLE_KEY: requireVar("SUPABASE_SERVICE_ROLE_KEY"),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: requireVar("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
  UPSTASH_REDIS_URL: process.env.UPSTASH_REDIS_URL,
  UPSTASH_REDIS_TOKEN: process.env.UPSTASH_REDIS_TOKEN,
  GOOGLE_API_KEY: requireVar("GOOGLE_API_KEY"),
  FRONTIER_ROADMAP_ENABLED: process.env.FRONTIER_ROADMAP_ENABLED ?? "false",
  ROADMODEL_LATENCY_BYPASS_TOKEN: process.env.ROADMODEL_LATENCY_BYPASS_TOKEN,
});
