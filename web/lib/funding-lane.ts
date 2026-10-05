// web/lib/funding-lane.ts
//
// Who pays for a request to a paid route (/api/recommend, /api/roadmap). One
// explicit decision, made before any upstream call, that fails closed: the
// operator's provider keys answer the founder list, the invite list and the
// latency-sweep bypass header, and every other request is refused.
//
// Phase 4.11 widens what a refused visitor can do with lanes of their own:
// `visitor` (their own provider key, per request: below) and `keyless` (picks
// computed in code at $0, on /api/recommend/keyless only: the outcome there
// for every request the operator and visitor lanes leave). Neither reopens the
// operator lane, which stays exactly the three reasons below.
//
// The visitor lane. A request that carries X-Roadmodel-Visitor-Key and
// X-Roadmodel-Visitor-Provider pays with that key, whoever sends it: an
// invited member who attaches a key chose to pay. The key is checked for shape
// here, travels on to the service ONLY as the same header (lib/api.ts
// visitorRequestHeaders), and is never copied into the lane, a log, the audit
// row or a response. A malformed key is answered 400 without forwarding.

import { timingSafeEqual } from "node:crypto";

import { env } from "./env";
import { isRateLimitExempt, parseExemptIds } from "./ratelimit";
import {
  isVisitorProvider,
  VISITOR_KEY_HEADER,
  VISITOR_PROVIDER_HEADER,
  visitorKeyLooksValid,
  type VisitorProvider,
} from "./visitor-key";

export {
  VISITOR_KEY_HEADER,
  VISITOR_PROVIDER_HEADER,
  VISITOR_PROVIDERS,
  visitorKeyLooksValid,
  type VisitorProvider,
} from "./visitor-key";

export type OperatorReason = "founder" | "invited" | "bypass";

export type OperatorLane = { lane: "operator"; reason: OperatorReason };

// The provider is the only thing about the key the lane carries.
export type VisitorLane = { lane: "visitor"; provider: VisitorProvider };

// Picks computed in code from the bundled catalog: no engine, no provider key,
// $0 to everyone.
export type KeylessLane = { lane: "keyless" };

export type FundingLane =
  | OperatorLane
  | VisitorLane
  | KeylessLane
  | { lane: "refused" }
  // The request tried to pay with a key that cannot be one.
  | { lane: "invalid"; error: "visitor_key_malformed" };

// The visitor lane, a malformed attempt at it, or null when the request
// carries neither visitor header. Either header alone is an attempt.
function visitorLane(req: Request): VisitorLane | { lane: "invalid"; error: "visitor_key_malformed" } | null {
  const key = req.headers.get(VISITOR_KEY_HEADER);
  const provider = req.headers.get(VISITOR_PROVIDER_HEADER);
  if (key === null && provider === null) return null;
  const p = provider?.trim().toLowerCase();
  if (isVisitorProvider(p) && key !== null && visitorKeyLooksValid(p, key.trim())) {
    return { lane: "visitor", provider: p };
  }
  return { lane: "invalid", error: "visitor_key_malformed" };
}

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

// Precedence: a visitor key (on routes that take one), then bypass, founder,
// invited. Anything else, and any exception on the way, is refused, or, on a
// route that takes the keyless lane, keyless: that lane spends nothing, so it
// is the safe answer to a failed decision too.
export function decideLane(
  req: Request,
  userId: string | undefined,
  { visitor = false, keyless = false }: { visitor?: boolean; keyless?: boolean } = {},
): FundingLane {
  try {
    if (visitor) {
      const v = visitorLane(req);
      if (v) return v;
    }
    if (bypassMatches(req)) return { lane: "operator", reason: "bypass" };
    if (userId && isRateLimitExempt(userId)) return { lane: "operator", reason: "founder" };
    if (userId && isInvited(userId)) return { lane: "operator", reason: "invited" };
  } catch (err) {
    console.warn("[funding-lane] lane decision failed — refusing", err);
  }
  return keyless ? { lane: "keyless" } : { lane: "refused" };
}
