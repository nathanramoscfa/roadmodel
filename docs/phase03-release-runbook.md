<!-- docs/phase03-release-runbook.md -->
# Phase 3 Release Runbook

This runbook covers the Phase 3 go-live cut for `roadmodel.ai` and the
`v0.3.0-phase-3` milestone tag. Phase 2's PyPI release flow lives in
[docs/phase02-release-runbook.md](phase02-release-runbook.md); Phase 3
does **not** republish the OSS CLI package (`roadmodel` v0.2.0 is
unchanged).

## Cut sequence

Operator-driven recipe for cutting the production apex from
staging-only to `roadmodel.ai` live. Complete each step before moving
to the next; verification commands are in
[Verification evidence](#verification-evidence).

0. **Prerequisites (Vercel + Upstash).**
   - Confirm `roadmodel.ai` is attached to the `roadmodel-web` Vercel
     project (Domains tab). Vercel expects apex record
     `A roadmodel.ai 76.76.21.21`.
   - Seed `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN`, and
     `ROADMODEL_IP_SALT` on `roadmodel-web` **production** (deferred
     from Step 6.1 — required for live 429 rate-limit smoke):

     ```bash
     cd web
     for SCOPE in production; do
       pbpaste | tr -d '\r\n' | vercel env add UPSTASH_REDIS_URL $SCOPE --force --yes
     done
     # repeat for UPSTASH_REDIS_TOKEN and ROADMODEL_IP_SALT
     # (openssl rand -hex 32 for ROADMODEL_IP_SALT)
     vercel deploy --prod --yes
     ```

   - Set `NEXT_PUBLIC_SITE_URL=https://roadmodel.ai` on production
     (literal — no Password Manager secret):

     ```bash
     cd web
     printf '%s' 'https://roadmodel.ai' \
       | vercel env add NEXT_PUBLIC_SITE_URL production --force --yes
     vercel deploy --prod --yes
     ```

1. **Add apex DNS at Namecheap.** In Advanced DNS for `roadmodel.ai`,
   delete any parked-page `URL Redirect Record` on the apex if present
   (Step 7 cut on 2026-05-20 found none — only a `staging` CNAME and a
   locked SPF TXT existed). Add an **A Record** (Namecheap's apex-IP
   record type — ALIAS at Namecheap expects a hostname, not an IP):
   - Host: `@`
   - Type: A Record
   - Value: `76.76.21.21` (Vercel documented apex IP)
   - TTL: Automatic / 300

2. **Wait for propagation** (typically 5–15 minutes).

3. **Verify DNS:**

   ```bash
   dig A roadmodel.ai +short
   ```

   Expected: a line containing `76.76.21.21`.

4. **Verify TLS** (Vercel auto-provisions Let's Encrypt once DNS
   resolves — no manual certificate step):

   ```bash
   curl -sSI https://roadmodel.ai | head -1
   ```

   Expected: `HTTP/2 200`.

5. **UptimeRobot monitor.** In the maintainer's UptimeRobot dashboard,
   create a free-tier HTTP(s) monitor for `https://roadmodel.ai` at the
   5-minute interval (same channel as staging monitor `803092893`).
   Record the monitor ID in
   [infra/README.md](../infra/README.md#uptimerobot-monitors).

6. **End-to-end smoke (Playwright + functional curl).** Run the
   commands in [Verification evidence](#verification-evidence) against
   `https://roadmodel.ai`. Both Playwright greps and the rate-limit
   curl sequence must pass before opening the docs PR.

7. **Docs PR + tag (outside PR merge).**
   - Merge the `docs(infra)` PR updating this runbook and
     `infra/README.md` DNS / monitor / production-URL tables.
   - From up-to-date `main`, sign and push the milestone tag, then
     create the GitHub Release (see [Tag and GitHub Release](#tag-and-github-release)).

## Verification evidence

Captured during the Step 7 cut (2026-05-20 UTC). Redact tokens if
re-pasting elsewhere.

### Pre-cut baseline (apex not yet live)

```text
$ dig A roadmodel.ai +short
(empty — no A record at cut start)

$ curl -sSI https://roadmodel.ai | head -1
curl: (6) Could not resolve host: roadmodel.ai
```

### Post-cut DNS + TLS

```text
$ dig A roadmodel.ai +short
76.76.21.21

$ curl -sSI https://roadmodel.ai | head -1
HTTP/2 200
```

TLS cert auto-issue did **not** fire on its own after the A record
propagated (Vercel's initial verify happened ~1h before DNS was set,
and the retry cadence was longer than the cut window). Manual nudge:

```text
$ vercel certs issue roadmodel.ai
Issuing a certificate for roadmodel.ai
> Success! Certificate entry for roadmodel.ai created [8s]

$ echo | openssl s_client -servername roadmodel.ai \
    -connect 76.76.21.21:443 2>/dev/null \
    | openssl x509 -noout -subject -issuer -dates
subject=CN=roadmodel.ai
issuer=C=US, O=Let's Encrypt, CN=R12
notBefore=May 20 03:32:32 2026 GMT
notAfter=Aug 18 03:32:31 2026 GMT
```

For future apex cuts where DNS is set *after* the domain is attached,
run `vercel certs issue <domain>` immediately rather than waiting for
the auto-retry.

### Staging reference (stack healthy pre-apex cut)

```text
$ dig CNAME staging.roadmodel.ai +short
6414f72d9e02a5d3.vercel-dns-016.com.

$ curl -sSI https://staging.roadmodel.ai | head -1
HTTP/2 200

$ cd web
$ PLAYWRIGHT_BASE_URL=https://staging.roadmodel.ai npx playwright test --grep "home page"
  ✓  1 [chromium] › tests/home.spec.ts:4:5 › home page renders hero + CTA (215ms)
  1 passed (1.6s)

$ PLAYWRIGHT_BASE_URL=https://staging.roadmodel.ai npx playwright test --grep "renders form"
  ✓  1 [chromium] › tests/recommend.spec.ts:4:5 › /recommend renders form + empty output (98ms)
  1 passed (1.2s)
```

### Playwright smoke (`PLAYWRIGHT_BASE_URL=https://roadmodel.ai`)

```text
$ cd web
$ PLAYWRIGHT_BASE_URL=https://roadmodel.ai npx playwright test --grep "home page"
  ✓  1 [chromium] › tests/home.spec.ts:4:5 › home page renders hero + CTA (109ms)
  1 passed (2.6s)

$ PLAYWRIGHT_BASE_URL=https://roadmodel.ai npx playwright test --grep "renders form"
  ✓  1 [chromium] › tests/recommend.spec.ts:4:5 › /recommend renders form + empty output (94ms)
  1 passed (1.2s)
```

### Functional `/api/recommend` smoke

First request (expected HTTP 200, recommender wire schema):

```text
$ curl -X POST https://roadmodel.ai/api/recommend \
    -H "Content-Type: application/json" \
    -d '{"task_description": "build a SQL agent"}'
{"model":"Composer 2","platform":"Cursor","settings":{"max_mode":"OFF","thinking":"N/A"},"session_cost_estimate":null,"comparison_table":[]}
HTTP 200 time=6.612247s
```

Note on cold starts: the upstream Python FastAPI service
(`roadmodel-api.vercel.app/v1/recommend`) can take 27–30 s on a fully
cold start, which exceeds the Next Route Handler default timeout. Warm
calls complete in 6–7 s. Tracked as a Phase 4 perf item (provision a
cron warm-up or migrate off cold-start runtime).

Note: the FastAPI wire schema returns `model`, `platform`, `settings`,
`session_cost_estimate`, and `comparison_table`. The UI renders the
free-tier badge client-side (`Free tier (Haiku 4.5) — upgrade for
frontier models` in `web/components/RecommendOutput.tsx`); it is not
a field on the JSON payload today.

Rate-limit sequence (requires Upstash seeded on production — Step 0):

```text
# Sequence captured 2026-05-20 from a single source IP+UA.
# Limit: 3/day per salted IP+UA hash (also 10/min burst).
# Note: a curl --max-time 20 abort still counts at the Upstash
# increment (which happens before the upstream Python call).

# Request 1 — server completed (Python cold start ~27 s), curl gave up
HTTP 000 time=20s (timed out; counted as 1)

# Request 2 — likewise a slow upstream, curl gave up at 30 s
HTTP 000 time=30s (timed out; counted as 2)

# Request 3 — rate-limit decision: window already exhausted
$ curl -X POST https://roadmodel.ai/api/recommend ...
{"error":"rate_limited","retry_after":31615}
HTTP 429 time=0.368s

# Request 4 — same
{"error":"rate_limited","retry_after":31615}
HTTP 429 time=0.244s
```

The `retry_after` ~31 615 s ≈ 8.8 h aligns with the daily window. Live
rate limiting is now **enforced** (previously fail-open across all
scopes per the [Step 6.1 carry-over](../private/ROADMAP.md)).

## release.yml pattern check

Confirm the tag-push path does **not** republish to PyPI for
`*-phase-*` milestone tags:

```bash
grep -A5 "^on:" .github/workflows/release.yml
```

Output (2026-05-20):

```text
on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
```

The trigger matches any `v*` tag (including `v0.3.0-phase-3`), but
`testpypi-upload` and `verify-testpypi` carry an explicit guard:

```yaml
if: ${{ github.event_name == 'push' && !contains(github.ref_name, '-phase-') }}
```

`pypi-upload` and `github-release` run only on `workflow_dispatch`.
Pushing `v0.3.0-phase-3` therefore executes `build` + `sign` at
most — **no TestPyPI or PyPI publish**. Safe to push the milestone
tag.

## Rollback procedure

If a critical issue surfaces after the apex cut, revert DNS within
~5 minutes:

1. In Namecheap Advanced DNS for `roadmodel.ai`, **delete** the apex
   ALIAS / ANAME record pointing at `76.76.21.21`.
2. Optionally restore the prior parked-page redirect if needed for
   registrar compliance (not required for NXDOMAIN rollback).
3. Wait for TTL expiry (300s on the apex row). Verify:

   ```bash
   dig A roadmodel.ai +short   # expect empty / NXDOMAIN
   curl -sSI https://roadmodel.ai  # expect resolution failure
   ```

4. `staging.roadmodel.ai` is unaffected — it remains the fallback URL
   until the apex is re-provisioned.
5. Pause the production UptimeRobot monitor; staging monitor
   `803092893` continues watching the staging URL.

## Phase 3 closing notes

**What Phase 4 inherits**

- Live production ingress at `https://roadmodel.ai` (marketing home +
  `/recommend`).
- Next.js Route Handler at `/api/recommend` with Upstash rate limiting
  (10/min burst, 3/day per salted IP+UA hash) and Supabase audit-log
  writes (`infra/supabase/migrations/20260601000000_audit_log.sql`).
- Vercel `roadmodel-web` + `roadmodel-api` stack; FastAPI recommender
  on `roadmodel-api.vercel.app/v1/recommend`.
- Provider-side cost ceilings documented in
  [docs/cost-ceilings.md](cost-ceilings.md) and
  [infra/README.md](../infra/README.md#provider-cost-ceilings).
- Staging custom env on `roadmodel-web` (`staging.roadmodel.ai`) for
  pre-production validation.

**Single open item carried forward**

- **Phase 7 application ledger** — the real-time per-provider token
  spend tracker that refuses calls before a daily ceiling. Provider-side
  caps ($450/mo aggregate) are the day-one floor; the application ledger
  strengthens but does not replace them (see
  [private/ROADMAP.md](../private/ROADMAP.md) Phase 7.1).

## Tag and GitHub Release

After the docs PR merges and the branch is retired, from clean
`main`:

```bash
git switch main
git pull --ff-only origin main
git tag -s v0.3.0-phase-3 \
  -m "Phase 3 — roadmodel.ai live with anonymous recommender"
git tag -v v0.3.0-phase-3   # confirm Good "git" signature
git push origin v0.3.0-phase-3
```

Create the GitHub Release:

```bash
gh release create v0.3.0-phase-3 \
  --title "Phase 3 — roadmodel.ai live" \
  --notes-file /tmp/release-notes.md
```

Release notes template (`/tmp/release-notes.md`):

- Summary paragraph: `roadmodel.ai` is live with anonymous `/recommend`
  backed by Haiku 4.5 / Gemini Flash, rate-limited at 3/day per IP,
  with audit logs and provider-side cost ceilings as the day-one
  guardrail.
- Link: [ROADMAP.md Phase 3](../ROADMAP.md#phase-3--marketing-site-and-anonymous-web-recommender)
- Link: [docs/phase03-release-runbook.md](phase03-release-runbook.md)
- Link: https://roadmodel.ai
- Note: no PyPI release — OSS CLI `roadmodel` v0.2.0 unchanged from
  Phase 2.

## v0.3.0-phase-3 (Phase 3)

- **Tag:** `v0.3.0-phase-3` — pushed 2026-05-20 from `main@80ecf6c`;
  SSH-signed by maintainer.
- **GitHub Release:**
  [Phase 3 — roadmodel.ai live](https://github.com/nathanramoscfa/roadmodel/releases/tag/v0.3.0-phase-3)
  (created 2026-05-20).
- **Tag-push `release.yml` run:**
  [Actions run 26173958719](https://github.com/nathanramoscfa/roadmodel/actions/runs/26173958719)
  — `build` ✓, `sign` ✓; `testpypi-upload`, `verify-testpypi`,
  `pypi-upload`, `github-release` all `skipped` as designed
  (`-phase-` guard + `workflow_dispatch`-only gates). No PyPI
  republish; OSS CLI `roadmodel` v0.2.0 unchanged.
- **Production URL:** https://roadmodel.ai
- **UptimeRobot production monitor:** [`803118024`](https://dashboard.uptimerobot.com/monitors/803118024)
  — `https://roadmodel.ai`, 5-min interval, maintainer email channel.
  See [infra/README.md UptimeRobot monitors](../infra/README.md#uptimerobot-monitors).
