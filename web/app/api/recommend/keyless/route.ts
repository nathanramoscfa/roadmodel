// web/app/api/recommend/keyless/route.ts
//
// Quick pick: three picks for a task the visitor classified themselves (task
// type, difficulty, a new kind of problem or not, budget priority), computed
// by the service's scoring core (POST /v1/score, service/app/score.py) from
// published benchmarks and prices. No engine runs and no provider key is read,
// so the call is $0 to everyone and runs on the keyless lane
// (lib/withFundingLane.ts): its own limits per IP+UA, never the operator's cap
// or spend counter.
//
// The service is reached at /v1/score and nowhere else, whatever the body
// says. The body's four task fields are checked against the service's enums
// and merged with the viewer's saved funding (none when signed out); only
// those fields, filtered to the shape /v1/score accepts, are forwarded.

import { NextResponse } from "next/server";

import { recommenderRequestHeaders } from "@/lib/api";
import { writeAudit } from "@/lib/audit";
import { getServerSession } from "@/lib/auth";
import { getModelAvailability } from "@/lib/availability";
import { isKeylessResponse, parseKeylessTask, scoreList } from "@/lib/keyless";
import { DEFAULT_PROFILE, getProfile } from "@/lib/profile";
import { scoreUrl } from "@/lib/service-url";
import { identifyRequest, withFundingLane, type KeylessLaneHandler } from "@/lib/withFundingLane";

const keylessHandler: KeylessLaneHandler = async (req, _lane, userId) => {
  const id = identifyRequest(req);
  const audit = (entry: Partial<Parameters<typeof writeAudit>[0]> & Pick<Parameters<typeof writeAudit>[0], "outcome">) =>
    void writeAudit({
      ip_hash: id.ipHash,
      ua_hash: id.uaHash,
      route: id.route,
      user_id: userId,
      funded_by: "keyless",
      ...entry,
    });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    body = null;
  }
  const task = parseKeylessTask(body);
  if (!task) {
    audit({ outcome: "bad_input", error_class: "invalid_keyless_task" });
    return NextResponse.json({ error: "bad_input" }, { status: 400 });
  }

  // The viewer's saved funding, so the picks are drawn over what they can run.
  // A profile that cannot be read is the anonymous answer: the whole catalog.
  const profile = userId ? await getProfile(userId).catch(() => null) : null;
  const { ids: unavailable, authoritative } = await getModelAvailability();
  const payload = {
    category: task.category,
    complexity: task.complexity,
    novel: task.novel,
    budget_priority: task.budget_priority ?? profile?.budget_priority ?? DEFAULT_PROFILE.budget_priority,
    subscriptions: scoreList(profile?.subscriptions),
    api_providers: scoreList(profile?.api_providers),
    ...(profile?.consumption_headroom ? { consumption_headroom: profile.consumption_headroom } : {}),
    allowed_jurisdictions: scoreList(profile?.allowed_jurisdictions),
    unavailable_models: scoreList(unavailable),
    availability_authoritative: authoritative,
  };

  let upstream: Response;
  try {
    upstream = await fetch(scoreUrl(), {
      method: "POST",
      headers: recommenderRequestHeaders(),
      body: JSON.stringify(payload),
    });
  } catch (err) {
    audit({ outcome: "recommender_error", error_class: err instanceof Error ? err.name : "fetch_failed" });
    return NextResponse.json({ error: "recommender_unavailable" }, { status: 502 });
  }
  const text = await upstream.text();
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = null;
  }
  if (!upstream.ok) {
    // 422 no_frontier: the viewer's filters leave no measured model.
    const noFrontier = upstream.status === 422 && (parsed as { detail?: unknown } | null)?.detail === "no_frontier";
    audit({ outcome: "recommender_error", error_class: noFrontier ? "no_frontier" : `upstream_${upstream.status}` });
    return noFrontier
      ? NextResponse.json({ error: "no_frontier" }, { status: 422 })
      : NextResponse.json({ error: "recommender_unavailable" }, { status: 502 });
  }
  if (!isKeylessResponse(parsed)) {
    audit({ outcome: "recommender_error", error_class: "malformed_score_response" });
    return NextResponse.json({ error: "recommender_unavailable" }, { status: 502 });
  }

  const quality = parsed.rungs[0];
  audit({
    outcome: "ok",
    provider: quality.platform_name,
    model: quality.model_name,
    // The ledger column, explicitly zero: nobody paid for this answer.
    cost_usd: 0,
  });
  return NextResponse.json({ ...parsed, cost_usd: 0 });
};

export const POST = withFundingLane(
  // Unreached: with a keyless handler every caller runs it.
  (req, lane) => keylessHandler(req, lane, undefined),
  async () => {
    const session = await getServerSession();
    return session?.id;
  },
  { keyless: keylessHandler },
);
