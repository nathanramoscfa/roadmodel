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
  // Optional until the maintainer seeds them on roadmodel-web Vercel
  // env vars (preview + staging + production). When unset, the
  // Step 6 rate limiter fails open with a startup warning — see
  // web/lib/ratelimit.ts. Flip to .min(1) in the follow-up PR that
  // lands the seeded values; same for ROADMODEL_IP_SALT.
  UPSTASH_REDIS_URL: z.string().optional(),
  UPSTASH_REDIS_TOKEN: z.string().optional(),
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
  UPSTASH_REDIS_URL: process.env.UPSTASH_REDIS_URL,
  UPSTASH_REDIS_TOKEN: process.env.UPSTASH_REDIS_TOKEN,
});
