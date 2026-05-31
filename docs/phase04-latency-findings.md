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
- Invocation (the keychain wrapper exports all eight production
  secrets from the macOS login keychain so no values are pasted
  inline; `NODE_PATH` is set so tsx — invoked from outside `web/` —
  can resolve `@supabase/supabase-js` from `web/node_modules`):

  ```bash
  NODE_PATH=/Users/nathanramos/roadmodel/web/node_modules \
  scripts/with-prod-secrets.sh node web/node_modules/.bin/tsx \
      scripts/measure-recommend-latency.ts \
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

**Sweep run 2026-05-31** — 50 requests issued over a 600-second
window against `https://roadmodel.ai/api/recommend`. All 50
returned `200`; 48 audit rows had a usable `latency_ms` JSONB
(two rows lost — the first cold-start writes likely did not flush
to `audit_log` before the script's 10-second settle window ended).

| Span                  | P50 (ms) | P95 (ms) | P99 (ms) | n  |
| --------------------- | -------- | -------- | -------- | -- |
| `total_ms`            |   17,080 |   31,530 |   39,884 | 48 |
| `dispatch_ms`         |        2 |       10 |       25 | 48 |
| `scoring_ms`          |        0 |        0 |        0 | 48 |
| `provider_ms`         |   17,078 |   31,526 |   39,881 | 48 |
| `service_scoring_ms`  |        0 |        0 |        0 | 48 |
| `service_provider_ms` |   17,014 |   31,462 |   39,854 | 48 |
| `render_ms`           |        0 |        0 |        0 | 48 |
| `cold_start_ms`       |        0 |        0 |       40 | 48 |

Client-side wall clock: P50 17,805 ms / P95 31,901 ms / P99 40,005 ms.

**The dominant span is unambiguous.** `service_provider_ms` accounts
for **99.6 %+ of `total_ms`** at every percentile. The Gemini Flash
call inside the FastAPI service is the only span large enough to
matter; the web-tier dispatch (2 ms P50), web-tier scoring (~0 ms),
web-tier render (~0 ms), the FastAPI service-tier scoring (~0 ms),
and cold-start (~0 ms warm, 40 ms P99 — well below the 8,000 ms
keep-alive trigger) are all noise relative to the provider call.
Warm-path P50 is **5.7× over** the ≤ 3,000 ms budget; warm-path P95
is **6.3× over** the ≤ 5,000 ms budget.

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

Applying the Step 7 rubric to the 2026-05-31 baseline:

| Candidate fix          | Trigger condition                                                              | Baseline               | Verdict      |
| ---------------------- | ------------------------------------------------------------------------------ | ---------------------- | ------------ |
| **Token cap (1024)**   | `service_provider_ms` P50 > 2,000 ms                                           | 17,014 ms (8.5× over) | **APPLY**    |
| **Parallel fan-out**   | `service_scoring_ms` P50 > 500 ms AND per-row I/O in the comparison loop       | 0 ms                   | **DEFER**    |
| **Keep-alive cron**    | `cold_start_ms` P95 > 8,000 ms                                                 | 0 ms (P99: 40 ms)      | **DEFER**    |

The token-cap rubric fires by a factor of 8.5×. The other two rubrics
do not fire — the FastAPI service's local scoring is sub-millisecond
(no per-row I/O is in play for the Phase 4 static catalog, matching
the original Step 7 spec's "mark as 'not applicable for Phase 4
catalog' in the findings doc rather than shipping no-op parallelism"
guidance), and cold-start latency is well inside the keep-alive
threshold (P99 40 ms is two orders of magnitude under the 8,000 ms
trigger; the Vercel Fluid Compute warm-instance reuse from the Phase
3 → Phase 4 migration ([[project-full-vercel-migration]]) absorbs
cold-start cost).

**Why the dominant span is the Gemini call.** Phase 3 Step 5.5b
swapped the recommender to Gemini 2.5 Flash for cost discipline, but
the call site at `src/roadmodel/providers/google.py:20` passes no
`max_output_tokens` so the SDK default of 8,192 applies. Real
recommender responses (the six-field block plus rationale) fit well
under 1,024 tokens in practice. The provider is generating ~8× the
output it needs to, and decode-time dominates the wall clock at this
output ratio. This is exactly the failure mode the original Step 7
spec called out as candidate fix #1.

## Fixes applied

> **PR 7b:** list the fixes that landed plus the version /
> config bump that carried each one (e.g. `roadmodel` PyPI patch
> release version, `service/pyproject.toml` pin range, Vercel
> Cron `crons[]` entry).

**Token cap (1024) — landed in `roadmodel` 0.2.1 + `roadmodel-service`
pin bump (this PR, Phase 4 Step 7b).**

- Added optional `max_output_tokens: int | None` keyword to
  `roadmodel.recommend.recommend`, `recommend_structured`, and the
  `ProviderAdapter` Protocol. Threaded through all three bundled
  providers:
  - `providers.google` → forwarded as `config.max_output_tokens` to
    `client.models.generate_content`.
  - `providers.anthropic` → forwarded as `max_tokens` (replaces the
    prior hardcoded `4096` when set).
  - `providers.openai` → forwarded as `max_output_tokens` to the
    Responses API.
- `roadmodel-service` now passes `max_output_tokens=1024` from
  `service/app/recommend.py` via a module-level constant
  (`_RECOMMENDER_MAX_OUTPUT_TOKENS = 1024`) with an inline comment
  citing the baseline P50 of 17,014 ms.
- Package version bumped `0.2.0` → `0.2.1` (patch SemVer — additive
  optional keyword, behavior unchanged when unset).
  `service/pyproject.toml` pin updated to `roadmodel>=0.2.1,<0.3`.
- Unit test `tests/test_provider_max_output_tokens.py` asserts the
  keyword is propagated to every SDK call (monkey-patched fakes
  capture kwargs and check `max_output_tokens` is present when
  passed and absent when omitted, with the Anthropic prior `4096`
  default preserved). Per
  [[feedback-monkeypatched-contract-validation]] the suite also
  includes a drift guard that `inspect.signature` validates each
  provider's `recommend` continues to accept the keyword.
- PyPI publish via the existing OIDC Trusted Publishing path
  ([[project-pypi-publish-oidc]]) — `git tag -s v0.2.1` from `main`
  after this PR squash-merges; `release.yml` handles the upload.
  `roadmodel-service` redeploys on Vercel automatically from `main`
  on the same merge.

**Expected impact.** Capping output at 1,024 tokens should reduce
the dominant span (`service_provider_ms`) by roughly the same ratio
as the over-allocation — 8,192 / 1,024 = 8×. If decode-time scales
linearly with output budget allocation, P50 could drop from
~17,000 ms to ~2,000–3,000 ms, putting the warm path inside or
near budget. Empirical post-fix sweep numbers land in PR 7c.

## Fixes deferred

> **PR 7b:** for each candidate fix the rubric did NOT trigger,
> write a short rationale citing the baseline number and link
> a GitHub issue tracking the future-work candidate.

**Parallel fan-out — not applicable for the Phase 4 catalog.**
Baseline `service_scoring_ms` P50 is 0 ms — well below the 500 ms
trigger. Inspection of `src/roadmodel/recommend.py` confirms the
comparison loop (via `cost.compare_alternatives_funding_rank` at
`src/roadmodel/recommend.py:176`) is deterministic cost arithmetic
over a static bundled catalog with no per-row I/O. There is no
work to parallelize on the FastAPI side; the per-row I/O premise
the rubric assumes is absent for the Phase 4 catalog. Shipping
no-op parallelism (concurrent futures wrapping pure-CPU loops)
would add complexity for no measurable benefit. Re-evaluate if
Phase 5+ introduces a comparison-table source that requires
network or DB lookups per row.

**Keep-alive cron — not needed.** Baseline `cold_start_ms` P95 is
0 ms and P99 is 40 ms, two orders of magnitude below the 8,000 ms
trigger. Vercel Fluid Compute warm-instance reuse
([[project-full-vercel-migration]]) is doing the work the cron
would have done. A keep-alive cron at 24 × 12 = 288 invocations/day
would burn provider-side compute (and the Hobby cron quota) for no
measurable user-facing win at current traffic. Re-evaluate if
post-launch traffic ([[project-site-pre-launch-gate]]) develops a
long-tail of cold instances during off-peak hours.

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

**Baseline (pre-fix, 2026-05-31):** `cold_start_ms` P50 = 0 ms,
P95 = 0 ms, P99 = 40 ms. The 50-request sweep observed at most one
cold-start event (the very first request, written to one of the
two audit rows that did not flush in time). All other requests
hit warm Vercel Fluid Compute instances. The keep-alive trigger
(`cold_start_ms` P95 > 8,000 ms) does not fire.

Post-fix numbers land in PR 7c with the rest of the post-fix
sweep.

## Future work

> **PR 7c:** list every candidate that was investigated but
> deferred (with the issue link), plus any new findings the
> sweep surfaced that aren't in scope for Phase 4 Step 7.

<!-- TODO(PR 7c): future-work log -->
