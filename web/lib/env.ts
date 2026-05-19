// web/lib/env.ts
import { z } from "zod";

const ENV_README =
  'infra/README.md "Environment variables"';

const envSchema = z.object({
  NEXT_PUBLIC_SITE_URL: z
    .string()
    .min(1)
    .default("https://staging.roadmodel.ai"),
  ROADMODEL_SERVICE_URL: z.string().min(1),
  ROADMODEL_INTERNAL_TOKEN: z.string().min(1),
  SUPABASE_URL: z.string().min(1),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1),
  UPSTASH_REDIS_URL: z.string().min(1),
  UPSTASH_REDIS_TOKEN: z.string().min(1),
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
  ROADMODEL_SERVICE_URL: requireVar("ROADMODEL_SERVICE_URL"),
  ROADMODEL_INTERNAL_TOKEN: requireVar("ROADMODEL_INTERNAL_TOKEN"),
  SUPABASE_URL: requireVar("SUPABASE_URL"),
  SUPABASE_SERVICE_ROLE_KEY: requireVar("SUPABASE_SERVICE_ROLE_KEY"),
  UPSTASH_REDIS_URL: requireVar("UPSTASH_REDIS_URL"),
  UPSTASH_REDIS_TOKEN: requireVar("UPSTASH_REDIS_TOKEN"),
});
