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
};

export default nextConfig;
