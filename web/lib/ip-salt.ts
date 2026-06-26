// web/lib/ip-salt.ts
//
// Single source for the per-IP/UA hashing salt used by the recommend rate
// limiter (lib/withRateLimit.ts) and the gate brute-force lockout
// (lib/gateGuard.ts).
//
// The salt is seeded in Vercel (Production + Preview scopes). In PRODUCTION a
// missing salt is a misconfiguration we must NOT paper over with the public
// default below: every client would then hash under a salt that lives in this
// open-source repo, which (a) lets anyone pre-compute the hash of a target IP
// and correlate audit_log rows — defeating the IP anonymization — and (b)
// makes the rate-limit / lockout keys predictable. So we fail CLOSED in
// production (throw) rather than silently degrade.
//
// Everywhere else (local dev, CI, Playwright, Preview) we keep a clearly
// labelled constant default so the code path runs without a seeded salt.
// Gated on VERCEL_ENV === "production" specifically (NOT VERCEL=1, which is set
// on every Vercel runtime incl. preview/dev).

const NON_PROD_DEFAULT_SALT = "default-salt-rotate-quarterly";

export function ipHashSalt(): string {
  const salt = process.env.ROADMODEL_IP_SALT;
  if (salt) {
    return salt;
  }
  if (process.env.VERCEL_ENV === "production") {
    throw new Error(
      "ROADMODEL_IP_SALT is required in production — refusing the public " +
        "fallback salt, which would de-anonymize the audit log and make the " +
        "rate-limit/lockout keys predictable. Seed it on the roadmodel-web " +
        'Production scope. See infra/README.md "Environment variables".',
    );
  }
  return NON_PROD_DEFAULT_SALT;
}
