// web/lib/gemini-client.ts
//
// Single point of contact between the Next.js tier and the
// @google/genai SDK. The Phase 3 recommender path stays on the
// FastAPI service (roadmodel-api Vercel project), so this wrapper
// is currently consumed only by web/lib/roadmap-engine.ts (Phase 4
// Step 4) and any future Vercel-Functions-side Gemini call.
//
// Sane defaults are documented on each constant so callers can
// override per-call without reading the SDK reference. The wrapper
// is intentionally thin — the engine layer owns prompt assembly and
// SSE shaping; this layer owns SDK instantiation, timeouts, and the
// retry policy.

import { GoogleGenAI } from "@google/genai";

import { env } from "./env";

// Per-request hard timeout. Vercel Functions default execution
// budget is 300s; pinning the upstream Gemini stream to 120s keeps
// a buffer for SSE flushing and the audit-write tail.
export const GEMINI_REQUEST_TIMEOUT_MS = 120_000;

// Generous ceiling for a single roadmap turn. The combined
// templates + history can reach ~10k input tokens; a roadmap draft
// rarely exceeds ~6k output tokens. 8192 leaves room for verbose
// drafts without inviting unbounded generation.
export const GEMINI_MAX_OUTPUT_TOKENS = 8192;

// Retry policy — gentle. Gemini 2.5 Flash and 3 Flash both expose
// transient 503 / DEADLINE_EXCEEDED on stream open; one immediate
// retry recovers in most cases without doubling user-visible
// latency. Subsequent failures surface as a friendly error from
// the route handler.
export const GEMINI_RETRY_MAX_ATTEMPTS = 2;
export const GEMINI_RETRY_INITIAL_DELAY_MS = 500;

let cachedClient: GoogleGenAI | null = null;

export function getGeminiClient(): GoogleGenAI {
  if (cachedClient === null) {
    cachedClient = new GoogleGenAI({ apiKey: env.GOOGLE_API_KEY });
  }
  return cachedClient;
}

export function isRetryableGeminiError(err: unknown): boolean {
  if (!(err instanceof Error)) {
    return false;
  }
  const message = err.message.toLowerCase();
  return (
    message.includes("503") ||
    message.includes("unavailable") ||
    message.includes("deadline_exceeded") ||
    message.includes("etimedout") ||
    message.includes("econnreset")
  );
}

export async function withGeminiRetry<T>(
  fn: () => Promise<T>,
  maxAttempts: number = GEMINI_RETRY_MAX_ATTEMPTS,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (
        attempt === maxAttempts - 1 ||
        !isRetryableGeminiError(err)
      ) {
        throw err;
      }
      await new Promise((resolve) =>
        setTimeout(resolve, GEMINI_RETRY_INITIAL_DELAY_MS * (attempt + 1)),
      );
    }
  }
  throw lastError;
}

// Test seam: tests inject a stub via setTestGeminiClient(); production
// code paths never touch this. Resetting to null restores the lazy
// default.
let testClientOverride: GoogleGenAI | null = null;

export function setTestGeminiClient(client: GoogleGenAI | null): void {
  testClientOverride = client;
}

export function resolveGeminiClient(): GoogleGenAI {
  return testClientOverride ?? getGeminiClient();
}
