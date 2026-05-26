<!-- docs/phase04-latency-findings.md -->

# Phase 4 Step 7 — `/api/recommend` warm-path latency

This document captures the pre-fix baseline, the diagnosis, the
fixes applied (and the fixes deferred), and the post-fix
verification numbers for the Phase 3 warm-path latency gap on
the anonymous `/recommend` flow. The doc is written
incrementally across the Step 7 PRs: PR 7a lands the
methodology and instrumentation kit; PR 7b paste-fills baseline
+ diagnosis + fixes; PR 7c paste-fills post-fix numbers.

## Methodology

### Sample size and window

- ≥ 50 requests per sweep over a 10-minute window
  (`--requests 50 --window-seconds 600`).
- Invocation (the cd into `web/` picks up `@supabase/supabase-js`,
  which lives in `web/node_modules` — there is no root
  `package.json`):

  ```bash
  cd web
  pnpm tsx ../scripts/measure-recommend-latency.ts \
      --target https://roadmodel.ai \
      --requests 50 --window-seconds 600
  ```
- Deterministic round-robin across three representative prompts
  baked into `scripts/measure-recommend-latency.ts` (creative
  writing, coding, planning) so reruns are directly comparable.
- All sweeps run against the production deployment at
  `https://roadmodel.ai` unless otherwise noted.

### Percentiles

- P50, P95, P99 reported for every span in
  `audit_log.latency_ms`. The script computes them client-side
  via a 0-indexed integer-floor percentile over the sorted
  values; n is the count of rows where the span was recorded.
- Client-side wall-clock P50 / P95 / P99 is reported alongside
  the server-side breakdown so we can detect divergence (e.g.
  TLS handshake / network jitter dominating any specific layer).

### Spans

The web-tier route handler records four spans:

| Span | What it covers |
| --- | --- |
| `dispatch_ms` | Input parse, profile load, engine resolve. |
| `provider_ms` | Wall-clock around the upstream FastAPI fetch. |
| `render_ms` | JSON parse, jurisdiction filter, response assembly. |
| `scoring_ms` | Local audit-row assembly (kept for naming symmetry; ~0ms in practice). |

The FastAPI service emits `X-Roadmodel-Timing` with two keys,
which the web tier ingests to decompose `provider_ms`:

| Span | What it covers |
| --- | --- |
| `service_scoring_ms` | FastAPI request validation + fallback-chain walking + response model assembly. |
| `service_provider_ms` | `roadmodel.recommend.recommend_structured` — the Gemini Flash call. |

`total_ms` is the wall-clock from the earliest span start to
the latest span end. `cold_start_ms` is `0` for warm calls and
the gap between Node.js module-evaluation time and the request
start for the first request after a cold boot.

### Bypass-token mechanism

The maintainer-run sweep would be throttled by the Phase 3 Step 6
fail-closed rate limiter (10 req/min burst, 3 req/day daily).
Step 7 ships a temporary env-gated bypass to make the 50-request
sweep possible:

- `ROADMODEL_LATENCY_BYPASS_TOKEN` — set on the Vercel
  production scope to a random 32-byte hex string.
- The measurement script sends the value in an
  `X-Roadmodel-Bypass` request header.
- `web/lib/withRateLimit.ts` does a constant-time comparison
  against the env-var value; on match it audits the request as
  `bypassed_rate_limit` and skips the Upstash check.
- The bypass is **gated on env-var presence** — without the env
  var the header is ignored entirely. There is no fail-open
  default.
- The bypass (env var, withRateLimit branch, and the
  `bypassed_rate_limit` audit outcome) is removed in PR 7c.

### Environment

- Both tiers run on Vercel Fluid Compute (`service/railway.json`
  is legacy and is deleted in PR 7c).
- The recommender Gemini call lives inside the FastAPI service,
  not the web tier; `service/app/recommend.py` calls
  `roadmodel.recommend.recommend_structured` from the bundled
  `roadmodel` package.

## Budget

Per `ROADMAP.md` §4.7 the warm-path budget is:

| Metric | Target |
| --- | --- |
| P50 | ≤ 3000 ms |
| P95 | ≤ 5000 ms |

Cold-start budget is tracked separately below.

## Baseline (pre-fix)

> **PR 7a:** maintainer runs the sweep with the instrumentation
> kit and pastes the markdown output here. Paste the script's
> table verbatim (the script writes a copy-pastable form), then
> add a one-paragraph narrative below the table calling out the
> dominant span.

<!-- TODO(PR 7a): paste sweep output -->

## Diagnosis

> **PR 7b:** with the baseline numbers in hand, walk through the
> Step 7 decision rubric and document what each fix candidate's
> baseline-derived trigger condition was, and whether it fired.
>
> Decision rubric (recap):
>
> - **Token cap (1024):** apply if baseline
>   `service_provider_ms` P50 > 2000ms.
> - **Parallel fan-out:** apply if baseline
>   `service_scoring_ms` P50 > 500ms AND inspection of
>   `src/roadmodel/recommend.py` confirms per-row I/O in the
>   comparison loop.
> - **Keep-alive cron:** apply if baseline `cold_start_ms`
>   P95 > 8000.

<!-- TODO(PR 7b): rubric walkthrough -->

## Fixes applied

> **PR 7b:** list the fixes that landed plus the version /
> config bump that carried each one (e.g. `roadmodel` PyPI patch
> release version, `service/pyproject.toml` pin range, Vercel
> Cron `crons[]` entry).

<!-- TODO(PR 7b): applied-fix log -->

## Fixes deferred

> **PR 7b:** for each candidate fix the rubric did NOT trigger,
> write a short rationale citing the baseline number and link
> a GitHub issue tracking the future-work candidate.

<!-- TODO(PR 7b): deferred-fix log -->

## Post-fix

> **PR 7c:** maintainer re-runs the sweep against the
> deployment that contains the PR 7b fixes and pastes the
> markdown table here. Annotate any span that improved by more
> than 20% with the underlying fix. If P95 misses budget, do
> NOT iterate inside PR 7c — open a GitHub issue tagged
> `phase04-step7d-latency-followup` and file PR 7d as a
> follow-up step.

<!-- TODO(PR 7c): paste sweep output -->

## Cold-start budget

> **PR 7b / 7c:** document the cold-start P50 / P95 / P99 from
> the baseline + post-fix sweeps separately from the warm-path
> table above. The keep-alive cron fix decision keys on the P95
> here, not the warm-path P95.

<!-- TODO(PR 7b/7c): cold-start summary -->

## Future work

> **PR 7c:** list every candidate that was investigated but
> deferred (with the issue link), plus any new findings the
> sweep surfaced that aren't in scope for Phase 4 Step 7.

<!-- TODO(PR 7c): future-work log -->
