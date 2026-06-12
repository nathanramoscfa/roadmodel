// web/lib/model-routing.ts
//
// 4D model tiering scaffold (per ROADMAP §6 — Phase 4 application
// of "Engine selection + free-tier override"). Two free-tier
// surfaces consume this module:
//
//   1. /api/recommend  → resolveRecommenderEngine() returns the
//      catalog-tracked engine the FastAPI recommender service is
//      forced to use. Phase 3 hard-coded "google-gemini-2.5-flash";
//      Step 6 makes that string catalog-derived so the Phase 9 §9.2
//      auto-refresh cron flips it when a cheaper qualifying
//      knowledge-B Google model shows up in cursor.com's pricing
//      page.
//
//   2. /api/roadmap    → resolveRoadmapEngine() returns the
//      free-tier engine the @google/genai SDK call is parameterized
//      on. Step 4 PASS keeps it at `gemini-2.5-flash`; Step 4 FAIL
//      escalation flips FREE_ROADMAP_MIN_TIER from 'B' to 'A' in
//      engine-overrides.ts, which shifts the derived engine to
//      `gemini-3-flash`. The model swap is the only difference
//      between PASS and FAIL paths — same SDK, same caching API,
//      same provider-side billing meter.
//
// The frontier branch (Phase 5 paid rollout) returns a Claude
// Sonnet 4.6 / Opus 4.7 shape; the downstream roadmap-engine
// wrapper throws a documented "Phase 5 scope" error if it is
// actually invoked during Phase 4. This is defense-in-depth — the
// resolver's return shape is valid; the wrapper is the gate.
//
// Phase 4 free-tier picks are constrained to provider='google'
// because the only free-tier engine wrapper this phase ships is
// @google/genai. As Phase 5+ broadens supported providers the
// resolver's provider filter lifts in lockstep with engine-wrapper
// coverage — anything else routes cost-optimal picks toward
// engines the wrapper can't execute. The catalog-tracking property
// holds regardless: the Phase 9 §9.2 cron's engine re-derivation
// automation finds a moving target as the catalog refreshes
// against the upstream Cursor pricing page.

import catalog from "@/data/catalog.json";
import {
  ENGINE_OVERRIDES,
  FREE_RECOMMEND_MIN_TIER,
  FREE_ROADMAP_MIN_TIER,
} from "./engine-overrides";
import { DEFAULT_PROFILE, type JurisdictionCode, type Profile } from "./profile";

// Tier ordering matches the docs/model-selector.txt's quality scale where S
// is best and D is worst. `tierRank` lets us compare candidates
// against the surface's minTier with a simple `<=` check (lower
// rank == higher quality).
export type TaskTier = "S" | "A" | "B" | "C" | "D";
const TIER_RANK: Record<TaskTier, number> = {
  S: 0,
  A: 1,
  B: 2,
  C: 3,
  D: 4,
};

export type EngineSurface = "recommend" | "roadmap";

// Map a surface to its PRIMARY task category in the
// docs/model-selector.txt's <task-categories> taxonomy. Surface-driven
// rather than profile-driven because the surface determines what
// the model is being asked to do; the profile influences only the
// jurisdiction filter.
const SURFACE_PRIMARY: Record<EngineSurface, keyof CatalogTiers> = {
  recommend: "knowledge",
  roadmap: "planning",
};

// "Frontier" tier_cost values — high and very-high. Catalog
// candidates in these tiers belong to the paid frontier branch,
// not the free-tier path; the resolver filters them out before
// considering cost order.
const FRONTIER_TIER_COSTS = new Set(["high", "very-high"]);

// Phase 4 free-tier provider allow-list. See header comment — the
// only free-tier engine wrapper this phase ships is @google/genai,
// so catalog candidates outside Google would route requests at an
// SDK the wrapper cannot execute. Phase 5+ lifts this filter as
// new provider wrappers come online.
const PHASE4_FREE_TIER_PROVIDERS = new Set(["google"]);

interface CatalogTiers {
  coding?: TaskTier;
  planning?: TaskTier;
  agentic?: TaskTier;
  multimodal?: TaskTier;
  "long-context"?: TaskTier;
  knowledge?: TaskTier;
  speed?: TaskTier;
}

interface CatalogModel {
  id: string;
  name?: string;
  input_price_per_1m?: number;
  output_price_per_1m?: number;
  cache_read_per_1m?: number;
  tier_cost?: string;
  tiers?: CatalogTiers;
  jurisdiction?: JurisdictionCode;
}

interface CatalogShape {
  models: CatalogModel[];
}

const CATALOG: CatalogShape = catalog as CatalogShape;

// Provider derivation from model id. The catalog's `id` field
// encodes the provider via well-known prefixes (and a small set of
// Anthropic exceptions — `sonnet-4.6`, `opus-4.7` — that omit the
// "claude-" prefix). Phase 4 only uses the result for two things:
// (1) the PHASE4_FREE_TIER_PROVIDERS gate, (2) the force_provider
// wire string handed to the FastAPI recommender service. A future
// catalog refresh can replace this with a `provider` column when
// the upstream pricing page exposes one.
export function inferProvider(id: string): string {
  if (id.startsWith("gemini-")) return "google";
  if (id.startsWith("gpt-")) return "openai";
  if (id.startsWith("composer-")) return "cursor";
  if (id.startsWith("grok-")) return "xai";
  if (id.startsWith("kimi-")) return "moonshot";
  if (id.startsWith("deepseek-")) return "deepseek";
  // Mistral's code model "codestral" carries no "mistral-" prefix — handle it
  // like the Anthropic sonnet-/opus- exceptions below (Phase 4.6 T5 providers).
  if (id.startsWith("mistral-") || id === "codestral") return "mistral";
  if (
    id.startsWith("claude-") ||
    id.startsWith("sonnet-") ||
    id.startsWith("opus-") ||
    id.startsWith("haiku-")
  ) {
    return "anthropic";
  }
  return "unknown";
}

export interface ResolvedEngine {
  // Catalog id (e.g. "gemini-2.5-flash") for the engine wrapper.
  engine: string;
  // Phase-4 provider gate: "google" for free-tier; "anthropic" for
  // Phase 5 frontier. The wrapper's provider switch keys on this.
  provider: string;
  // FastAPI recommender service wire format: "<provider>-<id>".
  // Recommender route passes this verbatim as `force_provider` to
  // pin the upstream engine choice. Returned regardless of surface
  // so callers can audit-log a consistent identifier across
  // /recommend and /roadmap.
  force_provider: string;
  // Per-call max output tokens for the engine wrapper. Free tier
  // shares the GEMINI_MAX_OUTPUT_TOKENS budget; frontier engines
  // get a smaller default because their output prices are 5–10x.
  max_tokens: number;
  // True for the Phase 5 frontier branch; false for the Phase 4
  // free-tier path. The wrapper uses this to pick the SDK call
  // shape (and, in Phase 4, to enforce the defensive throw).
  use_frontier: boolean;
}

export class NoEligibleEngineError extends Error {
  readonly surface: EngineSurface;
  readonly minTier: TaskTier;
  constructor(surface: EngineSurface, minTier: TaskTier) {
    super(
      `No catalog engine matches surface=${surface}, minTier=${minTier}. ` +
        "Catalog drift; check engine-overrides.ts or refresh docs/catalog.json.",
    );
    this.name = "NoEligibleEngineError";
    this.surface = surface;
    this.minTier = minTier;
  }
}

interface PickFreeEngineArgs {
  surface: EngineSurface;
  minTier: TaskTier;
  allowedJurisdictions: JurisdictionCode[];
}

// Build a ResolvedEngine for a known catalog id. Used by the
// override path (skips catalog filtering) and by the catalog path
// (after the survivor is chosen). Throws NoEligibleEngineError if
// the override pins an id that's no longer in the catalog —
// otherwise a typo in the override file would silently route to
// "unknown" provider.
function _resolveByIdFromCatalog(
  catalogShape: CatalogShape,
  id: string,
  surface: EngineSurface,
): ResolvedEngine {
  const model = catalogShape.models.find((m) => m.id === id);
  if (!model) {
    throw new NoEligibleEngineError(surface, "B");
  }
  const provider = inferProvider(id);
  return {
    engine: id,
    provider,
    force_provider: `${provider}-${id}`,
    max_tokens: 8192,
    use_frontier: false,
  };
}

// Phase 4 free-tier catalog derivation. The algorithm is a slimmed
// version of <selection-algorithm> in docs/model-selector.txt:
//
//   1. Honor the ENGINE_OVERRIDES escape hatch — when set, skip the
//      catalog filter chain entirely.
//   2. Filter by jurisdiction (model's jurisdiction must be in the
//      caller's allow-list).
//   3. Pick the surface's PRIMARY task category (knowledge for
//      /recommend, planning for /roadmap).
//   4. Filter out frontier tiers (tier_cost in high/very-high).
//   5. Phase 4 provider gate: only Google engines are wrapper-
//      executable. Phase 5+ lifts this in lockstep with new
//      wrapper branches.
//   6. Filter by tier rank: tiers[primary] must be at least as
//      good as minTier (lower rank == higher quality).
//   7. Sort by output_price_per_1m ascending; stable sort breaks
//      ties on catalog order, which the auto-refresh cron's diff
//      surfaces in the PR review when it changes.
//   8. Return the first survivor — or throw NoEligibleEngineError
//      if the filter chain eliminates every candidate (catalog
//      drift; the maintainer either lowers the floor in
//      engine-overrides.ts or pins via ENGINE_OVERRIDES).
export function pickFreeEngine(args: PickFreeEngineArgs): ResolvedEngine {
  return _pickFreeEngineFromCatalog(CATALOG, args);
}

// Test seam: exposed so the prompt-caching spec can inject a
// synthetic catalog and verify the auto-pick shifts when a
// cheaper qualifying model appears. Production never calls this;
// pickFreeEngine() is the production entry point and uses the
// bundled catalog.
export function _pickFreeEngineFromCatalog(
  catalogShape: CatalogShape,
  args: PickFreeEngineArgs,
): ResolvedEngine {
  const { surface, minTier, allowedJurisdictions } = args;

  // (1) Override escape hatch. The override file is the
  // maintainer's authoritative-by-construction signal that the
  // catalog derivation should be skipped for this surface.
  const overrideId = ENGINE_OVERRIDES[surface];
  if (overrideId) {
    return _resolveByIdFromCatalog(catalogShape, overrideId, surface);
  }

  const primary = SURFACE_PRIMARY[surface];
  const allowed = new Set(allowedJurisdictions);
  const minRank = TIER_RANK[minTier];

  // Build candidate list with all filters applied. Each step's
  // semantics is documented inline so a future catalog refresh
  // can drop in additional filters without re-reading the spec.
  const survivors = catalogShape.models.filter((m) => {
    // (2) Jurisdiction filter — skips unknowns unless the caller
    // explicitly allow-lists "unknown".
    if (!m.jurisdiction || !allowed.has(m.jurisdiction)) {
      return false;
    }
    // (4) Frontier exclusion.
    if (m.tier_cost && FRONTIER_TIER_COSTS.has(m.tier_cost)) {
      return false;
    }
    // (5) Phase 4 provider gate.
    const provider = inferProvider(m.id);
    if (!PHASE4_FREE_TIER_PROVIDERS.has(provider)) {
      return false;
    }
    // (6) Tier-rank filter on the surface's primary category.
    const tier = m.tiers?.[primary];
    if (!tier) {
      return false;
    }
    return TIER_RANK[tier] <= minRank;
  });

  if (survivors.length === 0) {
    throw new NoEligibleEngineError(surface, minTier);
  }

  // (7) Stable sort by output price ascending. The toSorted-like
  // approach (slice then sort) preserves catalog order for ties.
  const sorted = [...survivors].sort((a, b) => {
    const pa = a.output_price_per_1m ?? Number.POSITIVE_INFINITY;
    const pb = b.output_price_per_1m ?? Number.POSITIVE_INFINITY;
    return pa - pb;
  });

  const winner = sorted[0];
  const provider = inferProvider(winner.id);
  return {
    engine: winner.id,
    provider,
    force_provider: `${provider}-${winner.id}`,
    max_tokens: 8192,
    use_frontier: false,
  };
}

interface ResolveRoadmapEngineArgs {
  profile: Profile | null;
  envFrontierEnabled: boolean;
}

// Roadmap-surface entry point. Frontier branch fires when EITHER
// the env-var default is enabled OR the per-user override is
// explicitly TRUE; the per-user FALSE override forces the free
// tier even if the env var is on. The defensive throw in the
// roadmap-engine wrapper means Phase 4 never actually executes
// the frontier branch's @anthropic call shape.
export function resolveRoadmapEngine(
  args: ResolveRoadmapEngineArgs,
): ResolvedEngine {
  const { profile, envFrontierEnabled } = args;
  const userOverride = profile?.frontier_roadmap_override ?? null;
  const useFrontier = userOverride === true
    ? true
    : userOverride === false
      ? false
      : envFrontierEnabled;

  if (useFrontier) {
    // Phase 5 shape. The resolver returns a valid Anthropic
    // configuration; the downstream wrapper is the gate that
    // throws the "Phase 5 scope" error in Phase 4.
    return {
      engine: "claude-sonnet-4-6",
      provider: "anthropic",
      force_provider: "anthropic-claude-sonnet-4-6",
      max_tokens: 4096,
      use_frontier: true,
    };
  }

  return pickFreeEngine({
    surface: "roadmap",
    minTier: FREE_ROADMAP_MIN_TIER,
    allowedJurisdictions:
      profile?.allowed_jurisdictions ??
      [...DEFAULT_PROFILE.allowed_jurisdictions],
  });
}

interface ResolveRecommenderEngineArgs {
  profile: Profile | null;
  // True when the request carries an authenticated session. The frontier
  // quality tier is signed-in-only; anonymous requests always get the free
  // engine. (Phase 4.5 T3b)
  signedIn?: boolean;
  // RECOMMENDER_FRONTIER_ENABLED gate. Off by default → the free engine for
  // everyone (the increment-1 dark-ship state). (Phase 4.5 T3b)
  frontierEnabled?: boolean;
}

// Phase 4.5 T3b signed-in quality-tier engine: Gemini 2.5 Pro on the Google
// key, run with reasoning ON by the FastAPI service (which keys its thinking-ON
// params off this model id — see service/app/recommend.py). The 2026-06-06
// bake-off picked it as the lowest-coupling engine that clears the #185/#188
// adherence residuals the free-tier Flash engine left open. max_tokens mirrors
// the service's frontier combined cap; use_frontier marks the audit row for the
// per-call cost ledger.
const FRONTIER_RECOMMENDER_ENGINE = "gemini-2.5-pro";

// Recommender-surface entry point. Free engine (catalog-derived Flash) by
// default; routes signed-in requests to the frontier engine ONLY when
// RECOMMENDER_FRONTIER_ENABLED is on. The `force_provider` string passes
// through to the FastAPI recommender as the upstream engine pin.
export function resolveRecommenderEngine(
  args: ResolveRecommenderEngineArgs,
): ResolvedEngine {
  const { profile, signedIn = false, frontierEnabled = false } = args;
  if (signedIn && frontierEnabled) {
    return {
      engine: FRONTIER_RECOMMENDER_ENGINE,
      provider: "google",
      force_provider: `google-${FRONTIER_RECOMMENDER_ENGINE}`,
      max_tokens: 2048,
      use_frontier: true,
    };
  }
  return pickFreeEngine({
    surface: "recommend",
    minTier: FREE_RECOMMEND_MIN_TIER,
    allowedJurisdictions:
      profile?.allowed_jurisdictions ??
      [...DEFAULT_PROFILE.allowed_jurisdictions],
  });
}
