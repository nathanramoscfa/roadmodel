// web/app/api/recommend/route.ts
import { NextResponse } from "next/server";
import { writeAudit, type AuditOutcome } from "@/lib/audit";
import { identifyRequest, withRateLimit } from "@/lib/withRateLimit";

const RECOMMENDER_URL = "https://roadmodel-api.vercel.app/v1/recommend";

interface RecommenderPayload {
  model?: string;
  platform?: string;
  session_cost_estimate?: { total_usd?: number };
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
    typeof (body as { task_description?: unknown }).task_description !== "string"
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
  const upstreamPayload = {
    task_description: taskDescription,
    context: {
      ...incomingContext,
      force_provider: "google-gemini-2.5-flash",
    },
  };

  let upstream: Response;
  try {
    upstream = await fetch(RECOMMENDER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(upstreamPayload),
    });
  } catch (err) {
    auditFor(req, "recommender_error", {
      error_class: err instanceof Error ? err.name : "fetch_failed",
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
    });
    return new NextResponse(upstreamBody, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  auditFor(req, "ok", {
    provider: parsed?.platform,
    model: parsed?.model,
    cost_usd: parsed?.session_cost_estimate?.total_usd,
  });

  return new NextResponse(upstreamBody, {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

export const POST = withRateLimit(handler);
