// web/lib/funding-lane.ts
//
// Who pays for a request to a paid route (/api/recommend, /api/roadmap). One
// explicit decision, made before any upstream call, that fails closed: the
// operator's provider keys answer the founder list, the invite list and the
// latency-sweep bypass header, and every other request is refused.
//
// Phase 4.11 widens what a refused visitor can do with lanes of their own:
// Step 2 adds `visitor` (their own provider key, per request) and Step 5 adds
// `keyless` (picks computed in code at $0). Neither reopens the operator lane,
// which stays exactly the three reasons below.

import { timingSafeEqual } from "node:crypto";

import { env } from "./env";
import { isRateLimitExempt, parseExemptIds } from "./ratelimit";

export type OperatorReason = "founder" | "invited" | "bypass";

export type OperatorLane = { lane: "operator"; reason: OperatorReason };

export type FundingLane = OperatorLane | { lane: "refused" };

// Who funded a request, as audit_log.funded_by records it. The two lanes
// Steps 2 and 5 add already have their values here (and in the column's CHECK)
// so they need no migration.
export type FundedBy = "operator" | "visitor" | "keyless";

// Comma-separated Supabase user ids invited onto the operator lane, parsed
// once at module load. Empty by default: nobody is invited.
const INVITED = parseExemptIds(env.RECOMMEND_INVITED_USER_IDS);

export function isInvited(userId: string): boolean {
  return INVITED.has(userId);
}

// The maintainer's scripts (the latency sweep, the daily soak) send
// X-Roadmodel-Bypass. It counts only when ROADMODEL_LATENCY_BYPASS_TOKEN is set
// and the header matches it; the comparison is constant-time so repeated
// probes cannot recover the token by timing.
export function bypassMatches(req: Request): boolean {
  const expected = env.ROADMODEL_LATENCY_BYPASS_TOKEN;
  if (!expected) {
    return false;
  }
  const supplied = req.headers.get("x-roadmodel-bypass");
  if (!supplied) {
    return false;
  }
  const expectedBuf = Buffer.from(expected, "utf8");
  const suppliedBuf = Buffer.from(supplied, "utf8");
  if (expectedBuf.length !== suppliedBuf.length) {
    return false;
  }
  return timingSafeEqual(expectedBuf, suppliedBuf);
}

// Precedence: bypass, then founder, then invited. Anything else, and any
// exception on the way, is refused.
export function decideLane(req: Request, userId: string | undefined): FundingLane {
  try {
    if (bypassMatches(req)) return { lane: "operator", reason: "bypass" };
    if (userId && isRateLimitExempt(userId)) return { lane: "operator", reason: "founder" };
    if (userId && isInvited(userId)) return { lane: "operator", reason: "invited" };
  } catch (err) {
    console.warn("[funding-lane] lane decision failed — refusing", err);
  }
  return { lane: "refused" };
}
