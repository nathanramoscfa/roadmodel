// web/app/api/recommend/route.ts
import { NextResponse } from "next/server";
import { writeAudit, type AuditOutcome } from "@/lib/audit";
import { getServerSession } from "@/lib/auth";
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
    process.env.ROADMODEL_E2E_AUTH === "1" &&
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

const handler = async (req: Request): Promise<Response> => {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    auditFor(req, "bad_input", { error_class: "invalid_json" });
    return NextResponse.json({ error: "bad_input" }, { status: 400 });
  }

  if (
    typeof body !== "object" ||
    body === null ||
    typeof (body as { task_description?: unknown }).task_description !==
      "string"
  ) {
    auditFor(req, "bad_input", { error_class: "missing_task_description" });
    return NextResponse.json({ error: "bad_input" }, { status: 400 });
  }

  const taskDescription = (body as { task_description: string })
    .task_description;
  const incomingContext =
    typeof body === "object" &&
    body !== null &&
    typeof (body as { context?: unknown }).context === "object" &&
    (body as { context?: unknown }).context !== null
      ? ((body as { context: Record<string, unknown> }).context ?? {})
      : {};

  const session = await getServerSession();
  const userId = session?.id;
  const profile = userId ? await getProfile(userId) : null;
  const budgetPriority =
    profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority;
  const allowedJurisdictions = userId
    ? await getAllowedJurisdictions(userId)
    : [...DEFAULT_PROFILE.allowed_jurisdictions];

  const upstreamPayload = {
    task_description: taskDescription,
    context: {
      ...incomingContext,
      budget_priority: budgetPriority,
      allowed_jurisdictions: allowedJurisdictions,
      force_provider: "google-gemini-2.5-flash",
    },
  };

  let upstream: Response;
  try {
    upstream = await fetch(recommenderUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(upstreamPayload),
    });
  } catch (err) {
    auditFor(req, "recommender_error", {
      error_class: err instanceof Error ? err.name : "fetch_failed",
      user_id: userId,
    });
    return NextResponse.json(
      { error: "recommender_unavailable" },
      { status: 502 },
    );
  }

  const upstreamBody = await upstream.text();
  let parsed: RecommenderPayload | null = null;
  try {
    parsed = JSON.parse(upstreamBody) as RecommenderPayload;
  } catch {
    parsed = null;
  }

  if (!upstream.ok) {
    auditFor(req, "recommender_error", {
      error_class: `upstream_${upstream.status}`,
      user_id: userId,
    });
    return new NextResponse(upstreamBody, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  let responsePayload = parsed ?? {};
  responsePayload = filterByJurisdiction(responsePayload, allowedJurisdictions);

  if (budgetPriority && responsePayload.settings) {
    responsePayload = {
      ...responsePayload,
      settings: {
        ...responsePayload.settings,
        budget_priority: budgetPriority,
      },
    };
  }

  const rationale =
    typeof responsePayload.settings?.rationale === "string"
      ? responsePayload.settings.rationale
      : "";
  if (budgetPriority && !rationale.includes(budgetPriority)) {
    responsePayload = {
      ...responsePayload,
      settings: {
        ...(responsePayload.settings ?? {}),
        rationale: rationale
          ? `${rationale} Budget priority: ${budgetPriority}.`
          : `Budget priority: ${budgetPriority}.`,
        budget_priority: budgetPriority,
      },
    };
  }

  auditFor(req, "ok", {
    provider: responsePayload.platform,
    model: responsePayload.model,
    cost_usd: responsePayload.session_cost_estimate?.total_usd,
    user_id: userId,
  });

  return new NextResponse(JSON.stringify(responsePayload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

export const POST = withRateLimit(handler, async () => {
  const session = await getServerSession();
  return session?.id;
});
