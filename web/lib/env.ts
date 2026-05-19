// web/lib/env.ts
import { z } from "zod";

const ENV_README =
  'infra/README.md "Environment variables"';

const envSchema = z.object({
  NEXT_PUBLIC_SITE_URL: z
    .string()
    .min(1)
    .default("https://staging.roadmodel.ai"),
  // Railway service vars stay optional until Phase 3 Step 7 provisions the
  // production Railway service and cuts the apex DNS. recommendOnServer()
  // throws at request time if either is missing, which the /api/recommend
  // route maps to HTTP 502.
  ROADMODEL_SERVICE_URL: z.string().optional(),
  ROADMODEL_INTERNAL_TOKEN: z.string().optional(),
  SUPABASE_URL: z.string().min(1),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
  // Upstash vars stay optional until Phase 3 Step 6 provisions Upstash and
  // ships the rate limiter; Step 6 must flip these to .min(1) when it lands.
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
  ROADMODEL_SERVICE_URL: process.env.ROADMODEL_SERVICE_URL,
  ROADMODEL_INTERNAL_TOKEN: process.env.ROADMODEL_INTERNAL_TOKEN,
  SUPABASE_URL: requireVar("SUPABASE_URL"),
  SUPABASE_SERVICE_ROLE_KEY: requireVar("SUPABASE_SERVICE_ROLE_KEY"),
  UPSTASH_REDIS_URL: process.env.UPSTASH_REDIS_URL,
  UPSTASH_REDIS_TOKEN: process.env.UPSTASH_REDIS_TOKEN,
});
