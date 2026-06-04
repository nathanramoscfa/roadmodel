// web/app/api/recommend/route.ts
import { NextResponse } from "next/server";
import { writeAudit, type AuditOutcome } from "@/lib/audit";
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
import { identifyRequest, withRateLimit } from "@/lib/withRateLimit";

const DEFAULT_RECOMMENDER_URL =
  "https://roadmodel-api.vercel.app/v1/recommend";

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

        const localSession = await getServerSession();
        const localUserId = localSession?.id;
        const profile = localUserId ? await getProfile(localUserId) : null;
        const localBudget =
          profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority;
        const localJurisdictions = localUserId
          ? await getAllowedJurisdictions(localUserId)
          : [...DEFAULT_PROFILE.allowed_jurisdictions];

        try {
          const engine = resolveRecommenderEngine({ profile });
          return {
            kind: "ok",
            body: parsedBody,
            session: localSession,
            userId: localUserId,
            taskDescription: td,
            incomingContext: ctx,
            allowedJurisdictions: localJurisdictions,
            budgetPriority: localBudget,
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

    const upstreamPayload = {
      task_description: taskDescription,
      context: {
        ...incomingContext,
        budget_priority: budgetPriority,
        allowed_jurisdictions: allowedJurisdictions,
        force_provider: recommenderEngine.force_provider,
      },
    };

    let upstream: Response;
    try {
      upstream = await withSpan("provider", async () =>
        fetch(recommenderUrl(), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
      const rationale =
        budgetPriority && !baseRationale.includes(budgetPriority)
          ? baseRationale
            ? `${baseRationale} Budget priority: ${budgetPriority}.`
            : `Budget priority: ${budgetPriority}.`
          : baseRationale;
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

    recordTotal();
    auditFor(req, "ok", {
      provider: responsePayload.platform,
      model: responsePayload.model,
      cost_usd: responsePayload.session_cost_estimate?.total_usd,
      user_id: userId,
      latency_ms: getTimings(),
    });

    return new NextResponse(JSON.stringify(responsePayload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });

export const POST = withRateLimit(handler, async () => {
  const session = await getServerSession();
  return session?.id;
});
