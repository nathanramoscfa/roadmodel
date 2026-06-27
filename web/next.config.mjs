// web/next.config.mjs
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The roadmodel repo root sits one level above web/, so the
  // Next.js file tracer needs to be told it can look upward when
  // bundling serverless functions. Without this, the /api/roadmap
  // route's reads of docs/templates/*.md would fail at runtime on
  // Vercel because the file tracer treats any path outside web/
  // as out-of-scope by default.
  outputFileTracingRoot: new URL("..", import.meta.url).pathname,
  // Explicit globs the tracer must include alongside the auto-
  // detected dependency graph. The /api/roadmap Route Handler
  // reads both roadmap templates at request time (see
  // web/lib/roadmap-prompts.ts); listing them here pins the
  // contract so a future refactor that hides the read behind a
  // helper does not silently break bundling.
  outputFileTracingIncludes: {
    "/api/roadmap": [
      "../docs/templates/project-roadmap-template.md",
      "../docs/templates/phase-roadmap-template.md",
    ],
  },
  // Security response headers (audit H3). Applied to every route. These are
  // the framework-functionality-safe set:
  //   - HSTS: force HTTPS for 2y incl. subdomains. No `preload` on purpose —
  //     preload-list submission is a separate, hard-to-reverse commitment we
  //     don't want to make pre-launch.
  //   - X-Frame-Options: DENY — clickjacking protection (the app is never
  //     framed; the gate + auth flows especially must not be).
  //   - X-Content-Type-Options: nosniff — block MIME sniffing.
  //   - Referrer-Policy: don't leak full URLs (which can carry the gate
  //     `next=` param / ids) to cross-origin destinations.
  //   - Permissions-Policy: deny powerful features the app never uses.
  // The Content-Security-Policy is set per-request in web/middleware.ts (it
  // needs a per-request nonce so Next's inline bootstrap/streaming scripts +
  // our inline theme script execute under a strict, no-'unsafe-inline' policy)
  // — it can't live here in the static header set. Defense-in-depth; no XSS
  // sink today (all LLM/user output renders through JSX auto-escaping).
  async headers() {
    const securityHeaders = [
      {
        key: "Strict-Transport-Security",
        value: "max-age=63072000; includeSubDomains",
      },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      {
        key: "Permissions-Policy",
        value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
      },
    ];
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
