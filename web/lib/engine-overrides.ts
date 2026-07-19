// web/lib/engine-overrides.ts
//
// Maintainer-controlled escape hatches that sit on top of the
// catalog-derived `pickFreeEngine` resolver. Two knobs, both
// committed in source so changes ship via PR review:
//
//   1. FREE_*_MIN_TIER — the quality floor the resolver enforces
//      when filtering catalog candidates. Defaults to `'B'` on the
//      Step 4 PASS path (Gemini 2.5 Flash qualifies); flipped to
//      `'A'` on the Step 4 FAIL escalation (Gemini 3 Flash becomes
//      the cheapest Google planning-A model in the current
//      catalog).
//
//   2. ENGINE_OVERRIDES — surface-keyed pin map. Setting
//      `ENGINE_OVERRIDES.roadmap = 'gemini-3-flash'` forces the
//      free-tier /roadmap engine regardless of what the catalog
//      derivation would pick. Use cases:
//      - Quality regression on the auto-picked model — pin to a
//        known-good engine while investigating.
//      - New model not yet quality-tested — keep the catalog from
//        auto-flipping to it.
//      - Cost spike not yet propagated to the catalog — pin to a
//        previously cheaper model.
//
// The Phase 9 §9.2 catalog-refresh cron READS this file when
// computing "would-be" engine flips. A flip against a pinned
// surface gets recorded in the catalog-diff PR for review but is
// NOT applied until the override is cleared — the override is the
// authoritative-by-construction signal that the maintainer wants
// manual control over that surface.

import type { TaskTier } from "./model-routing";

// Defaults to 'B' (PASS path). Step 4 FAIL escalation: flip to 'A'
// in a one-line PR — no string-literal change anywhere else in the
// tree, the resolver picks up the new minimum tier and the
// catalog-derived engine shifts to the cheapest Google planning-A
// model.
export const FREE_ROADMAP_MIN_TIER: TaskTier = "B";

// Recommender quality floor. Stays at 'B' across Phase 4; the
// /recommend surface is a JSON proxy to the FastAPI service which
// performs its own engine routing — this floor exists so the
// outer Next.js tier matches the FastAPI service's free-tier
// posture.
export const FREE_RECOMMEND_MIN_TIER: TaskTier = "B";

// Surface-keyed override map. Empty by default — the catalog
// derivation runs untouched. When the maintainer wants to pin a
// surface to a specific model id, they set the corresponding key
// here.
export const ENGINE_OVERRIDES: {
  recommend?: string;
  roadmap?: string;
} = {
  // GPT-5-mini canary (eval-backed engine move). Pins the free/anon /recommend
  // engine to gpt-5-mini (force_provider "openai-gpt-5-mini") — best
  // instruction-adherence + ~3x cheaper with OpenAI automatic prefix caching.
  // The signed-in frontier stays on gemini-2.5-pro until this anon canary is
  // confirmed in prod (cost + adherence), then it flips too (full cutover).
  recommend: "gpt-5-mini",
};
