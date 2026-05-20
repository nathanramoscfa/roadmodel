# Phase 3 QA Findings

This document rolls up Phase 3 verification: static checks
`scripts/verify-phase03.sh` (checks 1–43), targeted pytest and
Playwright surfaces, Lighthouse CI on staging, live URL smoke from
Step 7, and provider cap screenshots. Automation mapping follows
`private/phase03-roadmap.md` (V1–V8).

## Per-step verification rollup

### Step 1 — Public ROADMAP.md

- **Static checks:** 1–5 (`ROADMAP.md` at repo root, README
  `## Project status` links `ROADMAP.md`, executable
  `update/sync_public_roadmap.py`, deny-list template,
  `tests.yml` `roadmap-sync` job).
- **Pytest:** `tests/test_sync_public_roadmap.py` (V1.3 under
  `--api` and `--post`).
- **Sync:** `--post` V1.2 runs
  `python update/sync_public_roadmap.py --check` against the
  shipped public roadmap.
- **Manual result:** **PASS** — deny-list linter clean; public
  Phase 3 entry matches private scope without vendor leakage.

### Step 2 — Cloud provisioning

- **Static checks:** 6–12 (`infra/README.md`, `infra/.env.example`,
  gitignored `infra/screenshots/`, executable `scripts/verify-infra.sh`,
  README sections Provider cost ceilings / Environment variables /
  Provisioning sequence).
- **Infra script:** `scripts/verify-infra.sh` (V2.2 under `--post`).
- **Manual result:** **PASS** — staging DNS/TLS green;
  `staging.roadmodel.ai` resolves and serves HTTP/2 200.

### Step 3 — FastAPI service

- **Static checks:** 13–19 (`service/pyproject.toml` roadmodel pin,
  `/healthz` + `/v1/recommend`, `auth.py` + `require_bearer`,
  `RecommendRequest` / `RecommendResponse`, `Dockerfile`,
  `railway.json`, `tests.yml` `service-tests` job).
- **Pytest:** `service/tests/` (V3.2 under `--api` and `--post`).
- **Live health:** V3.3 GET `/healthz` when `ROADMODEL_SERVICE_URL`
  is set (production alias `https://roadmodel-api.vercel.app`).
- **Manual result:** **PASS** with drift notes — live deploy is
  Vercel Fluid Compute (`roadmodel-api`), not Railway; bearer auth
  is retained as a Step 3 artifact but is not wired on the public
  Vercel path post Step 5.5b. See "Pre-ship items".

### Step 4 — Next.js scaffold + marketing home

- **Static checks:** 20–26 (`web/package.json`, layout, home H1
  "Pick the right model for the right job", `robots.txt`
  `Disallow: /`, `web/lib/env.ts`, `home.spec.ts`, `web-build` +
  `web-test` jobs).
- **Playwright:** `web/tests/home.spec.ts` (V4.3 under `--ui` and
  `--post`).
- **Build:** `npm --prefix web run build` (V4.2).
- **Manual result:** **PASS** — marketing home, how-it-works, and
  pricing teaser render on staging and production.

### Step 5 — /recommend page + cheap-model backend

- **Static checks:** 27–31 (recommend page without placeholder,
  `/api/recommend` route with `force_provider`, `recommendOnServer`
  export, `recommend.spec.ts`, `PromptForm` / `RecommendOutput` /
  `FreeTierLabel` components).
- **Playwright:** `npm --prefix web run test -- --grep "/recommend"`
  (V5.2).
- **Manual result:** **PASS** — anonymous POST to
  `https://roadmodel.ai/api/recommend` returns model + platform +
  settings JSON; free-tier badge renders client-side in
  `RecommendOutput`.

### Step 6 — Abuse controls + audit log

- **Static checks:** 32–37 (`ratelimit.ts`, `audit.ts`,
  `withRateLimit.ts`, Supabase migration, `cost-ceilings.md`
  runbook section, `test_audit_log_migration.py`).
- **Pytest:** `tests/test_audit_log_migration.py` (V6.2).
- **Playwright:** `--grep "burst_limit"` and `--grep "daily_limit"`
  (V6.3).
- **Manual result:** **PASS** — production Upstash vars seeded;
  3/day IP limit and burst limiter exercised per
  `docs/phase03-release-runbook.md`.

### Step 7 — Go-live + tag

- **Static checks:** 38–39 (`docs/phase03-release-runbook.md`,
  `git tag v0.3.0-phase-3`).
- **Release URL:** GitHub tag
  <https://github.com/nathanramoscfa/roadmodel/releases/tag/v0.3.0-phase-3>;
  live apex <https://roadmodel.ai>.
- **Live smoke:** V7.2 `dig A roadmodel.ai +short` → `76.76.21.21`;
  V7.3 `curl -sSI https://roadmodel.ai` → HTTP/2 200.
- **Manual result:** **PASS** — apex cut completed 2026-05-20 UTC;
  primary evidence in
  [docs/phase03-release-runbook.md](phase03-release-runbook.md#verification-evidence).

## Lighthouse CI scores

Captured at Step 8 sign-off against
`https://staging.roadmodel.ai` (2026-05-20):

| Category        | Score | Gate                          |
| --------------- | ----- | ----------------------------- |
| Performance     | 0.97  | soft (warn if < 0.8) — PASS   |
| Accessibility   | 1.00  | hard (fail if < 0.9) — PASS   |
| SEO             | 0.63  | soft (warn if < 0.8) — WARN   |

SEO below 0.8 is expected pre-launch: `robots.txt` blocks all
crawlers and `/pricing` is not yet shipped (Phase 5). Accessibility
meets the WCAG 2.1 AA Lighthouse proxy gate.

## Live URL smoke

Cross-reference
[docs/phase03-release-runbook.md — Verification evidence](phase03-release-runbook.md#verification-evidence)
for the authoritative curl + Playwright transcript.

Summary (2026-05-20):

- `dig A roadmodel.ai +short` → `76.76.21.21`
- `curl -sSI https://roadmodel.ai` → `HTTP/2 200`
- Playwright home + `/recommend` form smoke green on production
- Functional `POST /api/recommend` returns HTTP 200 with recommender
  wire schema (warm path ~6–7 s; cold-start latency tracked for Phase 4)

## Provider cap verification

Screenshots committed locally under `infra/screenshots/` (gitignored).
Observed console caps match
[infra/README.md — Provider cost ceilings](../infra/README.md#provider-cost-ceilings):

| Provider  | Monthly cap (USD) | Screenshot path (local)        |
| --------- | ----------------- | ------------------------------ |
| Anthropic | $200              | `infra/screenshots/anthropic-cap.png` |
| OpenAI    | $200              | `infra/screenshots/openai-cap.png`    |
| Google    | $50               | `infra/screenshots/google-cap.png`    |

Alert ladders at 50% / 75% / 90% confirmed on all three consoles.

## Pre-ship items

- **Drift — Step 3 deploy target.** Step 3 originally specified
  Railway (`service/railway.json` + Dockerfile). Step 5.5 migrated
  the FastAPI recommender to Vercel Fluid Compute (`roadmodel-api`).
  `Dockerfile` and `railway.json` remain as reference artifacts for
  static check 17–18; Railway was deleted in Step 5.5b (#89, #91).
- **Drift — bearer auth.** `service/app/auth.py` + `require_bearer`
  satisfy the Step 3 static contract but are not mounted on the
  public Vercel deployment (no shared secret on the browser path).
  Internal service auth is deferred to Phase 4 session validation.
- **Drift — latency SLO.** Public ROADMAP Phase 3 acceptance cites
  "<5 seconds"; warm production calls meet this, but cold-start on
  Vercel Fluid Compute can exceed 20 s. Tracked for Phase 4 warm-up
  cron or runtime migration.
- **SEO Lighthouse soft miss.** Score 0.63 on staging with
  `Disallow: /` — intentional pre-PMF; revisit when `/pricing` ships
  in Phase 5 and robots policy opens for marketing pages.
- **Phase 7 application ledger.** Provider caps in Step 2 strengthen
  but do not replace the console ceilings documented here.
- **Phase 4 audit schema.** `audit_log` gains `user_id`; the rate-limit
  key prefix stays stable so a future per-user limiter can coexist
  with the anonymous IP daily limiter.
