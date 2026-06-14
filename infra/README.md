<!-- infra/README.md -->
# Infrastructure runbook

> **Audience:** the maintainer (and any future maintainer with full
> repo access). This file is the single source of truth for the
> managed-service projects roadmodel runs on from Phase 3 onward:
> their IDs, dashboard URLs, env var schema, DNS records, TLS
> posture, provider-side cost ceilings, uptime monitors, the
> seven-step re-provisioning runbook, and the disaster-recovery
> floor those caps establish for Phase 7. Vendor names are spelled
> out verbatim here because this file is **private to the repo's
> trusted operators** — the public-facing `ROADMAP.md` at the repo
> root describes the same stack in provider-agnostic terms and is
> lint-protected by [tests.yml](../.github/workflows/tests.yml)'s
> `roadmap-sync` job against vendor leakage.

**Status:** Schema, decisions, env vars, and cost ceilings are
locked in by this commit. The project IDs, dashboard slugs, and
UptimeRobot monitor ID get filled in by the maintainer immediately
after walking the [Provisioning sequence](#provisioning-sequence)
in the three vendor consoles; until those values land here, the
fields read `TBD (fill in after step N)`. The post-provisioning
edit is committed as a follow-up `docs(infra)` PR, not amended
into the Step 2 squash.

---

## Cloud projects

The three vendors Phase 3 stands up. Stripe (Phase 5) and the
Cloudflare / secrets-store / observability stack (Phase 7+) are
deliberately out of scope here — they're additive layers on top of
this baseline.

| Project           | Vendor   | Project ID                     | Dashboard URL                                                    | Staging URL                              | Production URL          | Provisioned    |
| ----------------- | -------- | ------------------------------ | ---------------------------------------------------------------- | ---------------------------------------- | ----------------------- | -------------- |
| `roadmodel-web`   | Vercel   | `prj_1emPjG8EamGB5G942ipNjjeqh8NX` (team `team_5uU81P0Gl4i22rBjMSwDRsLR`, slug `roadmodel`) — root `web/`, previews live | `https://vercel.com/roadmodel/roadmodel-web` | `https://staging.roadmodel.ai` — Up 2026-05-19 | `https://roadmodel.ai` (Step 7 target — pending apex DNS verify) | 2026-05-17 |
| `roadmodel-api`   | Vercel   | `prj_GLyJj2J4Ch7Yr6TruBr6aD8jeD5E` (team `team_5uU81P0Gl4i22rBjMSwDRsLR`, slug `roadmodel`) — root `service/`, Python 3.12 / Fluid Compute, framework `fastapi` (auto-detected from `service/pyproject.toml`) | `https://vercel.com/roadmodel/roadmodel-api` | `https://roadmodel-api.vercel.app/v1/recommend` (production alias; called server-side by the Next.js `/api/recommend` route handler — see [Step 6 resume checklist](#resume-checklist-step-6--phase-3-step-6)) | TBD (cut in Step 7) | 2026-05-19 (Step 5.5a) |
| `roadmodel-data`  | Supabase | `nbxzpqnmafcayeqnfvcv` (org `mkvjpvgvuhhzkzfyhvsp`, region `us-east-1`) | `https://supabase.com/dashboard/project/nbxzpqnmafcayeqnfvcv` | Same dashboard, `staging` schema | Same dashboard, `prod` | 2026-05-17 |

> **Historical — Railway (retired 2026-05-19, Step 5.5b).** The
> FastAPI recommender originally ran on Railway as project
> `roadmodel-service` (id `09b49af8-35b0-4cbd-8c6b-803960ebfe6a`).
> Phase 3 Step 5.5 consolidated it onto Vercel after a multi-hour
> Railway control-plane outage on 2026-05-19 coincided with Step 5
> close-out's [issue #86](https://github.com/nathanramoscfa/roadmodel/issues/86)
> token-alignment surfacing the [project_railway_setup_gaps] memory.
> Driver triad: outage signal + Vercel's 2026 first-class
> Python/FastAPI support + eliminating the
> `ROADMODEL_INTERNAL_TOKEN` / `ROADMODEL_SERVICE_URL` shared-secret
> boundary. The Railway-era files (`service/Dockerfile` and
> `service/railway.json`) were removed from the repo in Step 5.5b;
> the Railway project itself was deleted via dashboard on
> 2026-05-20 once the post-Step-5.5b outage subsided (confirmed
> via HTTP 404 on the previous `*.up.railway.app` hostnames). The
> [project_railway_setup_gaps] memory is **historical** as of this
> step — no future provisioning step targets Railway.

Vendor rationale (frozen by Step 2; revisit only on a documented
incident):

- **Vercel for the Next.js 15 web tier.** Auto-issued
  Let's Encrypt TLS, preview deployments per PR, edge-cached SSR
  out of the box, and the App-Router toolchain is first-party
  there. Cost at pilot scale (`Pro` plan) is the bottom of the
  range projected in `private/ROADMAP.md` §5.

  > **Status (Phase 3 Step 4 — closed 2026-05-19):** The Next.js
  > scaffold lives under `web/`, root-directory wiring in
  > [Vercel project configuration](#vercel-project-configuration),
  > `staging.roadmodel.ai` serves the marketing home (2xx, public).
  > See the Step 4 resume checklist there for closure log.
- **Vercel for the Python FastAPI recommender service** (since
  Phase 3 Step 5.5, 2026-05-19). The `roadmodel-api` project runs
  the same `app.main:app` ASGI handler on Fluid Compute, with
  deploy-on-push and the same Let's Encrypt TLS posture as the web
  tier. Replaced Railway after Railway's 2026-05-19 control-plane
  outage coincided with [issue #86](https://github.com/nathanramoscfa/roadmodel/issues/86)'s
  `ROADMODEL_INTERNAL_TOKEN` drift surfacing the
  [project_railway_setup_gaps] surface. Consolidating onto Vercel
  eliminates the cross-vendor shared-secret boundary entirely —
  `staging.roadmodel.ai/api/recommend` is a Vercel rewrite to
  `roadmodel-api.vercel.app/v1/recommend`; no bearer is sent because
  no bearer is enforced server-side (Step 6 ships rate limiting +
  Origin checks as the replacement defense).
- **Supabase Pro for Postgres + Auth + Storage.** Pro tier — not
  Free — because Phase 4's audit log needs the row-count headroom
  and Phase 7's disaster-recovery posture relies on Supabase Pro's
  daily backups. Self-hosted Postgres was considered and rejected:
  Auth + Storage would have to be glued back together separately,
  and the maintainer's bandwidth doesn't cover ops at this stage.

## Vercel project configuration

Captured from the `roadmodel-web` project after Phase 3 Step 4
lands the Next.js scaffold. Reconcile against the Vercel dashboard
(Settings) if any value drifts.

| Setting              | Value                                                                 |
| -------------------- | --------------------------------------------------------------------- |
| Project name         | `roadmodel-web`                                                       |
| Root directory       | `web` (Vercel runs `npm install` / `npm run build` inside `web/`)   |
| Framework preset     | Next.js (auto-detected from `web/package.json`)                       |
| Production branch    | `main` (production deploys on push to `main`)                         |
| Preview deployments  | Enabled — Vercel bot posts preview URLs on every PR                   |
| Custom environments  | `staging` (id `env_nlbUWVIOslQOHcmNUftnMvlqeSJj`, type `preview`, `branchMatcher: equals "staging"`) → serves `staging.roadmodel.ai` |
| Deployment Protection| **Disabled** (was `all_except_custom_domains` until 2026-05-19; that setting only exempts *production* custom domains, so `staging.roadmodel.ai` was being SSO-gated. `robots.txt Disallow: /` already prevents indexing pre-launch.) |
| Build command        | `npm run build` (default; runs in `web/`)                             |
| Output directory     | `.next` (Next.js default; relative to `web/`)                         |
| Install command      | `npm install` (default; runs in `web/`)                               |

**Environments.** As of 2026-05-19 (Step 5.5b cutover), `roadmodel-web`
is wired across three env scopes:

- **`preview`** (built-in; per-PR previews): `NEXT_PUBLIC_SITE_URL`,
  `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- **`staging`** (custom env, mapped to `staging.roadmodel.ai`):
  same three vars set.
- **`production`** (built-in, tracks `main`): `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SITE_URL`
  (`https://roadmodel.ai`, seeded Step 7 2026-05-20).
- `ROADMODEL_SERVICE_URL` and `ROADMODEL_INTERNAL_TOKEN` were
  **removed entirely in Step 5.5b** — the rewrite from
  `staging.roadmodel.ai/api/recommend` to
  `roadmodel-api.vercel.app/v1/recommend` is configured in
  [web/vercel.json](../web/vercel.json) and needs no shared
  secret. All five stale entries (3× `ROADMODEL_INTERNAL_TOKEN` +
  2× `ROADMODEL_SERVICE_URL` across the preview / staging /
  production scopes on `roadmodel-web`, plus 1×
  `ROADMODEL_INTERNAL_TOKEN` on `roadmodel-api`) were deleted via
  the Vercel API during Step 5.5b close-out (2026-05-19).
- `UPSTASH_REDIS_URL` and `UPSTASH_REDIS_TOKEN` are seeded on
  `roadmodel-web` across **all four scopes** — Production, Preview,
  Development, and the `staging` Custom Environment — as of Step 7
  close-out (2026-05-20) via the Vercel Marketplace Upstash for
  Redis integration (which injects the legacy `KV_REST_API_URL` /
  `KV_REST_API_TOKEN` pair) plus aliases under the names `env.ts`
  and `ratelimit.ts` actually read. Production + Development +
  staging were seeded via `vercel env add`; default `Preview` was
  seeded via the Vercel dashboard because the CLI bug in both
  54.1.0 and 54.2.0 blocks `vercel env add NAME preview --value X
  --yes --force` without a branch. With all four scopes populated,
  a future small PR can flip `env.ts` from `.optional()` to
  `.min(1)` for these vars. The `roadmodel-api` Vercel project
  does **not** need either var — the FastAPI side never invokes
  the rate limiter (browser traffic terminates at the Next.js
  handler).
- `ROADMODEL_IP_SALT` is the daily-rotation salt the Next.js
  rate limiter hashes the client IP + UA with before keying
  Upstash. Seeded alongside the Upstash pair across all four
  scopes (Production, Preview, Development, `staging` Custom Env)
  at Step 7 close-out (`openssl rand -hex 32` value, stored in
  Google Password Manager as `roadmodel ROADMODEL_IP_SALT`).
  Rotation cadence is **quarterly** per the Phase 7
  secrets-rotation policy. Defaults to a placeholder in
  `web/lib/withRateLimit.ts` so local + CI builds work without
  override, but production builds without the override silently
  bucket every IP under the same key, so the var **must** be
  set in every Vercel scope serving real traffic.

**`roadmodel-api` environments.** As of 2026-05-19 (post Step 5.5b
close-out), `roadmodel-api` carries **only the three AI provider
keys** — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` —
on the built-in `production` + `preview` scopes. **No `staging`
custom environment exists on this project**; the
`staging.roadmodel.ai/api/recommend` rewrite hits
`roadmodel-api.vercel.app` (the production alias) regardless of
which web-tier scope the request originated from. This works for
Phase 3 because the FastAPI is environment-agnostic, but Step 7
should re-evaluate when the production apex DNS cuts (likely by
adding a `staging` custom env on `roadmodel-api` mirroring
`roadmodel-web`'s setup, then updating
[web/vercel.json](../web/vercel.json) to route per-env). Gaps the
Phase 3 close-out documentation got ahead of reality on:

- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are **not yet set
  on `roadmodel-api`** — service/ doesn't read them today (no
  `SUPABASE_*` references in `service/app/`). Step 6 wires them
  when the rate limiter + audit log land on the FastAPI side.
- Likewise `UPSTASH_REDIS_URL` / `UPSTASH_REDIS_TOKEN` are
  Step-6-or-later additions on this project.
- The `ROADMODEL_USER_CONTEXT` entry seeded during Step 5.5a's
  Dockerfile-era provisioning (`/var/task/user-context.md`) was
  also deleted in Step 5.5b close-out — `service/app/recommend.py`
  bootstraps the user-context template to `/tmp` directly via
  `_bootstrap_user_context()` and passes the path explicitly to
  `load_config()`, so the env var was already inert.

**Resume checklist (Step 4) — closed 2026-05-19.**

- [x] GitHub-connected preview deployments re-enabled (they were
  paused 2026-05-19 to avoid doomed Python-detection builds — fixed
  by setting Root Directory to `web/`).
- [x] Green preview on the Step 4 PR — PR #76 deploy
  `dpl_8XxotwPuwcTegDZPG26pFcfSP9NW` succeeded; promoted to the
  `staging` custom env via `vercel redeploy --target staging`.
- [x] `staging.roadmodel.ai` returns 2xx — first 200 at 16:24 UTC
  2026-05-19 after disabling SSO protection.
- [x] [UptimeRobot monitor 803092893](#uptimerobot-monitors) resumed.

**Resume checklist (Step 5) — closed 2026-05-19 with one
deferred item.** Step 5 shipped via PR #84 (`/recommend` page +
`/api/recommend` Route Handler + service `force_provider` support)
and PR #85 (production-build hotfix relaxing
`ROADMODEL_SERVICE_URL` / `ROADMODEL_INTERNAL_TOKEN` to `.optional()`
in [web/lib/env.ts](../web/lib/env.ts) so production builds don't
fail at "Collecting page data" while the production Railway
service is deferred to Step 7). The two deferred items below are
**superseded by Step 5.5b** — see the [Step 5.5 resume
checklist](#resume-checklist-step-55--closed-2026-05-19) below.

- [x] Production deploy green on `main` after the PR #85 hotfix —
  deployment `roadmodel-n9clqlarq` Ready in 26s; the post-merge
  build of `17b5d62` had errored on the unset
  `ROADMODEL_SERVICE_URL` and `roadmodel-web-roadmodel.vercel.app`
  was serving the pre-Step-5 build until the hotfix landed.
- [x] Staging promoted to the Step 5 build via
  `vercel redeploy roadmodel-n9clqlarq-roadmodel.vercel.app
  --target staging --scope roadmodel` → deployment
  `roadmodel-608iaojr2`, target=`staging`, Ready in 47s.
- [x] `staging.roadmodel.ai/recommend` returns 200 with the new
  two-column layout served by the Step 5 deployment.
- [x] Live `POST /api/recommend` returns a Haiku 4.5
  recommendation. **Superseded by Step 5.5b** — instead of fixing
  the Vercel↔Railway token alignment that broke at Step 5 close,
  Step 5.5 retired the boundary entirely by moving FastAPI onto
  Vercel. Live-POST evidence captured below in the [Step 5.5
  resume checklist](#resume-checklist-step-55--closed-2026-05-19).
- [x] Browser submit from `/recommend` populates the output column
  end-to-end. **Superseded by Step 5.5b** — same supersession path.

**Resume checklist (Step 5.5) — closed 2026-05-19.** Phase 3
Step 5.5 consolidated the FastAPI recommender onto Vercel in two
PRs: Step 5.5a (PR #88) added a new `roadmodel-api` Vercel project
deploying `service/` on Fluid Compute alongside Railway; Step 5.5b
(this PR) cut `staging.roadmodel.ai/api/recommend` over via a
Vercel rewrite, deleted the Next.js proxy, dropped the
`ROADMODEL_INTERNAL_TOKEN` shared secret, and tore Railway down.
The Step 5 deferred items above resolve here.

- [x] Step 5.5a: `roadmodel-api` Vercel project (id
  `prj_GLyJj2J4Ch7Yr6TruBr6aD8jeD5E`) created with Root Directory
  `service/`, framework `fastapi`, Python 3.12 / Fluid Compute.
  `[tool.vercel] entrypoint = "app.main:app"` in
  [service/pyproject.toml](../service/pyproject.toml).
- [x] Step 5.5a: `roadmodel-api.vercel.app` returns 200 on
  `POST /v1/recommend` with the `ROADMODEL_INTERNAL_TOKEN` bearer —
  Claude Haiku 4.5 in ~20s (Anthropic-API bound, same shape as
  Railway).
- [x] Step 5.5b: [web/vercel.json](../web/vercel.json) rewrites
  `/api/recommend` → `https://roadmodel-api.vercel.app/v1/recommend`.
- [x] Step 5.5b: Next.js proxy `web/app/api/recommend/route.ts`,
  `recommendOnServer` in [web/lib/api.ts](../web/lib/api.ts),
  `ROADMODEL_SERVICE_URL` + `ROADMODEL_INTERNAL_TOKEN` fields in
  [web/lib/env.ts](../web/lib/env.ts) — all removed.
- [x] Step 5.5b: bearer auth dropped from FastAPI
  ([service/app/main.py](../service/app/main.py) — `require_bearer`
  dependency removed; `service/app/auth.py` deleted). The Vercel
  rewrite can't inject headers, so the bearer would have 401'd every
  browser POST; consolidating onto Vercel made the shared secret
  redundant anyway (driver 3 of Step 5.5). Step 6 ships rate
  limiting as the replacement defense.
- [x] Step 5.5b: live `POST staging.roadmodel.ai/api/recommend`
  returns Haiku 4.5 (evidence + screenshot pasted into issue #86
  before close).
- [x] Step 5.5b: browser submit from `/recommend` populates the
  output column end-to-end against the live Vercel-API (verified
  via headless Chromium against `staging.roadmodel.ai/recommend`;
  output column rendered model header + settings + free-tier
  badge in 26.8s end-to-end).
- [x] Step 5.5b: 6 stale Vercel env entries deleted via API
  during close-out — 5 on `roadmodel-web` (3×
  `ROADMODEL_INTERNAL_TOKEN`, 2× `ROADMODEL_SERVICE_URL`) + 1 on
  `roadmodel-api` (`ROADMODEL_INTERNAL_TOKEN`). The Step 5.5a-era
  `ROADMODEL_USER_CONTEXT` on `roadmodel-api` (Dockerfile-era,
  superseded by `_bootstrap_user_context()` to `/tmp`) was also
  pruned.
- [x] Step 5.5b: `service/railway.json` and `service/Dockerfile`
  removed from the repo; [project_railway_setup_gaps] memory
  marked historical.
- [x] Step 5.5b: Railway project `roadmodel-service` deleted via
  dashboard 2026-05-20 once the control plane returned (CLI / MCP
  re-auth would have required an interactive `railway login` that
  the agent couldn't drive; dashboard delete was the faster path).
  Confirmed cut-over post-delete: `https://roadmodel-service-staging.up.railway.app/healthz`
  and `https://roadmodel-service-production.up.railway.app/healthz`
  both return HTTP 404 (Railway edge resolves but has no service to
  route to). The $5/mo Hobby plan billing on the workspace stops
  with the project delete.
- [x] Step 5.5b: issue [#86](https://github.com/nathanramoscfa/roadmodel/issues/86)
  closed with the verification evidence.

**Resume checklist (Step 6 — Phase 3 Step 6).** Phase 3 Step 6
ships the abuse-control + audit-log layer the Step 5.5b close-out
forward-referenced. Architecturally, the `/api/recommend` path
changes from a pure Vercel rewrite to a thin Next.js Route Handler
that wraps the same upstream call with rate limiting and a
Supabase audit-log write.

- [x] `web/app/api/recommend/route.ts` restored as a thin proxy.
  It is **not** the Step-5-era proxy: no `ROADMODEL_SERVICE_URL`
  / `ROADMODEL_INTERNAL_TOKEN` shared secret is re-introduced
  (the upstream URL is hard-coded to the production
  `roadmodel-api.vercel.app` alias; the bearer is gone for good).
  The handler validates the request body, forwards POSTs to the
  FastAPI service server-side, and writes an enriched audit row
  (model / provider / cost) on success.
- [x] `web/vercel.json` `rewrites` block deleted. With the Next.js
  Route Handler back in place, the rewrite would intercept first
  and bypass the rate limiter; removing it routes `/api/recommend`
  to the handler.
- [x] `@upstash/ratelimit` + `@upstash/redis` + `@supabase/supabase-js`
  added to `web/package.json`. Upstash backs the 10/min burst +
  3/day sliding-window limiters keyed on the SHA-256 of the
  forwarded client IP and User-Agent (salted with
  `ROADMODEL_IP_SALT`).
- [x] `infra/supabase/migrations/20260601000000_audit_log.sql` is
  the first migration in the new `infra/supabase/` tree. The
  `audit_log` table has `bigserial` PK, `timestamptz ts` (BRIN
  index), the SHA-256 IP/UA hashes, the route, the optional
  provider/model/token/cost enrichment columns, an outcome enum
  (`ok` / `rate_limited` / `burst_dropped` / `recommender_error`
  / `bad_input`), and RLS enabled with service-role-only
  insert + select policies. Apply manually via
  `supabase db push --linked` from
  [infra/supabase/README.md](supabase/README.md).
- [x] `tests/test_audit_log_migration.py` parses the SQL file with
  `sqlparse` and asserts the column order, BRIN index, RLS
  enable, and both service-role policies are present. Lives in
  the root `tests/` so the existing pytest CI job runs it.
- [x] `web/tests/recommend.spec.ts` extended with two Playwright
  tests for the 429 burst-drop and 429 daily-rate-limit
  user-visible behavior. The tests mock `/api/recommend` at the
  `page.route` level rather than driving real Upstash traffic,
  matching the existing 502 test pattern in the same file
  (Playwright cannot intercept the Next.js server's outbound
  Upstash calls, so the literal "11 real POSTs" framing from
  the Step 6 task spec is replaced by the strongest equivalent
  CI can run unattended). The backend rate-limit decision
  itself rides on `@upstash/ratelimit`'s upstream tests.
- [x] `docs/cost-ceilings.md` publishes the day-one provider
  caps with the cap-breach response runbook + forward
  reference to the Phase 7 application ledger. Source of truth
  remains the
  [Provider cost ceilings](#provider-cost-ceilings) table
  below; the public doc derives from it.
- [ ] **Deferred to Step 6.1:** seed `UPSTASH_REDIS_URL`,
  `UPSTASH_REDIS_TOKEN`, and `ROADMODEL_IP_SALT` on
  `roadmodel-web` Vercel env vars (preview + staging +
  production). Step 6 surfaced that the Step 5.5b close-out's
  "Upstash provisioned + env vars set in Vercel" claim was
  inaccurate — UPSTASH_REDIS_URL was missing on every scope,
  which broke the Step 6 preview deploy. The Step 6 PR
  responded by keeping `web/lib/env.ts` `.optional()` and
  shipping `web/lib/ratelimit.ts` in **fail-open mode** so the
  build succeeds; the rate-limit defense is inert until the
  values land. Step 6.1 is a small follow-up PR that flips
  env.ts to `.min(1)`, removes the fail-open path in
  `ratelimit.ts`, and verifies a real 429 from
  `staging.roadmodel.ai/api/recommend` after the maintainer
  seeds the values.

Vercel env-var seed (do this before Step 6.1 PR can ship):

```bash
cd web
# UPSTASH_REDIS_URL — from the Upstash console
for SCOPE in preview staging production; do
  pbpaste | tr -d '\r\n' \
    | vercel env add UPSTASH_REDIS_URL $SCOPE --force --yes
done
# repeat the loop for UPSTASH_REDIS_TOKEN (Upstash console)
# and ROADMODEL_IP_SALT (fresh value: openssl rand -hex 32)
```

Save the values to Google Password Manager under entries
`roadmodel UPSTASH_REDIS_URL`, `roadmodel UPSTASH_REDIS_TOKEN`,
and `roadmodel ROADMODEL_IP_SALT` for the quarterly-rotation
runbook in
[docs/cost-ceilings.md](../docs/cost-ceilings.md#cap-breach-response-runbook).

**Resume checklist (Step 7 — Phase 3 Step 7).** Phase 3 Step 7 cuts
the production apex DNS, verifies TLS + monitoring + end-to-end
smoke against `https://roadmodel.ai`, publishes
[docs/phase03-release-runbook.md](../docs/phase03-release-runbook.md),
and tags `v0.3.0-phase-3` (milestone marker — no PyPI republish).

- [x] `roadmodel.ai` attached to `roadmodel-web` Vercel project
  (Domains tab; apex target `76.76.21.21`).
- [x] `NEXT_PUBLIC_SITE_URL=https://roadmodel.ai` seeded on
  `roadmodel-web` production scope; production redeployed.
- [x] Namecheap apex **A Record** → `76.76.21.21` (no parked-page
  redirect existed at cut time). `dig A roadmodel.ai +short` →
  `76.76.21.21`.
- [x] TLS green via manual `vercel certs issue roadmodel.ai`:
  `curl -sSI https://roadmodel.ai` → `HTTP/2 200`, Let's Encrypt
  R12 cert valid May 20 → Aug 18 2026.
- [x] UptimeRobot monitor `803118024` for `https://roadmodel.ai`
  created 2026-05-20; recorded in
  [UptimeRobot monitors](#uptimerobot-monitors).
- [x] Upstash trio seeded on **all four scopes** — Production,
  Preview, Development, and `staging` Custom Environment — via the
  Vercel Marketplace Upstash integration (which injects `KV_REST_API_*`
  legacy names) plus `UPSTASH_REDIS_URL` / `UPSTASH_REDIS_TOKEN`
  aliases. CLI seeded Production + Development + staging; the
  default `Preview` scope was added via the Vercel dashboard
  (Settings → Environment Variables → Edit existing row → also
  check Preview) since the Vercel CLI bug in both 54.1.0 and
  54.2.0 blocks non-interactive CLI seeding of `preview` without
  a branch.
- [x] Playwright (`home page`, `renders form`) + functional `curl`
  smoke + 4-request rate-limit sequence captured in
  [docs/phase03-release-runbook.md](../docs/phase03-release-runbook.md).
  Live 429 confirmed: `{"error":"rate_limited","retry_after":31615}`.
- [ ] Signed tag `v0.3.0-phase-3` pushed from `main`; GitHub Release
  created (see runbook — tag push runs `build` + `sign` only).

## Environment variables

The full env var schema both Vercel projects read. Step 4 wires the
Next.js consumers, Step 5.5 stands up the `roadmodel-api` Vercel
project that consumes the AI provider keys, Step 6 consumes the
Upstash pair for the rate limiter. Documenting them all here is
deliberate — Step 6 should not relitigate the Upstash decision.

> **Status (2026-05-19, post Step 5.5b close-out):** The
> `Set today` column below reflects the **actual** state of each
> project's Vercel env vars, not the aspirational target. The
> `Set today` and `Target scopes` columns will reconverge as
> Step 6 wires Supabase + Upstash into the FastAPI tier and
> Step 7 splits the `roadmodel-api` staging custom env.

| Variable                       | Value source                                                 | Consumed by                                                                  | Set today                                                | Target scopes (when fully wired) |
| ------------------------------ | ------------------------------------------------------------ | ---------------------------------------------------------------------------- | -------------------------------------------------------- | --------------------------------- |
| `ANTHROPIC_API_KEY`            | `roadmodel-api` Vercel env vars                              | FastAPI service (Step 5.5a)                                                  | api: production + preview                                | api: production + preview + staging (Step 7) |
| `OPENAI_API_KEY`               | `roadmodel-api` Vercel env vars                              | FastAPI service (Step 5.5a)                                                  | api: production + preview                                | api: production + preview + staging (Step 7) |
| `GOOGLE_API_KEY`               | `roadmodel-api` Vercel env vars                              | FastAPI service (Step 5.5a)                                                  | api: production + preview                                | api: production + preview + staging (Step 7) |
| `NEXT_PUBLIC_SITE_URL`         | `roadmodel-web` Vercel env vars                              | Next.js metadata + absolute links (Step 4)                                   | web: preview + staging + production                      | web: preview + staging + production |
| `SUPABASE_URL`                 | Both Vercel projects' env vars                               | Next.js audit log (Step 6) + FastAPI (Step 6 — currently unused)             | web: preview + staging + production; api: **not set**    | both projects, all scopes (Step 6) |
| `SUPABASE_SERVICE_ROLE_KEY`    | Both Vercel projects' env vars (Supabase dashboard → Vercel) | Next.js audit log (Step 6) + FastAPI (Step 6 — currently unused)             | web: preview + staging + production; api: **not set**    | both projects, all scopes (Step 6) |
| `UPSTASH_REDIS_URL`            | `roadmodel-web` Vercel env vars (Marketplace Upstash + alias) | Next.js rate limiter (live since Step 7 close-out)                          | web: production + preview + development + staging Custom Env (Step 7) | web: production + preview + development + staging |
| `UPSTASH_REDIS_TOKEN`          | `roadmodel-web` Vercel env vars (Marketplace Upstash + alias) | Next.js rate limiter (live since Step 7 close-out)                          | web: production + preview + development + staging Custom Env (Step 7) | web: production + preview + development + staging |
| `ROADMODEL_IP_SALT`            | `roadmodel-web` Vercel env vars (generated `openssl rand -hex 32`) | Next.js rate limiter daily IP+UA hashing salt (live since Step 7 close-out); rotate quarterly | web: production + preview + development + staging Custom Env (Step 7) | web: production + preview + development + staging |
| `FRONTIER_ROADMAP_ENABLED`     | `roadmodel-web` Vercel env vars (default `false`)            | Next.js model-routing resolver — gates the Phase 5 Anthropic frontier branch | **not set anywhere in Phase 4 (defaults false)**         | web: production + preview + staging (set true on the scope where Phase 5 rolls out) |
| `RECOMMEND_RATELIMIT_EXEMPT_USER_IDS` | `roadmodel-web` Vercel env vars (comma-separated founder Supabase uid; default empty) | Next.js rate limiter — user_ids that skip the `/api/recommend` daily limit (founder browser dogfooding); empty = nobody exempt | web: production (founder uid) | web: production (+ preview/staging if founder tests there) |

Rules:

- The `SUPABASE_SERVICE_ROLE_KEY` bypasses RLS. It's set on both
  Vercel projects' env-var scopes (server-side only) and the
  Supabase dashboard itself. It must never appear in any
  `NEXT_PUBLIC_*` var, browser bundle, or client-side render — the
  browser-facing public `anon` key handles client-side reads.
- `*_API_KEY` values live ONLY on `roadmodel-api` Vercel env vars
  and the maintainer's local shell. They never appear on
  `roadmodel-web` env vars — the browser must never see provider
  keys, per [private/ROADMAP.md](../private/ROADMAP.md) §3.
- `FRONTIER_ROADMAP_ENABLED` is **reserved for Phase 5
  paid-frontier rollout** — do NOT flip it true in Phase 4. The
  roadmap-engine wrapper throws "Phase 5 scope: anthropic engine
  branch not yet wired" if the flag fires while Phase 4 code is
  deployed. The Phase 4 Step 4 FAIL escalation stays inside
  Google (FREE_ROADMAP_MIN_TIER flips from `'B'` to `'A'` in
  `web/lib/engine-overrides.ts`, the catalog-derived
  `pickFreeEngine` shifts to Gemini 3 Flash); the env var is
  the gate Phase 5 flips, not Phase 4.
- `ROADMODEL_INTERNAL_TOKEN` / `ROADMODEL_SERVICE_URL` were
  **retired in Step 5.5b**. The cross-project boundary that used
  to need them is now a Vercel rewrite — no shared secret, no
  cross-vendor coordination. See the [Step 5.5 resume
  checklist](#resume-checklist-step-55--closed-2026-05-19) for the
  full cut-over evidence.
- Local development reads the same schema from a gitignored
  `.env` at the repo root; [infra/.env.example](.env.example) is
  the template.

## DNS records

The registrar of record for `roadmodel.ai` is the maintainer's
Namecheap account (confirmed by the maintainer during step 4 of
the [Provisioning sequence](#provisioning-sequence)).

| Host                      | Type   | Value                                       | TTL   | Notes                                                  |
| ------------------------- | ------ | ------------------------------------------- | ----- | ------------------------------------------------------ |
| `staging.roadmodel.ai`    | CNAME  | `6414f72d9e02a5d3.vercel-dns-016.com`       | Auto  | Cut 2026-05-17. Project-scoped Vercel target; `cname.vercel-dns.com` is the documented universal fallback per Vercel's IP-range migration banner. |
| `roadmodel.ai` (apex)     | A      | `76.76.21.21` (Vercel documented apex IP)   | Auto  | Cut 2026-05-20 (Step 7). Namecheap Advanced DNS → **A Record**, host `@` (Namecheap's ALIAS type expects a hostname; an IP must use A). No parked-page redirect existed at cut time. `dig A roadmodel.ai +short` → `76.76.21.21`. |
| `www.roadmodel.ai`        | CNAME  | TBD (Vercel-issued `www` target)            | 300   | **Not cut in Step 7** — apex-only launch; `www` redirects deferred. |

Step 2 cut only the `staging` row. Step 7 cut the apex row above;
`www` stays TBD until a follow-up DNS PR adds the Vercel `www`
target and redirect policy.

## TLS posture

Vercel auto-issues Let's Encrypt certificates on every custom
domain it serves and auto-renews them ~30 days before expiry. No
manual intervention is required unless the auto-renew fails.

Failure modes the maintainer should watch for:

- **DNS misconfigured during issuance.** Vercel surfaces this in
  the project's `Domains` tab with a red badge; fix the registrar
  record and Vercel retries automatically within an hour.
- **CAA records blocking Let's Encrypt.** `roadmodel.ai` should
  have no CAA records at registrar level for Step 2; if added
  later (a Phase 7 hardening option), include `letsencrypt.org`
  explicitly.
- **Renewal failure.** Vercel emails the project owner; the
  manual fix is to re-issue from `Domains → Refresh certificate`.

The same auto-issue posture applies to `roadmodel-api`
(`*.vercel.app` and any custom domain configured) and Supabase
(managed TLS in front of project URLs). No manual cert handling
is required at this stage.

## Provider cost ceilings

These are the day-one cost-ceiling floor the Phase 7 application
ledger strengthens but does NOT replace (see
[Disaster recovery](#disaster-recovery)). The cap values below
are the single source of truth — Step 6 mirrors them into
`docs/cost-ceilings.md` as the public-doc derivative; if a cap
changes here, Step 6's doc must be re-synced.

| Provider   | Monthly cap (USD) | Alert thresholds       | Console URL                                                                       |
| ---------- | ----------------- | ---------------------- | --------------------------------------------------------------------------------- |
| Anthropic  | $200              | 50% / 75% / 90% email ($100 / $150 / $180) | `https://platform.claude.com/settings/limits` (was `console.anthropic.com`; Anthropic rebranded the console late 2025) |
| OpenAI     | $200 (org budget; hard cap) | 50% / 75% / 90% email ($100 / $150 / $180) | `https://platform.openai.com/settings/organization/limits` (was `/account/limits`; OpenAI 2025 redesign collapsed the legacy soft/hard distinction into a single budget + percentage alerts — the 75% alert is the functional successor to the old "soft limit") |
| Google     | $50               | 50% / 75% / 90% email ($25 / $37.50 / $45) | `https://console.cloud.google.com/billing/010548-2423B0-E0B624/budgets` (project `roadmodel-saas`, budget `roadmodel Gemini API monthly`, scoped to Generative Language API service) |

Cap-sizing rationale (frozen here so Phase 7 doesn't relitigate):

- `private/ROADMAP.md` §5 sizes AI inference at $200-$800/mo at
  pilot scale assuming ≤100 paid users. Phase 3 has zero paid
  users and only an anonymous IP-rate-limited recommender — the
  Step 2 caps sit at the bottom of that range with a ~3x safety
  margin against the expected anonymous-traffic volume.
- The Anthropic + OpenAI caps are equal ($200 each) because the
  Phase 3 free-tier model could be served from either provider
  depending on the cheap-model availability at the time of each
  call (Haiku 4.5 vs Flash); the routing decision is finalized
  in Step 5.
- Google's cap is the smallest ($50) — but see
  [Model routing](#model-routing-phase-3) below; in Phase 3 the
  Gemini API is actually the **primary** free-tier provider, not
  the fallback. The $50 cap is sized small not because Gemini
  carries the least load, but because Gemini 2.5 Flash is so
  cheap per call that $50 covers ~500,000 recommend calls — well
  past any realistic pilot-scale traffic.
- All three alert ladders (50% / 75% / 90%) match by design so
  the maintainer sees a consistent breach signal across vendors.

### Model routing (Phase 3)

Frozen decision for the free-tier cheap-model selection. Phase 3
Step 5 (the FastAPI service) implements this; Step 5 should NOT
relitigate the choice unless one of the trigger conditions below
fires.

| Tier                 | Primary model       | Fallback (on cap or outage) | Why                                                  |
| -------------------- | ------------------- | --------------------------- | ---------------------------------------------------- |
| Anonymous web        | Gemini 2.5 Flash    | Claude Haiku 4.5            | Flash is ~15× cheaper per call than Haiku, US-based provider, comparable quality at this complexity tier. |
| Free signed-in (rec) | Gemini 2.5 Flash    | Claude Haiku 4.5            | Same call profile as anonymous.                      |
| Free signed-in (roadmap) | Claude Haiku 4.5 (long-form) | Gemini 2.5 Flash | Roadmap synthesis benefits from Claude's longer-context coherence; Flash falls back if cap fires. |

Rationale (frozen):

- **Cost.** Gemini 2.5 Flash at ~$0.0001/call vs Haiku 4.5 at
  ~$0.0015/call. The $50 Google cap covers ~500,000 calls/month;
  Anthropic's $200 cap covers ~133,000 calls/month of Haiku at
  the same call profile. Flash is the strictly cheaper primary.
- **Geopolitics + brand.** DeepSeek considered and rejected:
  cheaper than Haiku but more expensive than Flash, plus
  China-jurisdiction privacy exposure, US-China API-restriction
  risk, and brand mismatch with roadmodel's positioning (we
  recommend Claude/Cursor/Codex; running our own surface on a
  model we don't recommend undermines us). Not worth $15-30/mo
  expected savings vs Haiku for solo-maintainer ops tax of a 4th
  provider.
- **Fallback design.** When Gemini's $50 cap fires (or Gemini
  has an outage), traffic flips to Haiku on Anthropic. Anthropic's
  $200 cap easily absorbs this — at Haiku rates it covers another
  ~133K calls of overflow. OpenAI's $200 is the third-tier
  fallback if both Google and Anthropic are unavailable.

Trigger conditions to revisit this routing:

- Phase 5 monetization ships and paid-tier revenue funds AI cost
  — at that point, default frontier (Sonnet 4.6) takes over for
  paid surfaces and this cheap-tier discussion becomes academic
  for paying users.
- Google deprecates Flash or raises Flash pricing by >5×.
- Anthropic drops Haiku pricing below Flash.
- A non-trivial cohort of users complains about Flash quality
  for recommend-tier prompts.

## UptimeRobot monitors

Free-tier UptimeRobot account; staging monitor in Step 2, production
monitor added in Step 7 when the apex URL is cut.

| Monitor ID                                                                     | Target URL                          | Interval   | Alert channel                |
| ------------------------------------------------------------------------------ | ----------------------------------- | ---------- | ---------------------------- |
| `803092893` (paused 2026-05-17; resumed 2026-05-19 after Step 4 deploy went live — `Up` per dashboard) | `https://staging.roadmodel.ai`      | 5 minutes  | maintainer's email on file   |
| `803118024` (created 2026-05-20 Step 7; Up since creation — 100% / 24h, 36 ms avg) | `https://roadmodel.ai`              | 5 minutes  | maintainer's email on file   |

UptimeRobot's free tier allows 50 monitors at a 5-minute floor.
That's the right granularity for Step 2 — finer-grained polling
adds no signal at this stage and burns the free-tier quota faster
than necessary.

**Pause/resume history.** Free-tier UptimeRobot treats HTTP 4xx as
Down (the "Up HTTP status codes" override is gated behind the Solo
plan, $7/mo). Between Step 2 (DNS cut) and Step 4 (Next.js scaffold
live), `staging.roadmodel.ai` responded 404 / `DEPLOYMENT_NOT_FOUND`
because no deployment was aliased to it — so the monitor was
**paused** at the end of Step 2 to avoid page-spam, and **resumed
2026-05-19** after Step 4 brought staging to 2xx. Current state:
`Up`, 100% uptime in the polling window.

## Provisioning sequence

The seven-step recipe a future maintainer follows to re-provision
this stack from scratch. Each step blocks on the verifying check
named in it; do not move to step N+1 until step N's check passes.

1. **Vercel.** Create the `roadmodel-web` project under the
   maintainer's Vercel team. Add `staging` and `production`
   environments under it (Settings → Environments → Add). Connect
   the GitHub repo (Settings → Git → Connect GitHub) with Preview
   Deployments enabled. Record the project ID and team ID into
   the [Cloud projects](#cloud-projects) table.

2. **Vercel (roadmodel-api).** Create a second Vercel project
   for the FastAPI recommender under the same team as
   `roadmodel-web`. From the repo's `service/` directory:

   ```bash
   cd service && vercel link --yes --project roadmodel-api
   ```

   Set Root Directory = `service/`, framework = `fastapi`
   (auto-detected from `service/pyproject.toml`), runtime = Python
   3.12 / Fluid Compute (auto). The `[tool.vercel] entrypoint =
   "app.main:app"` declaration in `service/pyproject.toml`
   resolves to the ASGI handler. Add `staging` and `production`
   custom environments (Settings → Environments) so this project
   mirrors `roadmodel-web`'s scope layout. Seed env vars per
   [Environment variables](#environment-variables) from Google
   Password Manager entries `roadmodel <VAR_NAME>` via:

   ```bash
   pbpaste | tr -d '\r\n' | vercel env add VAR <env> --force --yes
   ```

   Record the project ID into the
   [Cloud projects](#cloud-projects) table.

   > **Historical:** Steps 5.5a / 5.5b superseded the original
   > Railway provisioning step here. The Railway-era recipe lived
   > in commits prior to Step 5.5b; consult git history if you
   > need it for a forensic reason.

3. **Supabase.** Create the `roadmodel-data` project on the
   **Pro** plan — not Free; Free's row caps and lack of daily
   backups are disqualifying for the Phase 4 audit log. Record
   the project URL and the dashboard path to the service-role
   key (Settings → API → service_role) into the
   [Cloud projects](#cloud-projects) table. **Do NOT commit the
   service-role key value itself anywhere** — it lives only in
   the two Vercel projects' env vars and the Supabase dashboard.

4. **DNS.** At the registrar (Namecheap), add a CNAME record
   for `staging.roadmodel.ai` pointing at Vercel's
   `cname.vercel-dns.com` target. Do not touch the apex or `www`
   rows — those wait for Step 7. Verify with:

   ```bash
   dig CNAME staging.roadmodel.ai +short
   ```

   Expected: a line containing `vercel-dns.com.` Block on this
   before moving to step 5.

5. **TLS.** Wait up to 5 minutes for Vercel to auto-issue a
   Let's Encrypt certificate against the new CNAME. Verify with:

   ```bash
   curl -sSI https://staging.roadmodel.ai | head -1
   ```

   Expected: `HTTP/2 200` or `HTTP/2 404` — either response
   means the TLS handshake completed. A connection error
   (`SSL_ERROR`, `Could not resolve host`) means re-check step 4.

6. **UptimeRobot.** In the maintainer's UptimeRobot dashboard,
   create a free-tier HTTP(s) monitor against
   `https://staging.roadmodel.ai` at the 5-minute interval. Set
   the maintainer's email as the notification channel. Record
   the monitor ID into the
   [UptimeRobot monitors](#uptimerobot-monitors) table.

7. **Provider caps.** In each provider console, configure the
   cap and alert thresholds documented in
   [Provider cost ceilings](#provider-cost-ceilings):

   - **Anthropic.** `console.anthropic.com` → Settings → Limits
     → set monthly spend cap $200 with email alerts at 50%,
     75%, 90%.
   - **OpenAI.** `platform.openai.com` → Billing → Usage
     limits → set hard limit $200, soft limit $150, alerts at
     50%, 75%, 90%.
   - **Google.** Create a new GCP project (`roadmodel-saas`),
     link the existing billing account, enable the
     **Generative Language API** (Gemini). For the API key,
     **use Google AI Studio (https://aistudio.google.com), NOT
     Cloud Console → Credentials.** AI Studio creates a plain
     API key (no service account binding required) and lets you
     pick `roadmodel-saas` as the billing project so usage hits
     the GCP budget. The Cloud Console "Create credentials → API
     key" flow now (2025+ policy) demands service-account binding
     and a Vertex-scoped role, which is overkill for a simple
     `x-goog-api-key`-header use case and surfaces a chain of
     IAM/role obstacles. Then `console.cloud.google.com` →
     Billing → Budgets & alerts → create a $50/mo budget scoped
     to the `roadmodel-saas` project + filtered to the
     Generative Language API service, alerts at 50%, 75%, 90%.
     Google budgets are **email-only**, not hard cutoffs —
     Phase 7 application ledger adds the hard stop layer.

   Record the Google billing-account-specific console URL into
   the [Provider cost ceilings](#provider-cost-ceilings) table
   (it's the only one that varies per billing account).

After step 7, the maintainer runs `scripts/verify-infra.sh`
locally; expected output is `PASS` on every check.

## Disaster recovery

The provider-side cost ceilings configured above are the
**disaster-recovery floor** for AI-inference spend. Phase 7
adds an application-side ledger that tracks token spend in real
time per provider and refuses calls before they breach a daily
ceiling (see [private/ROADMAP.md](../private/ROADMAP.md) §4
Phase 7.1). That ledger **strengthens but does not replace**
this floor — if the application ledger ever fails open (a bug, a
bad deploy, a stale cache), the provider-side caps still hold
and the bill cannot exceed $450/mo across the three providers
under Step 2's settings.

Recovery steps the maintainer follows when a cap fires:

1. The provider emails the maintainer at the configured
   threshold (50% / 75% / 90%).
2. The maintainer triages: is the spend organic (legitimate
   traffic growth — raise the cap deliberately) or anomalous
   (abuse, leaked key, runaway loop — kill the offending
   surface)?
3. For anomalous spend, the maintainer revokes the affected
   provider API key in the provider console, rotates a fresh
   key onto `roadmodel-api` Vercel env vars (`vercel env add
   <KEY> production --force --yes` from `service/`), redeploys
   the FastAPI service (`vercel deploy --prod` from `service/`
   or push to `main`), and files an incident note under
   `private/incidents/<UTC-date>-<provider>.md` for the
   post-mortem trail.
4. For organic spend, the maintainer raises the cap **only
   after** updating the cap value in
   [Provider cost ceilings](#provider-cost-ceilings) AND
   re-running `update/sync_public_roadmap.py --check` to
   confirm the public derivative still lints clean. The cap
   value is the source of truth here; the public doc trails.

The Phase 7 ledger never assumes the provider caps will hold —
it is a defense-in-depth layer, not a replacement. Equally, the
provider caps don't assume the application ledger will hold —
they are the deterministic floor regardless of application
state.

## Authentication

Phase 4 Step 1 (2026-05-21) stood up Supabase Auth on the
`roadmodel-data` project. Sign-in flows: magic-link (email OTP)
and GitHub OAuth. Sessions are HTTP-only cookies refreshed in
`web/middleware.ts` on every request that traverses a protected
route. The Phase 3 password gate (`SITE_PASSWORD`) sits **in
front of** auth — see [web/middleware.ts](../web/middleware.ts):
gate branch first, auth branch second. Step 8 of Phase 4 lifts
the gate; Step 1 must not remove it.

### Key separation rule

Two distinct Supabase keys, two distinct trust boundaries:

| Key                              | Env var                            | Where it can appear                                            | Role                                      |
| -------------------------------- | ---------------------------------- | -------------------------------------------------------------- | ----------------------------------------- |
| Publishable (formerly `anon` JWT) | `NEXT_PUBLIC_SUPABASE_ANON_KEY`    | Browser bundle (`NEXT_PUBLIC_`), server, middleware            | Anonymous reads, scoped by RLS            |
| Secret (formerly `service_role`)  | `SUPABASE_SERVICE_ROLE_KEY`        | **Server-side only** — Vercel env vars, never browser-shipped  | Bypasses RLS (audit-log writer uses this) |

Supabase renamed the keys in 2026; the env var names stay legacy
for code-compat with the Phase 3 audit-log writer in
[web/lib/audit.ts](../web/lib/audit.ts). The publishable key is
public-safe by design (RLS enforces row access); the secret key
must **never** appear in a `NEXT_PUBLIC_*` var, a browser bundle,
a client component, or a server response body.

### GitHub OAuth — provisioning + rotation

The maintainer-side OAuth app lives at
[github.com/settings/applications](https://github.com/settings/applications).
Settings:

- **Application name:** `roadmodel`
- **Homepage URL:** `https://roadmodel.ai`
- **Authorization callback URL:** `https://nbxzpqnmafcayeqnfvcv.supabase.co/auth/v1/callback`
  (Supabase project ref — change if the project is re-provisioned)

The Client ID + Client Secret are pasted into Supabase dashboard
**Auth → Providers → GitHub** (toggle on). Both values are saved
to Google Password Manager as
`roadmodel github_oauth_client_id` and
`roadmodel github_oauth_client_secret`.

**Rotation procedure** (when the secret leaks or on the quarterly
secrets-rotation cadence from Phase 7):

1. GitHub OAuth app → Generate a new client secret. The old one
   stays valid until you delete it; **do not delete yet**.
2. Supabase dashboard → Auth → Providers → GitHub → Edit → paste
   the new secret → Save. Supabase swaps the new value live.
3. Smoke-test sign-in with GitHub against `staging.roadmodel.ai`.
4. GitHub OAuth app → delete the old secret.
5. Update the Google Password Manager entry.

**The Client ID does not rotate** unless the OAuth app is
re-created (which forces a new callback URL handshake — only do
this on full re-provisioning).

### Magic-link email template

Configured at Supabase dashboard **Auth → Email Templates →
Magic Link**. Phase 4 Step 1 uses the **Supabase default
template** verbatim — the `{{ .ConfirmationURL }}` token in the
body is what the magic-link handshake reads.

If the template is ever overridden (custom branding, copy
changes), the override MUST keep `{{ .ConfirmationURL }}` inside
an `<a href="…">` tag, or magic-link sign-in silently fails (the
email arrives without a clickable link). Verify after any edit:
the Step 1 e2e tests (`web/tests/auth.spec.ts`) stub the OTP
request at the network layer and don't catch this — only a real
sign-in attempt against the live template does.

### Audit log + user attribution

Step 1's
[20260602000000_audit_log_user_id.sql](supabase/migrations/20260602000000_audit_log_user_id.sql)
migration adds a nullable `user_id uuid` column to `audit_log`
referencing `auth.users(id) ON DELETE SET NULL`. The Phase 3
anonymous `/api/recommend` audit writes keep `user_id` NULL;
signed-in routes (Phase 4 Steps 4 / 5 forward) pass
`session.user.id`. RLS:

- `service_role` retains full SELECT + INSERT (Phase 3 policies
  preserved).
- `authenticated` gains a SELECT policy filtered by
  `user_id = auth.uid()` — a signed-in user reads only their
  own rows.
- `anon` has no SELECT policy and so cannot read anything.

The schema is verified live in CI by the `migration-tests` job
in [.github/workflows/tests.yml](../.github/workflows/tests.yml),
which stands up a vanilla Postgres 16 container from
[infra/test-postgres/docker-compose.yml](test-postgres/docker-compose.yml),
seeds the Supabase-managed `auth.users` table and the
`anon` / `authenticated` / `service_role` roles via
[init.sql](test-postgres/init.sql), applies every migration, and
runs the pg-catalog assertions in
[tests/test_phase04_migrations.py](../tests/test_phase04_migrations.py).
