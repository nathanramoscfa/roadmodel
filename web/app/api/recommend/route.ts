// web/app/api/recommend/route.ts
import { NextResponse } from "next/server";
import { writeAudit, type AuditOutcome } from "@/lib/audit";
import { getModelAvailability } from "@/lib/availability";
import { getServerSession } from "@/lib/auth";
import { isE2eAuthEnabled } from "@/lib/e2e-mode";
import {
  getTimings,
  ingestServiceTimings,
  recordTotal,
  runWithTimings,
  withSpan,
} from "@/lib/latency";
import {
  NoEligibleEngineError,
  resolveRecommenderEngine,
} from "@/lib/model-routing";
import {
  DEFAULT_PROFILE,
  getAllowedJurisdictions,
  getProfile,
  type BudgetPriority,
  type JurisdictionCode,
} from "@/lib/profile";
import { BUDGET_PRIORITY_IDS, isBudgetPriority } from "@/lib/budget-priority";
import { recommenderRequestHeaders } from "@/lib/api";
import { identifyRequest, withRateLimit } from "@/lib/withRateLimit";
import { fundingNoteForModel, personalizeComparison } from "@/lib/funding";
import { env } from "@/lib/env";

const DEFAULT_RECOMMENDER_URL =
  "https://roadmodel-api.vercel.app/v1/recommend";

// Per-call cost LEDGER (Phase 4.5 T3b). Estimates the recommend ENGINE call's
// spend so signed-in frontier usage is queryable per audit row (e.g. sum
// cost_usd over signed-in rows = frontier spend). This is OUR cost, distinct
// from the recommended model's user-facing session_cost_estimate. Rates are per
// 1M tokens; the static system prompt (header + selector + tier-cost +
// user-context) dominates input at ~20k tokens. outTokens is the visible +
// (frontier) reasoning estimate. Engines absent here yield no ledger fields.
const ENGINE_RATES: Record<
  string,
  { inPer1m: number; outPer1m: number; outTokens: number }
> = {
  "gemini-2.5-flash": { inPer1m: 0.3, outPer1m: 2.5, outTokens: 512 },
  "gemini-2.5-pro": { inPer1m: 1.25, outPer1m: 10, outTokens: 900 },
};
const STATIC_PROMPT_TOKENS = 20000;

// Cost ledger for the engine call(s). `inputCalls` / `outputCalls` scale the
// static-prompt input and the visible output independently: the fan-out sends
// the big system prompt N times (inputCalls = outputCalls = 3), while the ladder
// sends it ONCE and emits ~3x the output (inputCalls = 1, outputCalls = 3) — so
// the ladder's lower input cost is reflected faithfully.
function estimateEngineCost(
  engine: string,
  taskLen: number,
  { inputCalls = 1, outputCalls = 1 }: { inputCalls?: number; outputCalls?: number } = {},
): { inputTokens: number; outputTokens: number; costUsd: number } | undefined {
  const r = ENGINE_RATES[engine];
  if (!r) return undefined;
  const inputTokens = (STATIC_PROMPT_TOKENS + Math.ceil(taskLen / 4)) * inputCalls;
  const outputTokens = r.outTokens * outputCalls;
  const costUsd =
    (inputTokens * r.inPer1m + outputTokens * r.outPer1m) / 1_000_000;
  return { inputTokens, outputTokens, costUsd: Number(costUsd.toFixed(6)) };
}

function recommenderUrl(): string {
  if (
    isE2eAuthEnabled() &&
    process.env.ROADMODEL_E2E_MOCK_RECOMMEND === "1"
  ) {
    const site =
      process.env.ROADMODEL_E2E_SITE_URL ?? "http://127.0.0.1:3000";
    return new URL("/api/test/mock-recommend", site).toString();
  }
  return process.env.ROADMODEL_RECOMMEND_URL ?? DEFAULT_RECOMMENDER_URL;
}

// The single-call ladder endpoint (tasks #1/#3): the /v1/recommend base with a
// /ladder suffix. Derived from recommenderUrl() so the ROADMODEL_RECOMMEND_URL
// override and the E2E mock host both carry through (the E2E mock serves a
// ladder-shaped body at the same path + /ladder).
function ladderUrl(): string {
  return `${recommenderUrl()}/ladder`;
}

// The ladder upstream response (tasks #1/#3): three tier-keyed picks (each the
// same shape as a fanned-out RecommenderPayload) plus the deterministic
// tier-distinctness guard the edge uses to decide whether to keep the ladder or
// fall back to the fan-out.
interface LadderPayload {
  picks?: Partial<Record<"quality" | "balanced" | "cost", RecommenderPayload>>;
  guard?: { healthy?: boolean; [k: string]: unknown };
}

// Ladder tier -> the priority id the frontend/matrix expect, in cost→best order.
const LADDER_TIER_TO_PRIORITY: ReadonlyArray<
  readonly [keyof NonNullable<LadderPayload["picks"]>, BudgetPriority]
> = [
  ["cost", "cheap"],
  ["balanced", "balanced"],
  ["quality", "best"],
];

const CN_JURISDICTION_MODELS = new Set([
  "kimi-k2.5",
  "Kimi K2.5",
]);

interface RecommenderPayload {
  model?: string;
  platform?: string;
  session_cost_estimate?: { total_usd?: number };
  settings?: Record<string, unknown>;
  comparison_table?: Record<string, unknown>[];
  // The model's reasoning, carried as a top-level field by the service (#173).
  rationale?: string;
  // Structured rationale sections (task/pick/run), carried verbatim to the
  // client so the "Why this model?" panel can render sub-headings. Best-effort
  // from the service (absent on an older service or a non-conforming model);
  // it flows through shapePick's spreads untouched — no budget/funding notes
  // are appended here, unlike settings.rationale below.
  rationale_sections?: Record<string, string> | null;
  // The conversation-handling decision (New/Continue), carried as a top-level
  // field by the service (#190). Spread through to the client via `parsed`.
  conversation?: string;
  // The fallback model (Step 7) — shown as the "Backup" line if the primary is
  // unavailable. Carried top-level by the service; spread to the client via
  // `parsed`, same as conversation. Absent when the LLM emitted no backup.
  backup?: string;
}

function isCnJurisdictionModel(model: string | undefined): boolean {
  if (!model) {
    return false;
  }
  return CN_JURISDICTION_MODELS.has(model);
}

function filterByJurisdiction(
  payload: RecommenderPayload,
  allowed: JurisdictionCode[],
): RecommenderPayload {
  if (allowed.includes("cn")) {
    return payload;
  }
  const comparison = payload.comparison_table ?? [];
  const filtered = comparison.filter((row) => {
    // Cost rows carry the model under `model_name` (SessionCostEstimate);
    // fall back to `model` for any legacy shape. Reading only `model` let a
    // jurisdiction-restricted model slip through as a cost-table alternative
    // even though it was correctly excluded as a pick.
    const model =
      typeof row.model_name === "string"
        ? row.model_name
        : typeof row.model === "string"
          ? row.model
          : "";
    return !isCnJurisdictionModel(model);
  });
  let model = payload.model;
  if (isCnJurisdictionModel(model)) {
    const fallback = filtered[0];
    model =
      fallback && typeof fallback.model === "string"
        ? fallback.model
        : undefined;
  }
  return {
    ...payload,
    model,
    comparison_table: filtered,
  };
}

function auditFor(
  req: Request,
  outcome: AuditOutcome,
  extras: Partial<Parameters<typeof writeAudit>[0]> = {},
): void {
  const id = identifyRequest(req);
  void writeAudit({
    ip_hash: id.ipHash,
    ua_hash: id.uaHash,
    route: id.route,
    outcome,
    ...extras,
  });
}

const handler = async (req: Request): Promise<Response> =>
  runWithTimings(async () => {
    // Phase 4 Step 7 — input parse + profile load + engine resolve
    // are bundled into a single dispatch span. Anything that runs
    // BEFORE the upstream fetch belongs here so provider_ms is
    // strictly the time spent on the FastAPI hop.
    let body: unknown;
    let session: Awaited<ReturnType<typeof getServerSession>>;
    let userId: string | undefined;
    let allowedJurisdictions: JurisdictionCode[];
    let budgetPriority: string;
    let subscriptions: string[];
    let apiProviders: string[];
    let taskDescription: string;
    let incomingContext: Record<string, unknown>;
    let recommenderEngine: ReturnType<typeof resolveRecommenderEngine>;

    try {
      const dispatched = await withSpan("dispatch", async () => {
        let parsedBody: unknown;
        try {
          parsedBody = await req.json();
        } catch {
          return { kind: "bad_input", error_class: "invalid_json" } as const;
        }
        if (
          typeof parsedBody !== "object" ||
          parsedBody === null ||
          typeof (parsedBody as { task_description?: unknown })
            .task_description !== "string"
        ) {
          return {
            kind: "bad_input",
            error_class: "missing_task_description",
          } as const;
        }

        const td = (parsedBody as { task_description: string })
          .task_description;
        // Reject blank / whitespace-only input before paying an upstream
        // call. The service's min_length=1 counts characters, not stripped
        // content, so "   " slipped through to a paid LLM call (#175).
        // Mirrors the too-long guard below; the service tier validates too.
        if (td.trim().length === 0) {
          return {
            kind: "bad_input",
            error_class: "blank_task_description",
          } as const;
        }
        // Mirror the service-tier task_description cap (issue #142:
        // RecommendRequest max_length=50000) at the edge so oversized
        // input is rejected here with a clear 400 instead of paying the
        // upstream fetch only to get a 422. Keep the two bounds in sync.
        if (td.length > 50000) {
          return {
            kind: "bad_input",
            error_class: "task_description_too_long",
          } as const;
        }
        const ctx =
          typeof (parsedBody as { context?: unknown }).context === "object" &&
          (parsedBody as { context?: unknown }).context !== null
            ? ((parsedBody as { context: Record<string, unknown> }).context ??
                {})
            : {};

        // Budget priority chosen inline on /recommend rides in the request
        // body so it takes effect immediately — even signed-out, and before the
        // profile PATCH lands — overriding the stored profile for THIS call.
        const bodyBudget = (parsedBody as { budget_priority?: unknown })
          .budget_priority;
        const localSession = await getServerSession();
        const localUserId = localSession?.id;
        const profile = localUserId ? await getProfile(localUserId) : null;
        const localBudget = isBudgetPriority(bodyBudget)
          ? bodyBudget
          : (profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority);
        const localJurisdictions = localUserId
          ? await getAllowedJurisdictions(localUserId)
          : [...DEFAULT_PROFILE.allowed_jurisdictions];
        // Phase 4.8 T2: the user's declared funding, for the edge-side
        // cost annotation (subscription-$0 vs API-PAYG). Empty for anon.
        const localSubscriptions =
          profile?.subscriptions ?? [...DEFAULT_PROFILE.subscriptions];
        const localApiProviders =
          profile?.api_providers ?? [...DEFAULT_PROFILE.api_providers];

        try {
          // T3b: signed-in users get the frontier engine ONLY when the gate is
          // on; anonymous requests always get the free (Flash) engine.
          const engine = resolveRecommenderEngine({
            profile,
            signedIn: Boolean(localUserId),
            frontierEnabled: env.RECOMMENDER_FRONTIER_ENABLED,
          });
          return {
            kind: "ok",
            body: parsedBody,
            session: localSession,
            userId: localUserId,
            taskDescription: td,
            incomingContext: ctx,
            allowedJurisdictions: localJurisdictions,
            budgetPriority: localBudget,
            subscriptions: localSubscriptions,
            apiProviders: localApiProviders,
            engine,
          } as const;
        } catch (err) {
          return {
            kind: "recommender_error",
            error_class:
              err instanceof NoEligibleEngineError
                ? "no_eligible_engine"
                : err instanceof Error
                  ? err.name
                  : "engine_resolve_failed",
            userId: localUserId,
          } as const;
        }
      });

      if (dispatched.kind === "bad_input") {
        recordTotal();
        auditFor(req, "bad_input", {
          error_class: dispatched.error_class,
          latency_ms: getTimings(),
        });
        return NextResponse.json({ error: "bad_input" }, { status: 400 });
      }
      if (dispatched.kind === "recommender_error") {
        recordTotal();
        auditFor(req, "recommender_error", {
          error_class: dispatched.error_class,
          user_id: dispatched.userId,
          latency_ms: getTimings(),
        });
        return NextResponse.json(
          { error: "recommender_unavailable" },
          { status: 503 },
        );
      }

      body = dispatched.body;
      session = dispatched.session;
      userId = dispatched.userId;
      taskDescription = dispatched.taskDescription;
      incomingContext = dispatched.incomingContext;
      allowedJurisdictions = dispatched.allowedJurisdictions;
      budgetPriority = dispatched.budgetPriority;
      subscriptions = dispatched.subscriptions;
      apiProviders = dispatched.apiProviders;
      recommenderEngine = dispatched.engine;
    } catch (err) {
      // Unexpected error inside the dispatch span — treat as a 500-
      // class fetch failure so the caller sees a friendly error
      // instead of an opaque 500. The audit row still carries the
      // partial latency snapshot so post-mortem analysis isn't
      // blind.
      recordTotal();
      auditFor(req, "recommender_error", {
        error_class: err instanceof Error ? err.name : "dispatch_failed",
        latency_ms: getTimings(),
      });
      return NextResponse.json(
        { error: "recommender_unavailable" },
        { status: 500 },
      );
    }

    // Silence the unused-vars lint for the body capture above;
    // body/session are kept named for parity with the original
    // handler shape and future Step 9 dashboards that may want
    // to include the original payload in the audit row.
    void body;
    void session;

    // Phase 4.9 B2/B5: forward the runtime unavailable-model ids so the selector
    // excludes a benched model (Step 0a) without a roadmodel release. Cached +
    // fail-open (empty on any error) — never blocks a recommendation. When the read
    // is authoritative (it succeeded), the list is the COMPLETE current truth and
    // the selector supersedes its bundled fallback with it — so a model the probe/AI
    // verifier has RESTORED becomes recommendable again with no release. A failed
    // read is not authoritative -> the service keeps its fail-closed static defaults.
    const { ids: unavailableModels, authoritative: availabilityAuthoritative } =
      await getModelAvailability();

    // Shape ONE upstream pick (jurisdiction filter + funding personalization +
    // rationale assembly) for a given budget priority. Lifted verbatim from the
    // former single-call render span and parameterized on `priority` so it can
    // run once per priority below. Pure + sync; closes over the request's
    // jurisdictions + declared funding.
    const shapePick = (
      parsed: RecommenderPayload | null,
      priority: string,
    ): RecommenderPayload => {
      let payload = filterByJurisdiction(parsed ?? {}, allowedJurisdictions);

      // Phase 4.8 T3: re-rank + relabel the cost table's per-platform rows to
      // THIS user's funding (subscription-$0 vs API-PAYG vs unfunded). Anon /
      // no declared funding -> rows unchanged (never changes the model picked).
      if (payload.comparison_table) {
        payload = {
          ...payload,
          comparison_table: personalizeComparison(
            payload.comparison_table,
            subscriptions,
            apiProviders,
          ),
        };
      }

      if (payload.settings) {
        payload = {
          ...payload,
          settings: { ...payload.settings, budget_priority: priority },
        };
      }

      // Surface the model's own reasoning in settings.rationale (the field the
      // UI reads), appending the budget-priority note unless already named.
      const baseRationale =
        (typeof payload.settings?.rationale === "string" &&
          payload.settings.rationale) ||
        (typeof payload.rationale === "string" && payload.rationale) ||
        "";
      const withBudget = !baseRationale.includes(priority)
        ? baseRationale
          ? `${baseRationale} Budget priority: ${priority}.`
          : `Budget priority: ${priority}.`
        : baseRationale;
      // T3 dedup (#270): when the personalized cost table renders it already
      // shows the funded path, so omit the funding sentence; keep it as a
      // fallback only when there's no table.
      const tableShowsFunding =
        Array.isArray(payload.comparison_table) &&
        payload.comparison_table.length > 0;
      const fundingNote = tableShowsFunding
        ? null
        : fundingNoteForModel(payload.model ?? "", subscriptions, apiProviders);
      const rationale = fundingNote
        ? withBudget
          ? `${withBudget} ${fundingNote}`
          : fundingNote
        : withBudget;
      if (rationale) {
        payload = {
          ...payload,
          settings: { ...(payload.settings ?? {}), rationale },
        };
      }
      return payload;
    };

    // Fan out one upstream /v1/recommend call per budget priority. The page now
    // shows Cost / Balanced / Quality side by side from a SINGLE user request
    // (so users see the cost-vs-quality trade-off for their prompt instead of
    // pre-committing with a toggle). One call per priority, run in parallel, so
    // wall-clock ~= a single call; the recommender is deterministic (temp 0) so
    // the three picks are stable + reliably ordered. Still ONE request -> one
    // rate-limit decrement. Never throws: a per-priority failure degrades that
    // column rather than the whole response.
    type PickFetch =
      | {
          priority: BudgetPriority;
          ok: true;
          parsed: RecommenderPayload | null;
          timing: string | null;
        }
      | { priority: BudgetPriority; ok: false; status: number; body: string };

    const fetchOne = async (priority: BudgetPriority): Promise<PickFetch> => {
      const upstreamPayload = {
        task_description: taskDescription,
        context: {
          ...incomingContext,
          unavailable_models: unavailableModels,
          availability_authoritative: availabilityAuthoritative,
          budget_priority: priority,
          allowed_jurisdictions: allowedJurisdictions,
          // Phase 4.8 T2b (#163): forward declared funding so the service biases
          // SELECTION toward a $0-funded surface on a quality tie. No keys sent.
          subscriptions,
          api_providers: apiProviders,
          force_provider: recommenderEngine.force_provider,
        },
      };
      let upstream: Response;
      try {
        upstream = await fetch(recommenderUrl(), {
          method: "POST",
          headers: recommenderRequestHeaders(),
          body: JSON.stringify(upstreamPayload),
        });
      } catch (err) {
        return {
          priority,
          ok: false,
          status: 502,
          body: err instanceof Error ? err.name : "fetch_failed",
        };
      }
      const text = await upstream.text();
      if (!upstream.ok) {
        return { priority, ok: false, status: upstream.status, body: text };
      }
      let parsed: RecommenderPayload | null = null;
      try {
        parsed = JSON.parse(text) as RecommenderPayload;
      } catch {
        parsed = null;
      }
      return {
        priority,
        ok: true,
        parsed,
        timing: upstream.headers.get("X-Roadmodel-Timing"),
      };
    };

    // Shape one upstream pick payload into the client-facing recommendation —
    // shared by both the ladder and the fan-out so they emit identical objects.
    const toRecommendation = (
      parsed: RecommenderPayload | null,
      priority: BudgetPriority,
    ) => ({
      ...shapePick(parsed, priority),
      priority,
      // Same engine for every pick (T3b tier label).
      tier: recommenderEngine.use_frontier ? "frontier" : "free",
      engine: recommenderEngine.engine,
    });

    // Tasks #1/#3 — one upstream call returns the whole anchored Cost/Balanced/
    // Quality ladder (Quality first, Balanced/Cost strictly lower). Returns null
    // on any error OR an UNHEALTHY (collapsed) ladder so the caller falls back to
    // the fan-out — the ladder can never make the result worse than today.
    const fetchLadder = async (): Promise<
      ReturnType<typeof toRecommendation>[] | null
    > => {
      const upstreamPayload = {
        task_description: taskDescription,
        context: {
          ...incomingContext,
          unavailable_models: unavailableModels,
          availability_authoritative: availabilityAuthoritative,
          // No budget_priority — the ladder emits all three tiers itself.
          allowed_jurisdictions: allowedJurisdictions,
          subscriptions,
          api_providers: apiProviders,
          force_provider: recommenderEngine.force_provider,
        },
      };
      let upstream: Response;
      try {
        upstream = await fetch(ladderUrl(), {
          method: "POST",
          headers: recommenderRequestHeaders(),
          body: JSON.stringify(upstreamPayload),
        });
      } catch {
        return null;
      }
      if (!upstream.ok) return null;
      let parsed: LadderPayload | null = null;
      try {
        parsed = JSON.parse(await upstream.text()) as LadderPayload;
      } catch {
        parsed = null;
      }
      const picks = parsed?.picks;
      if (!picks) return null;
      // A collapsed (unhealthy) ladder -> fall back to the fan-out.
      if (parsed?.guard?.healthy === false) return null;
      // One sample decomposes the provider span (Step 7).
      ingestServiceTimings(upstream.headers.get("X-Roadmodel-Timing"));
      const recs: ReturnType<typeof toRecommendation>[] = [];
      for (const [tier, priority] of LADDER_TIER_TO_PRIORITY) {
        const pick = picks[tier];
        if (!pick) return null; // incomplete ladder -> fall back
        recs.push(toRecommendation(pick, priority));
      }
      return recs;
    };

    let recommendations: ReturnType<typeof toRecommendation>[];
    let ladderMode = false;

    const ladderRecs = env.RECOMMEND_LADDER_ENABLED
      ? await withSpan("provider", fetchLadder)
      : null;

    if (ladderRecs) {
      recommendations = await withSpan("render", async () => ladderRecs);
      ladderMode = true;
    } else {
      const results = await withSpan("provider", async () =>
        Promise.all(BUDGET_PRIORITY_IDS.map(fetchOne)),
      );

      const ok = results.filter(
        (r): r is Extract<PickFetch, { ok: true }> => r.ok,
      );
      // Decompose the provider span via the first pick's timing header (Step 7);
      // the three calls share an engine so one sample is representative.
      if (ok.length > 0) {
        ingestServiceTimings(ok[0].timing);
      }

      if (ok.length === 0) {
        recordTotal();
        const first = results.find(
          (r): r is Extract<PickFetch, { ok: false }> => !r.ok,
        );
        const status = first?.status ?? 502;
        auditFor(req, "recommender_error", {
          error_class: `upstream_${status}`,
          user_id: userId,
          latency_ms: getTimings(),
        });
        return new NextResponse(
          first?.body ?? JSON.stringify({ error: "recommender_unavailable" }),
          { status, headers: { "Content-Type": "application/json" } },
        );
      }

      recommendations = await withSpan("render", async () =>
        // results preserve BUDGET_PRIORITY_IDS order (Cost -> Balanced -> Quality).
        ok.map((r) => toRecommendation(r.parsed, r.priority)),
      );
    }

    // The scoring span preserves the four-span shape the audit contract
    // documents (no-op body; the audit write happens after recordTotal()).
    await withSpan("scoring", async () => {});

    // Per-call cost ledger (T3b): OUR engine spend. The fan-out sends the big
    // system prompt once PER priority (n input + n output "calls"); the ladder
    // sends it ONCE and emits ~n× the output — so scale input/output separately.
    // provider/model name the PRIMARY (highlighted) pick.
    const primaryPick =
      recommendations.find((r) => r.priority === budgetPriority) ??
      recommendations[0];
    const n = recommendations.length;
    const per = estimateEngineCost(recommenderEngine.engine, taskDescription.length, {
      inputCalls: ladderMode ? 1 : n,
      outputCalls: n,
    });
    recordTotal();
    auditFor(req, "ok", {
      provider: primaryPick.platform,
      model: primaryPick.model,
      input_tokens: per?.inputTokens,
      output_tokens: per?.outputTokens,
      cost_usd: per?.costUsd,
      user_id: userId,
      latency_ms: getTimings(),
    });

    return new NextResponse(
      JSON.stringify({ recommendations, primary: budgetPriority }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

export const POST = withRateLimit(handler, async () => {
  const session = await getServerSession();
  return session?.id;
});
