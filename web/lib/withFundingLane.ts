// web/lib/withFundingLane.ts
//
// The gate in front of every paid route. It decides who pays for the request
// (lib/funding-lane.ts) before the handler runs, so a refused request is
// answered 402 without a single upstream call. The daily spend cap and the
// rate limits are the operator lane's: they bound what the operator's keys
// spend, so they apply inside that lane and nowhere else, and a tripped cap
// never stands in for a refusal.
//
// A route that takes the visitor lane (a visitor paying with their own key)
// passes a `visitor` handler. That lane never checks the operator's cap and
// never adds to its spend; it has its own limits per IP+UA, the declined-key
// limit among them.
//
// A route that takes the keyless lane (picks computed in code at $0) passes a
// `keyless` handler, and then every caller runs it: the requests no other lane
// funds, and the operator's own lanes too, since a $0 call has no spend for
// the cap to bound. It has its own limits per IP+UA and never reads the cap.

import { NextResponse } from "next/server";
import { createHash } from "node:crypto";

import { writeAudit } from "./audit";
import { decideLane, type KeylessLane, type OperatorLane, type VisitorLane } from "./funding-lane";
import { ipHashSalt } from "./ip-salt";
import { checkInvitedLimits, checkKeylessLimits, checkVisitorLimits } from "./ratelimit";
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
export type VisitorLaneHandler = (req: Request, lane: VisitorLane) => Promise<Response>;
// A keyless handler is told which lane the request was decided into, so its
// audit row can name the operator's reason when there is one.
export type KeylessLaneHandler = (
  req: Request,
  lane: KeylessLane | OperatorLane,
  userId: string | undefined,
) => Promise<Response>;
type UserIdResolver = (req: Request) => Promise<string | undefined>;

export interface FundingLaneOptions {
  // When this returns false the route answers 404 to every caller, before the
  // session is read or the lane decided (/api/roadmap's ROADMAP_ENABLED).
  enabled?: () => boolean;
  // The route's handler for the visitor lane. Without one the visitor headers
  // are ignored and the request is decided as if it carried none.
  visitor?: VisitorLaneHandler;
  // The route's handler for the keyless lane: with one, every caller runs it
  // and no request is refused.
  keyless?: KeylessLaneHandler;
  // What a refused caller can do instead, sent with the 402 as `options`.
  refusalOptions?: readonly string[];
}

// The IP+UA identity the visitor lane's limits key on.
export function ipUaKey(id: RequestIdentity): string {
  return `${id.ipHash}:${id.uaHash}`;
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

    const lane = decideLane(req, userId, {
      visitor: options.visitor !== undefined,
      keyless: options.keyless !== undefined,
    });

    if (options.keyless && (lane.lane === "keyless" || lane.lane === "operator")) {
      const limit = await checkKeylessLimits(ipUaKey(id));
      if (!limit.allowed) {
        void writeAudit({
          ip_hash: id.ipHash,
          ua_hash: id.uaHash,
          route: id.route,
          outcome: limit.reason === "burst_dropped" ? "burst_dropped" : "rate_limited",
          user_id: userId,
          funded_by: "keyless",
        });
        return NextResponse.json(
          { error: limit.reason, retry_after: limit.retryAfter },
          { status: 429, headers: { "Retry-After": String(limit.retryAfter) } },
        );
      }
      // $0 to everyone: no operator cap, no operator spend.
      return options.keyless(req, lane, userId);
    }

    if (lane.lane === "invalid") {
      // A key that cannot be one is never forwarded.
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "bad_input",
        error_class: lane.error,
        user_id: userId,
        funded_by: "visitor",
      });
      return NextResponse.json({ error: lane.error }, { status: 400 });
    }

    if (lane.lane === "visitor" && options.visitor) {
      const limit = await checkVisitorLimits(ipUaKey(id));
      if (!limit.allowed) {
        void writeAudit({
          ip_hash: id.ipHash,
          ua_hash: id.uaHash,
          route: id.route,
          // The declined-key limit has no outcome of its own in the CHECK:
          // it is a rate limit, told apart by its error_class.
          outcome: limit.reason === "burst_dropped" ? "burst_dropped" : "rate_limited",
          error_class: limit.reason,
          user_id: userId,
          funded_by: "visitor",
        });
        return NextResponse.json(
          { error: limit.reason, retry_after: limit.retryAfter },
          { status: 429, headers: { "Retry-After": String(limit.retryAfter) } },
        );
      }
      // The visitor pays: no operator cap, no operator spend.
      return options.visitor(req, lane);
    }

    if (lane.lane !== "operator") {
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "funding_required",
        user_id: userId,
      });
      return NextResponse.json(
        options.refusalOptions
          ? { error: "funding_required", options: options.refusalOptions }
          : { error: "funding_required" },
        { status: 402 },
      );
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
          outcome: limit.reason === "burst_dropped" ? "burst_dropped" : "rate_limited",
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
