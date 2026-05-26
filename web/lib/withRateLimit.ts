// web/lib/withRateLimit.ts
import { NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "node:crypto";
import { checkLimits } from "./ratelimit";
import { writeAudit } from "./audit";
import { env } from "./env";

const DAILY_SALT =
  process.env.ROADMODEL_IP_SALT ?? "default-salt-rotate-quarterly";

function hash(value: string): string {
  return createHash("sha256")
    .update(`${value}|${DAILY_SALT}`)
    .digest("hex");
}

export interface RequestIdentity {
  ipHash: string;
  uaHash: string;
  route: string;
}

export function identifyRequest(req: Request): RequestIdentity {
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
