// web/app/api/recommend/route.ts
import { NextResponse } from "next/server";
import { writeAudit, type AuditOutcome } from "@/lib/audit";
import { getUnavailableModelIds } from "@/lib/availability";
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
  type JurisdictionCode,
} from "@/lib/profile";
import { isBudgetPriority } from "@/lib/budget-priority";
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

function estimateEngineCost(
  engine: string,
  taskLen: number,
): { inputTokens: number; outputTokens: number; costUsd: number } | undefined {
  const r = ENGINE_RATES[engine];
  if (!r) return undefined;
  const inputTokens = STATIC_PROMPT_TOKENS + Math.ceil(taskLen / 4);
  const outputTokens = r.outTokens;
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
    const model = typeof row.model === "string" ? row.model : "";
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

    // Phase 4.9 B2: forward the runtime unavailable-model ids so the selector
    // excludes a benched model (Step 0a) without a roadmodel release. Cached +
    // fail-open (empty on any error) — never blocks a recommendation.
    const unavailableModels = await getUnavailableModelIds();

    const upstreamPayload = {
      task_description: taskDescription,
      context: {
        ...incomingContext,
        unavailable_models: unavailableModels,
        budget_priority: budgetPriority,
        allowed_jurisdictions: allowedJurisdictions,
        // Phase 4.8 T2b (#163): forward the user's declared funding so the
        // service can build a per-user user-context and the recommendation LLM's
        // model SELECTION prefers a surface the user funds at $0 on a quality
        // tie. Empty arrays for anon -> the service builds no per-user context
        // (bundled template, unchanged). No keys are sent — api_providers is a
        // per-provider boolean signal only.
        subscriptions,
        api_providers: apiProviders,
        force_provider: recommenderEngine.force_provider,
      },
    };

    let upstream: Response;
    try {
      upstream = await withSpan("provider", async () =>
        fetch(recommenderUrl(), {
          method: "POST",
          headers: recommenderRequestHeaders(),
          body: JSON.stringify(upstreamPayload),
        }),
      );
    } catch (err) {
      recordTotal();
      auditFor(req, "recommender_error", {
        error_class: err instanceof Error ? err.name : "fetch_failed",
        user_id: userId,
        latency_ms: getTimings(),
      });
      return NextResponse.json(
        { error: "recommender_unavailable" },
        { status: 502 },
      );
    }

    // Decompose the provider span into the upstream's
    // service_scoring_ms + service_provider_ms via the
    // X-Roadmodel-Timing header (Step 7 contract). When the
    // upstream is older than Step 7 the header is missing and
    // ingestServiceTimings is a no-op — provider_ms stays opaque
    // for those rows.
    ingestServiceTimings(upstream.headers.get("X-Roadmodel-Timing"));

    const upstreamBody = await upstream.text();
    let parsed: RecommenderPayload | null = null;
    try {
      parsed = JSON.parse(upstreamBody) as RecommenderPayload;
    } catch {
      parsed = null;
    }

    if (!upstream.ok) {
      recordTotal();
      auditFor(req, "recommender_error", {
        error_class: `upstream_${upstream.status}`,
        user_id: userId,
        latency_ms: getTimings(),
      });
      return new NextResponse(upstreamBody, {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const responsePayload = await withSpan("render", async () => {
      let payload = parsed ?? {};
      payload = filterByJurisdiction(payload, allowedJurisdictions);

      // Phase 4.8 T3: re-rank + relabel the cost table's per-platform rows to
      // THIS user's funding (subscription-$0 vs API-PAYG vs unfunded). The
      // service computes the table against the bundled founder context, so
      // without this a signed-in user would see the founder's funding. Anon /
      // no declared funding -> rows unchanged (consider-all, surface-cheaper;
      // never changes which model was selected).
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

      if (budgetPriority && payload.settings) {
        payload = {
          ...payload,
          settings: {
            ...payload.settings,
            budget_priority: budgetPriority,
          },
        };
      }

      // Surface the model's own reasoning in settings.rationale (the field the
      // UI reads). recommend_structured emits it as a TOP-LEVEL `rationale`;
      // the service passes it through (#173), with settings.rationale as a
      // fallback. Append the budget-priority note unless the reasoning already
      // names it (avoid redundancy) — but ALWAYS surface the reasoning itself,
      // even when it mentions the budget word, or the "Why this model?" panel
      // goes blank for those picks (e.g. a budget=best rationale saying "best").
      // budget_priority is set on settings by the block above.
      const baseRationale =
        (typeof payload.settings?.rationale === "string" &&
          payload.settings.rationale) ||
        (typeof payload.rationale === "string" && payload.rationale) ||
        "";
      const withBudget =
        budgetPriority && !baseRationale.includes(budgetPriority)
          ? baseRationale
            ? `${baseRationale} Budget priority: ${budgetPriority}.`
            : `Budget priority: ${budgetPriority}.`
          : baseRationale;
      // Phase 4.8 T2: the user's cheapest funded path for the recommended
      // model (subscription-$0 vs API-PAYG), computed deterministically from
      // their declared funding. Null when they've declared nothing that reaches
      // the model — never changes the model that was selected.
      //
      // T3 dedup (#270): when the personalized cost table will render (non-empty),
      // it already shows this funded path ("✓ $0 · <sub>"), so omit the funding
      // sentence from the rationale to avoid duplicating it. Keep it as a
      // fallback only when there's no table (e.g. cost estimation returned none).
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
          settings: {
            ...(payload.settings ?? {}),
            rationale,
          },
        };
      }
      return payload;
    });

    // The scoring span is a thin wrapper around the audit-row
    // assembly. It exists for symmetric naming so Phase 9
    // dashboards can decompose the request into the same four
    // span buckets regardless of which surface (recommend /
    // roadmap) the row came from.
    await withSpan("scoring", async () => {
      // Intentional no-op body — the audit write itself happens
      // AFTER recordTotal() below so the row carries the final
      // latency_ms map. Keeping this span empty (rather than
      // skipping it) preserves the four-span shape the audit
      // contract documents.
    });

    // Per-call cost ledger (T3b): record OUR engine call's estimated spend +
    // tokens. provider/model stay as the RECOMMENDATION (what we returned);
    // cost_usd/input_tokens/output_tokens are the engine call (what it cost us).
    const engineCost = estimateEngineCost(
      recommenderEngine.engine,
      taskDescription.length,
    );
    recordTotal();
    auditFor(req, "ok", {
      provider: responsePayload.platform,
      model: responsePayload.model,
      input_tokens: engineCost?.inputTokens,
      output_tokens: engineCost?.outputTokens,
      cost_usd: engineCost?.costUsd,
      user_id: userId,
      latency_ms: getTimings(),
    });

    // Surface the engine tier so the client renders an accurate tier label
    // (T3b): signed-in frontier users should not be told to "upgrade for
    // frontier models" when they are already on Gemini 2.5 Pro.
    const tieredPayload = {
      ...responsePayload,
      tier: recommenderEngine.use_frontier ? "frontier" : "free",
      engine: recommenderEngine.engine,
    };

    return new NextResponse(JSON.stringify(tieredPayload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });

export const POST = withRateLimit(handler, async () => {
  const session = await getServerSession();
  return session?.id;
});
