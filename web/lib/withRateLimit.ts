// web/lib/withRateLimit.ts
import { NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "node:crypto";
import { checkLimits, isRateLimitExempt } from "./ratelimit";
import { writeAudit } from "./audit";
import { env } from "./env";
import { ipHashSalt } from "./ip-salt";

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

// Phase 4 Step 7 — env-gated bypass for the maintainer-run
// latency sweep. The bypass is checked ONLY when the env var
// is set AND the inbound request carries a matching
// X-Roadmodel-Bypass header. Comparison is constant-time so a
// timing oracle cannot extract the token via repeated probes.
// Removed in PR 7c.
function bypassMatches(req: Request): boolean {
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

type Handler = (req: Request) => Promise<Response>;
type UserIdResolver = (req: Request) => Promise<string | undefined>;

export function withRateLimit(
  handler: Handler,
  resolveUserId?: UserIdResolver,
): Handler {
  return async (req: Request): Promise<Response> => {
    const id = identifyRequest(req);
    const userId = resolveUserId ? await resolveUserId(req) : undefined;

    if (bypassMatches(req)) {
      // Step 7 bypass — record the bypass so the latency sweep
      // shows up distinctly in audit_log (it would otherwise be
      // indistinguishable from organic traffic during analysis).
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: "bypassed_rate_limit",
        user_id: userId,
      });
      return handler(req);
    }

    // Founder/dev exemption: a signed-in user on the exempt list skips the
    // IP-pool rate limit entirely. This is the BROWSER-usable counterpart to the
    // X-Roadmodel-Bypass header above (which scripts can set but a browser
    // can't). The handler still runs and writes its normal audit row, so the
    // request is recorded as usual — no separate audit needed. Default-closed:
    // when RECOMMEND_RATELIMIT_EXEMPT_USER_IDS is unset, nobody is exempt.
    if (userId && isRateLimitExempt(userId)) {
      return handler(req);
    }

    const key = `${id.ipHash}:${id.uaHash}`;
    const limit = await checkLimits(key);

    if (!limit.allowed) {
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: limit.reason!,
        user_id: userId,
      });
      return NextResponse.json(
        { error: limit.reason, retry_after: limit.retryAfter },
        {
          status: 429,
          headers: { "Retry-After": String(limit.retryAfter) },
        },
      );
    }

    return handler(req);
  };
}
