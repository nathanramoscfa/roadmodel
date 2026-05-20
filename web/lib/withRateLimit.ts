// web/lib/withRateLimit.ts
import { NextResponse } from "next/server";
import { createHash } from "node:crypto";
import { checkLimits } from "./ratelimit";
import { writeAudit } from "./audit";

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

type Handler = (req: Request) => Promise<Response>;

export function withRateLimit(handler: Handler): Handler {
  return async (req: Request): Promise<Response> => {
    const id = identifyRequest(req);
    const key = `${id.ipHash}:${id.uaHash}`;
    const limit = await checkLimits(key);

    if (!limit.allowed) {
      void writeAudit({
        ip_hash: id.ipHash,
        ua_hash: id.uaHash,
        route: id.route,
        outcome: limit.reason!,
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
