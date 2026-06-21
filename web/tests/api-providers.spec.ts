// web/tests/api-providers.spec.ts
//
// Phase 4.8 T1 (#260) — the "API access" picker options are derived from
// catalog.json's access_methods (billing per-token / subscription-or-key),
// not a hardcoded list. These pure tests pin the derivation: every API-path
// provider present, subscription-pool-only providers (Cursor) excluded,
// labels cleaned, and the validation id set matches.

import { test, expect } from "@playwright/test";

import {
  API_PROVIDER_IDS,
  getApiProviderOptions,
} from "../lib/api-providers";

test("derives every provider with an API path, excluding pool-only ones", () => {
  const ids = new Set(getApiProviderOptions().map((o) => o.id));
  // The 8 federated providers reachable via a direct API key (z.ai + Groq
  // joined in #296 — GLM and Groq-hosted gpt-oss).
  expect(ids).toEqual(
    new Set([
      "anthropic",
      "openai",
      "google",
      "deepseek",
      "mistral",
      "xai",
      "zai",
      "groq",
    ]),
  );
  // Cursor is subscription-pool only (no bring-your-own-key path) → excluded.
  expect(ids.has("cursor")).toBe(false);
});

test("labels each provider with its display name", () => {
  const byId = new Map(getApiProviderOptions().map((o) => [o.id, o.label]));
  expect(byId.get("anthropic")).toBe("Anthropic");
  expect(byId.get("openai")).toBe("OpenAI");
  expect(byId.get("deepseek")).toBe("DeepSeek");
  expect(byId.get("xai")).toBe("xAI");
  expect(byId.get("zai")).toBe("z.ai");
  expect(byId.get("groq")).toBe("Groq");
});

test("API_PROVIDER_IDS matches the derived options", () => {
  const opts = getApiProviderOptions();
  expect(API_PROVIDER_IDS.size).toBe(opts.length);
  expect(API_PROVIDER_IDS.has("deepseek")).toBe(true);
  expect(API_PROVIDER_IDS.has("cursor")).toBe(false);
});
