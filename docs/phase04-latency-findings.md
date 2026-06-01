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

**Re-baseline 2026-05-31 (post-#131, clean anchor) — issue #132.**
The sweep above was captured mid-incident-churn (between the PR #127
cap add and the PR #131 recovery). After production settled at
`roadmodel` 0.2.2 (no cap, thinking on — the same config the original
baseline measured), a fresh 50-request / 600 s sweep against
`https://roadmodel.ai/api/recommend` (all 50 → `200`, 48 audit rows)
gives the stable anchor for any future thinking-off A/B:

| Span                  | P50 (ms) | P95 (ms) | P99 (ms) | n  |
| --------------------- | -------- | -------- | -------- | -- |
| `total_ms`            |   13,083 |   19,267 |   21,090 | 48 |
| `dispatch_ms`         |        2 |        6 |       24 | 48 |
| `scoring_ms`          |        0 |        0 |        0 | 48 |
| `provider_ms`         |   13,081 |   19,264 |   21,087 | 48 |
| `service_scoring_ms`  |        0 |        0 |        0 | 48 |
| `service_provider_ms` |   13,042 |   19,208 |   21,048 | 48 |
| `render_ms`           |        0 |        0 |        0 | 48 |
| `cold_start_ms`       |        0 |        0 |       39 | 48 |

Client-side wall clock: P50 13,037 ms / P95 19,379 ms / P99 21,209 ms.

The absolute numbers are lower than the original baseline, but the
config is identical (uncapped, thinking on), so the delta is Gemini
response-length variance (thinking tokens 1,580–2,487 and visible
response 207–23,363 across the #132 probes), **not** a real
improvement — do not read it as progress. The structural conclusion
is unchanged and, if anything, firmer: warm-path **P50 13,042 ms is
4.3× over** the ≤ 3,000 ms budget and **P95 19,208 ms is 3.8× over**
the ≤ 5,000 ms budget, with `service_provider_ms` still ~99.7 % of
`total_ms`. The gap is entirely the Gemini call; the lever remains the
thinking budget (see Diagnosis correction and Future work).

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
| **Token cap (1024)**   | `service_provider_ms` P50 > 2,000 ms                                           | 17,014 ms (8.5× over) | **~~APPLY~~ SUPERSEDED — see correction below; the lever is the thinking budget, not the token cap (#132)** |
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
the call site at `src/roadmodel/providers/google.py` passes no
`max_output_tokens` so the SDK default applies. The provider is
spending most of its decode time on **reasoning tokens**, not the
visible answer — see the correction below.

> **Correction (2026-05-31, issue #132).** The premise in the
> original draft of this section — that "real recommender responses
> fit well under 1,024 tokens, so a 1,024 cap reclaims ~8× of wasted
> output" — was **wrong**, and acting on it caused a ~4-hour
> production outage (every `/api/recommend` 500'd; see
> [[project-parser-selector-drift-incident]] and the package-level
> root cause in [[project-gemini-flash-thinking-budget]]). The real
> mechanism: **Gemini 2.5 Flash has thinking ON by default, and
> `max_output_tokens` is a _combined_ cap (thinking tokens + visible
> response).** Thinking is decoded first. At cap=1,024 roughly 980
> tokens were spent on thinking and only ~40 were left for the
> visible block, so the response truncated below the parser threshold
> and raised `MalformedResponseError`. The cap *value* was never the
> fix; **the thinking budget is the lever.** The diagnosis table's
> "Token cap (1024) → APPLY" verdict is superseded accordingly.

## Fixes applied

> **PR 7b:** list the fixes that landed plus the version /
> config bump that carried each one (e.g. `roadmodel` PyPI patch
> release version, `service/pyproject.toml` pin range, Vercel
> Cron `crons[]` entry).

**Token cap (1024) lands in two PRs — package release in 7b-a
(this PR), service uptake in 7b-b (follow-up after PyPI publish).**

The fix requires a chicken-and-egg-aware split:

- *PR 7b-a (this PR)* ships the `roadmodel` 0.2.1 package release:
  optional `max_output_tokens: int | None` keyword on
  `roadmodel.recommend.recommend`, `recommend_structured`, and the
  `ProviderAdapter` Protocol, threaded through all three bundled
  providers:
  - `providers.google` → forwarded as `config.max_output_tokens` to
    `client.models.generate_content`.
  - `providers.anthropic` → forwarded as `max_tokens` (replaces the
    prior hardcoded `4096` when set).
  - `providers.openai` → forwarded as `max_output_tokens` to the
    Responses API.

  Package version bumped `0.2.0` → `0.2.1` (patch SemVer; additive
  optional keyword, behavior unchanged when unset). Unit test
  `tests/test_provider_max_output_tokens.py` asserts propagation
  across every SDK call (monkey-patched fakes capture kwargs and
  check `max_output_tokens` is present when passed and absent when
  omitted, with the Anthropic prior `4096` default preserved). Per
  [[feedback-monkeypatched-contract-validation]] the suite also
  includes a drift guard that `inspect.signature` validates each
  provider's `recommend` continues to accept the keyword.

  PyPI publish via the existing OIDC Trusted Publishing path
  ([[project-pypi-publish-oidc]]) — `git tag -s v0.2.1` from `main`
  after this PR squash-merges; `release.yml` handles the upload.

- *PR 7b-b (this PR)* bumps `service/pyproject.toml` pin to
  `roadmodel>=0.2.1,<0.3` and passes `max_output_tokens=1024` from
  `service/app/recommend.py` via a module-level constant
  (`_RECOMMENDER_MAX_OUTPUT_TOKENS = 1024`) with an inline comment
  citing the baseline P50 of 17,014 ms. Required the prior 7b-a
  PR's tag-push to complete the OIDC publish to PyPI before the
  Vercel `roadmodel-api` deploy could install 0.2.1 (the chicken-
  and-egg the split was designed around).

**Expected impact (as predicted at PR 7b — SUPERSEDED).** Capping
output at 1,024 tokens should reduce the dominant span
(`service_provider_ms`) by roughly the same ratio as the
over-allocation — 8,192 / 1,024 = 8×. If decode-time scales linearly
with output budget allocation, P50 could drop from ~17,000 ms to
~2,000–3,000 ms, putting the warm path inside or near budget.

> This prediction was **wrong** and the cap was reverted the same day.
> It assumed `max_output_tokens` bounded only the visible response;
> in fact it is a combined thinking + response cap and the prediction
> ignored Gemini's default thinking budget entirely. See the
> correction under Diagnosis and the Post-fix diagnostic sweep (#132).

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

**Post-fix sweep 2026-06-01 — `thinking_budget=0` shipped (issue #132).**
The fix that landed is NOT a `max_output_tokens` cap (that reverted
approach is preserved in the diagnostic sweep below). `roadmodel` 0.2.3
(PR #141) added an optional `thinking_budget` keyword to the Google
provider; the service passes `thinking_budget=0` on the Gemini path
(PR #144), disabling Gemini 2.5 Flash's default reasoning — the
dominant latency term. Production was confirmed at `roadmodel` 0.2.3
(`/healthz`) before the sweep. 50 requests / 600 s window against
`https://roadmodel.ai/api/recommend`; all 50 → `200`.

| Span                  | Baseline P50 | **Post-fix P50** | Baseline P95 | **Post-fix P95** | Budget        |
| --------------------- | ------------ | ---------------- | ------------ | ---------------- | ------------- |
| `service_provider_ms` | 13,042 ms    | **1,627 ms**     | 19,208 ms    | **11,084 ms**    | P50 ≤ 3,000 / P95 ≤ 5,000 |
| `total_ms`            | 13,083 ms    | 1,724 ms         | 19,267 ms    | 11,130 ms        | —             |

Client-side wall clock: P50 1,960 ms / P95 11,356 ms / P99 13,389 ms.

**Verdict: P50 budget MET (8.0× faster, 13,042 → 1,627 ms); P95 budget
still MISSED (11,084 ms vs ≤ 5,000).** The per-request distribution is
sharply **bimodal**: 37 of 50 requests cluster at 1.3–2.7 s (well inside
budget), then a cliff to a slow tail of 13 requests at 4.6–13.4 s. The
tail is not cold-starts (`cold_start_ms` P95 = 16 ms) and not a specific
output platform (the slow rows span Cursor / Claude Code / claude.ai
picks). It is **Gemini 2.5 Flash's own residual generation variance**:
`thinking_budget=0` removes the reasoning term that dominated the median,
but Flash still occasionally takes 5–13 s to emit the visible block
(longer rationales on complex planning prompts). More budget tuning
cannot close this — the lever for the P95 tail is different (smaller
system prompt, prompt caching, or streaming), tracked as a follow-up.

**Quality held.** Spot-checked recommendations remained defensible with
thinking off — e.g. a Python-CLI coding prompt returned `gpt-5.3-codex`
on Codex (an A/S-tier coding pick), matching the thinking-off picks seen
in the pre-fix diagnostic probe. No degradation, no parse failures
(50/50 `200`).

The §4.7 budget had **two** criteria; one is now met and one is not.
Per this section's own guidance ("if P95 misses budget, do NOT iterate
here — open a follow-up issue"), the residual P95 tail is filed
separately rather than chased by re-tuning the budget value.

### P95 tail follow-up 2026-06-01 — Gemini output cap (issue #146)

The residual P95 tail above was diagnosed as **runaway-`RATIONALE`
generation variance**: a local probe of the real recommender prompt at
`thinking_budget=0` measured normal visible output at **124–300 tokens**
across 8 representative prompts, with a single **4,125-token runaway** on
a complex-planning prompt — the exact bimodal tail. Because thinking is
now OFF, `max_output_tokens` is a pure visible-response cap (no reasoning
to consume it, unlike the 2026-05-31 incident), so bounding it caps the
longest generations. Truncation is **parser-safe**: the 6 required fields
(`MODEL`..`CONVERSATION`) are emitted first and `RATIONALE` is captured
lazily to end-of-string, so even a forced `cap=96` truncation still parses
with the pick preserved (verified). The cap is **Gemini-only** (never the
Anthropic path, #128).

Two production sweeps (50 req / 600 s window against
`https://roadmodel.ai/api/recommend`, all 50 → `200`) converged the cap:

| `service_provider_ms` | P50      | **P95**       | P99      | Budget        |
| --------------------- | -------- | ------------- | -------- | ------------- |
| thinking_budget=0 only (above) | 1,627 ms | 11,084 ms | — | P95 ≤ 5,000 |
| + `max_output_tokens=768` (PR #149) | 1,735 ms | 5,530 ms | 5,755 ms | ❌ (−530 ms) |
| + `max_output_tokens=512` (PR #150) | 1,661 ms | **3,968 ms** | 6,356 ms | ✅ **MET** |

768 collapsed the runaway tail (11,084 → 5,530 ms) but missed the budget
by ~530 ms — the cap-bound long generations landed at ~5.5–6.3 s. The
capped tail scales with token count (~187 tok/s decode + ~1.4 s base), so
**512** brought it to ~4.1 s. At 512 the distribution is 35/50 fast
(≤3 s), 14/50 mid (3.2–4.7 s, the former runaways), and a single 7.1 s
outlier (the P99 — irreducible Google-side server variance, **not**
cap-bound at 512). 512 is still ~1.7× the observed normal-output max, so
normal rationales are never clipped — only over-long ones are trimmed.

**Verdict: P95 budget MET (3,968 ms ≤ 5,000 ms); P50 stayed met
(1,661 ms).** Quality held: 50/50 `200`, no fallback, and an authenticated
spot-check on the complex-planning prompt returned `opus-4.8` on Claude
Code (XHigh) — a defensible A-tier planning pick. The residual P99 tail
(~6.4 s) is Gemini server variance below the P95 line; closing it further
would need a different lever (prompt caching / streaming), not a tighter
cap. **Issue #146 resolved.**

### Diagnostic sweep (2026-05-31, issue #132 — local, exploratory)

Run from a laptop (not production) against the live Gemini 2.5 Flash
API with the real recommender system prompt, to find why the cap
broke and what actually controls latency. 66 calls total. **These are
exploratory numbers over home-internet RTT, not a production budget
measurement** — treat the *relative* findings as solid and the
*absolute* milliseconds as indicative only.

`max_output_tokens` is a **combined** cap (thinking + visible
response); thinking decodes first:

| `max_output_tokens` (thinking on) | parse | thinking tok | response tok | finish reason |
| --------------------------------- | ----- | ------------ | ------------ | ------------- |
| 1024 | **0/6 FAIL** | ~980 | ~40 | MAX_TOKENS |
| 1536 | 6/6 | ~1473 | ~59 | MAX_TOKENS |
| 2048 | 6/6 | ~1962 | ~80 | MAX_TOKENS |
| 4096 | 6/6 | 1563–3002 | 147–1941 | STOP |
| none | 6/6 | 1580–2487 | 207–23363 | STOP |

This reproduces the incident exactly: at 1,024, thinking consumed the
budget and the visible block truncated → `MalformedResponseError`.

Latency by thinking budget (p50 over 9 samples each, **laptop RTT**):

| config | p50 (ms) | min (ms) | max (ms) | meets P50 ≤ 3,000? |
| ------ | -------- | -------- | -------- | ------------------ |
| thinking ON / no cap (≈ today) | 13,584 | 7,978 | 40,979 | ❌ |
| thinking 512 / cap 2048 | 7,806 | 3,847 | 12,430 | ❌ |
| thinking **OFF** / cap 2048 | 6,817 | 1,538 | 10,807 | ❌ (but ~2× faster) |

**No configuration met the 3 s P50 from a laptop.** Thinking-off is
~2× faster but still ~6.8 s p50 here; the absolute budget verdict can
only come from a production-side sweep (Vercel → Gemini). The robust
finding is directional: **disabling Gemini's default thinking is the
dominant lever** (≈ 2×), far more than any `max_output_tokens` value.

**Quality caveat — thinking changes the recommendation.** Picks were
stable *within* a config but differed *between* thinking-on and
-off on every test prompt (e.g. planning GPT-5.5 → Opus 4.8; creative
Opus 4.8 → Haiku 4.5). All picks were defensible with full, cited
rationales and zero parse failures, but they are **not identical**.
For a model *selector*, reasoning quality is part of the product, so
disabling thinking is a deliberate **quality ↔ latency tradeoff**, not
a free mechanical win.

**Not a provider-chain bug.** `service/app/recommend.py`'s
`_FALLBACK_CHAIN` lists Haiku first, but the web route forces the
Gemini provider via `context.force_provider`
(`web/app/api/recommend/route.ts` → `resolveRecommenderEngine` →
`pickFreeEngine`, pinned to `google-gemini-2.5-flash`), and the
service's `_provider_chain()` reorders to put the forced provider
first. Production is served by Gemini **by design**; Haiku-primary is
only the default for an *unforced* direct service call.
`ANTHROPIC_API_KEY` is set in production, consistent with that.

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

**Post-fix (2026-06-01):** `cold_start_ms` P50 = 0 ms, P95 = 16 ms,
P99 = 55 ms — still two orders of magnitude under the 8,000 ms
keep-alive trigger. The `thinking_budget=0` change did not affect
cold-start; warm Vercel Fluid Compute reuse continues to absorb it.

## Future work

> **PR 7c:** list every candidate that was investigated but
> deferred (with the issue link), plus any new findings the
> sweep surfaced that aren't in scope for Phase 4 Step 7.

**Remaining work to close the warm-path budget (issue #132):**

1. **Re-measure from production**, not a laptop. Run the documented
   50-request sweep (Methodology section) against `https://roadmodel.ai`
   with thinking still on, to get the true production baseline p50/p95
   for `service_provider_ms`.
2. **Decide the quality ↔ latency tradeoff.** If thinking-off is
   acceptable for the free-tier recommender (given the pick-stability
   data above), it is the highest-leverage change. If not, the warm
   path stays at baseline and the budget target is renegotiated.
3. **If proceeding with thinking-off:** expose `thinking_config` in
   `roadmodel.providers.google.recommend` (it currently exposes only
   `max_output_tokens`), release as `roadmodel` 0.2.3 via the OIDC
   path ([[project-pypi-publish-oidc]]), bump the service pin, and
   apply it **Gemini-only** (never the Anthropic fallback, per PR #128).
   A `max_output_tokens` of ~2,048 is a safe companion cap *only* with
   thinking off (it must not be set with thinking on — that is the
   incident). Then run the production post-fix sweep and paste it into
   the Post-fix section above.

The PyPI publish in step 3 requires explicit maintainer authorization
(same gate as 0.2.1 / 0.2.2). Until then, production runs uncapped
(SDK default) with thinking on — the known ~17 s warm-path regression,
which is a far smaller blast radius than 500s on every call.

**Deferred candidates (unchanged from the Diagnosis rubric):** parallel
fan-out (N/A for the static Phase 4 catalog — no per-row I/O) and the
keep-alive cron (cold-start P95 is ~0 ms; Fluid Compute warm-reuse
already covers it).
