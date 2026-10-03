// web/lib/withFundingLane.ts
//
// The gate in front of every paid route. It decides who pays for the request
// (lib/funding-lane.ts) before the handler runs, so a refused request is
// answered 402 without a single upstream call. The daily spend cap and the
// rate limits are the operator lane's: they bound what the operator's keys
// spend, so they apply inside that lane and nowhere else, and a tripped cap
// never stands in for a refusal.

import { NextResponse } from "next/server";
import { createHash } from "node:crypto";

import { writeAudit } from "./audit";
import { decideLane, type OperatorLane } from "./funding-lane";
import { ipHashSalt } from "./ip-salt";
import { checkInvitedLimits } from "./ratelimit";
import { dailyCostCapTripped } from "./spend-guard";

function hash(value: string): string {
  // ipHashSalt() throws in production if ROADMODEL_IP_SALT is unset (fail
  // closed) and returns a labelled default elsewhere — see lib/ip-salt.ts.
  return createHash("sha256")
    .update(`${value}|${ipHashSalt()}`)
    .digest("hex");
}

export interface RequestIdentity {
  ipHash: string;
  uaHash: string;
  route: string;
}

export function identifyRequest(req: Request): RequestIdentity {
  // Trusted client IP. On Vercel `x-forwarded-for` is OVERWRITTEN by the
  // platform with the real client IP and client-supplied values are NOT
  // forwarded — Vercel does this specifically to prevent IP spoofing
  // (https://vercel.com/docs/headers/request-headers#x-forwarded-for). So
  // the header is effectively a single trusted IP here and `[0]` is the
  // genuine client. Do NOT "harden" this to take the LAST entry: that would
  // be correct on hosts that APPEND, but on Vercel it changes nothing while
  // making the code read as if a spoofable prefix exists. If this app is ever
  // deployed off Vercel (no spoof-proof proxy), revisit — XFF would then be
  // client-controlled and this keying would need a trusted-proxy IP instead.
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  const ua = req.headers.get("user-agent") ?? "unknown";
  return {
    ipHash: hash(ip),
    uaHash: hash(ua),
    route: new URL(req.url).pathname,
  };
}

export type LaneHandler = (req: Request, lane: OperatorLane) => Promise<Response>;
type UserIdResolver = (req: Request) => Promise<string | undefined>;

export interface FundingLaneOptions {
  // When this returns false the route answers 404 to every caller, before the
  // session is read or the lane decided (/api/roadmap's ROADMAP_ENABLED).
  enabled?: () => boolean;
}

export function withFundingLane(
  handler: LaneHandler,
  resolveUserId: UserIdResolver,
  options: FundingLaneOptions = {},
): (req: Request) => Promise<Response> {
  return async (req: Request): Promise<Response> => {
    if (options.enabled && !options.enabled()) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }

    const id = identifyRequest(req);
    let userId: string | undefined;
    try {
      userId = await resolveUserId(req);
    } catch {
      // An unreadable session is a signed-out caller, which the lane refuses.
      userId = undefined;
    }

    const lane = decideLane(req, userId);
    if (lane.lane !== "operator") {
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "funding_required",
        user_id: userId,
      });
      return NextResponse.json({ error: "funding_required" }, { status: 402 });
    }

    // Daily spend circuit breaker (real-time complement to the GCP budget
    // kill-switch): once the UTC day's operator spend crosses
    // ROADMODEL_DAILY_COST_CAP_USD, the operator lane stops until midnight —
    // the founder and the bypass header included. Fails open on a ledger error.
    const cap = await dailyCostCapTripped();
    if (cap.tripped) {
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "daily_cost_cap",
        user_id: userId,
        funded_by: "operator",
      });
      return NextResponse.json(
        { error: "daily_cost_cap", retry_after: cap.retryAfter },
        {
          status: 503,
          headers: { "Retry-After": String(cap.retryAfter ?? 3600) },
        },
      );
    }

    if (lane.reason === "bypass") {
      // Record the bypass so the latency sweep and the soak show up distinctly
      // in audit_log (they would otherwise read as organic traffic).
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "bypassed_rate_limit",
        user_id: userId,
        funded_by: "operator",
      });
      return handler(req, lane);
    }

    if (lane.reason === "invited" && userId) {
      const limit = await checkInvitedLimits(userId);
      if (!limit.allowed) {
        void writeAudit({
          ip_hash: id.ipHash,
          ua_hash: id.uaHash,
          route: id.route,
          outcome: limit.reason!,
          user_id: userId,
          funded_by: "operator",
        });
        return NextResponse.json(
          { error: limit.reason, retry_after: limit.retryAfter },
          {
            status: 429,
            headers: { "Retry-After": String(limit.retryAfter) },
          },
        );
      }
    }

    // The founder runs unlimited; the handler writes the request's audit row.
    return handler(req, lane);
  };
}
