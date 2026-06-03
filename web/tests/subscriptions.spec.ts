// web/tests/subscriptions.spec.ts
//
// Issue #152 — the subscription picker options are derived from
// catalog.json's subscription_tiers (not a hardcoded 3-item list). These
// pure tests pin the derivation: legacy ids preserved, labels cleaned,
// every tier present, grouped providers.

import { test, expect } from "@playwright/test";

import {
  SUBSCRIPTION_IDS,
  fundedSurfacesForSubscription,
  getSubscriptionOptions,
} from "../lib/subscriptions";

test("derives every catalog subscription tier", () => {
  const opts = getSubscriptionOptions();
  // 14 tiers in the current catalog across 4 providers.
  expect(opts.length).toBeGreaterThanOrEqual(12);
  const providers = new Set(opts.map((o) => o.provider));
  expect(providers).toEqual(
    new Set(["Anthropic", "OpenAI", "Google", "Cursor"]),
  );
});

test("preserves the legacy ids for the original three tiers", () => {
  const byId = new Map(getSubscriptionOptions().map((o) => [o.id, o]));
  expect(byId.get("claude-max")?.label).toBe("Claude Max ($200)");
  expect(byId.get("claude-max")?.provider).toBe("Anthropic");
  expect(byId.get("cursor-ultra")?.label).toBe("Cursor Ultra");
  expect(byId.get("chatgpt-pro")?.label).toBe("ChatGPT Pro ($200)");
});

test("cleans 'claude.ai Max' labels to 'Claude Max' and slugs the rest", () => {
  const opts = getSubscriptionOptions();
  // No label leaks the catalog's "claude.ai" wording.
  expect(opts.some((o) => /claude\.ai/i.test(o.label))).toBe(false);
  // A non-legacy tier gets a derived, provider-namespaced slug.
  const max100 = opts.find((o) => o.label === "Claude Max ($100)");
  expect(max100?.id).toBe("anthropic-claude-max-100");
});

test("SUBSCRIPTION_IDS matches the derived options and funds map to surfaces", () => {
  const opts = getSubscriptionOptions();
  expect(SUBSCRIPTION_IDS.size).toBe(opts.length);
  expect(SUBSCRIPTION_IDS.has("claude-max")).toBe(true);
  // Legacy Anthropic Max funds the Claude surfaces (basis for #163).
  expect(fundedSurfacesForSubscription("claude-max")).toContain("claude-code");
  expect(fundedSurfacesForSubscription("nonexistent-id")).toEqual([]);
});
