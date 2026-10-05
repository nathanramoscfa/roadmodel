<!-- docs/phase0411-qa-findings.md -->
# Phase 4.11 — Visitor-funded recommendations: QA findings

Verification rollup for Phase 4.11. Static, web, service, security and live
checks are codified in
[`scripts/verify-phase0411.sh`](../scripts/verify-phase0411.sh); `--fast` and
`--security` run on every PR through the `0411` entry in
`.github/workflows/phase-verify.yml`, and the funding invariant is watched daily
by `.github/workflows/cron-health.yml`.

## What the phase delivered

Before this phase every signed-in user could spend roadmodel's provider keys.
Now each request to a paid route is assigned to exactly one funding lane before
any upstream call, and a request no lane funds is refused with `402`.

| Step | Outcome | PR |
| --- | --- | --- |
| **1** | Fail-closed funding lanes (`decideLane`), the invite list, the `funded_by` ledger column and the `audit_log` outcome CHECK realigned to the writer; `/api/roadmap` made fail-closed and metered. | #891 |
| **2** | Visitor keys, per request: header-only transport, one ladder call, no fallback, log redaction, a rejected-key limiter. | #909 |
| **3** | OpenRouter connect (PKCE) as a fourth visitor provider. | #912 |
| **4** | Keyless picks in code: `POST /v1/score` and the agreement eval (32 of 36, under-tier 0). | #918 |
| **5** | The keyless lane on `/recommend` (Quick pick) and "run it in your own agent". | #919 |
| **6** | `verify-phase0411.sh`, the live lane probe, the daily funding-invariant alarm, these docs. | (this PR) |

## Findings by step

Each row names the finding, its class, where it went, and the guard that stops
it recurring.

### Step 1 — funding lanes

| Finding | Class | Destination | Guard |
| --- | --- | --- | --- |
| **`audit_log` CHECK drift.** The live outcome CHECK listed five values while the writer's `AuditOutcome` union had grown to ten, so every `daily_cost_cap`, `bypassed_rate_limit`, `unauthorized` and `roadmap_*` row failed to insert, silently (audit writes are fire-and-forget). | Drift bug | Fixed in migration `20261002000000_audit_log_funded_by.sql` (drop by name, re-add all 14 values) and applied to production. | `tests/test_audit_log_migration.py` parses the CHECK in force and the TypeScript union and asserts they are equal. |
| **`/api/roadmap` exposure.** The builder was hidden by a page-level flag only; the API route answered any signed-in user at the operator's cost. | Security gap | Fixed in Step 1: the route answers 404 while `ROADMAP_ENABLED` is false, 402 to a signed-in caller on no list, and meters `cost_usd` when enabled. | `web/tests/funding-lane.spec.ts` (roadmap 404 and 402); static check 8. |
| **Browser `context` smuggling.** The request's `context` object reached the engine unfiltered (`force_provider`, funding fields). | Security gap | Fixed: allowlist in `web/lib/recommend-context.ts`. | Allowlist case in `funding-lane.spec.ts`. |
| **Roadmap metering undercounts Gemini thinking tokens.** The stream's usage omits them. | Accuracy limit | Judgement call in #891; the builder is off in production and the other lanes never touch it. Owned by the step that re-enables the builder. | Out of scope: "Re-enabling the roadmap builder". |
| **Migration trees.** The roadmap said "both trees"; `supabase/migrations` is a gitignored symlink to `infra/supabase/migrations`. | Spec rot | Corrected in the roadmap. | Static check 5 looks only in `infra/supabase/migrations`. |

### Step 2 — visitor keys

| Finding | Class | Destination | Guard |
| --- | --- | --- | --- |
| **Log redaction missed child loggers.** A filter on the root logger sees only records logged on the root itself. | Latent leak | Fixed: a `LogRecord` factory scrubs every record as it is created, plus the root filter. | Canary key appears zero times in `caplog` (`service/tests/test_visitor_endpoint.py`). |
| **The eval file is read by the service.** The service deploys from `service/` and cannot read `docs/engine-eval.json`. | Drift risk | Fixed: a mirrored `service/app/engine-eval.json`. | `tests/test_engine_eval_mirror.py`. |
| **Stale `/privacy` claims** (old provider names, an old limit). | Spec rot | Fixed in #909. | Static check 16. |
| **A declined key had no audit outcome.** | Design gap | Audited as `rate_limited` with `error_class: too_many_rejected_keys`; no migration needed. Recorded in the #909 body. | `visitor-key.spec.ts`. |

### Step 3 — OpenRouter connect

| Finding | Class | Destination | Guard |
| --- | --- | --- | --- |
| **OpenRouter answers exhausted credit with `402`**, which the text match missed. | Bug | Fixed: `402` is `visitor_quota` for every provider. | Status-mapping cases in `test_visitor_endpoint.py`. |
| **The key must survive an OAuth round trip without storage.** | Design | Module-memory, take-once handoff; never a cookie or storage. | `web/tests/openrouter-connect.spec.ts`. |
| **No reasoning dial reaches OpenRouter** (package entry is `reasoning: "none"`), the likely cause of the 12.8 s p50. | Performance | Issue **#921** (needs a package release and a floor bump). | Eval record in `docs/engine-eval.json`. |
| **First connect attempt showed "The recommender is unavailable" after a `200`.** | Bug | Issue **#916**. | — (tracked) |
| **Local Playwright hang** in the onboarding T2b spec. | Test infrastructure | Issue **#655** (local only). | `reuseExistingServer` stays off; `PLAYWRIGHT_PORT` for a busy `:3000`. |

### Step 4 — keyless scoring

| Finding | Class | Destination | Guard |
| --- | --- | --- | --- |
| **A textbook proof classified as novel** (math-proof, 1 of 3 rungs agree). | Quality | Issue **#917**. | The bar: `tests/test_keyless_eval_shape.py` pins agree ≥ 27 of 36 and under-tier 0 (current: 32 of 36, 0). |
| **Two more disagreements** (non-english, fenced-json: 2 of 3 rungs each) are the engine and the hand labels reading a task differently. | Measurement | Inside the bar; recorded per probe in `docs/keyless-eval.json` and stated on `/recommend` as the agreement sentence. | Same shape test. |
| **List items written into the scorer's Markdown could inject a line** (a newline, pipe or backtick in a provider list). | Injection | Fixed: id-shaped items, at most 64 of 64 characters. | Per-field validation tests in `test_score_endpoint.py`. |
| **A jurisdiction-only profile lost its jurisdictions** under the "empty profile" rule. | Bug | Fixed: those lines are passed, with no funding rows. | `test_score_endpoint.py`. |

### Step 5 — the keyless lane

| Finding | Class | Destination | Guard |
| --- | --- | --- | --- |
| **Step 6's check 24 assumed the route file holds the `/v1/score` literal.** It lives in `web/lib/service-url.ts` (`scoreUrl()`). | Spec rot | Fixed in the Step 6 task block; check 24 asserts `scoreUrl()` plus the single `/v1/score` path. | Static check 24. |
| **Signed-out visitors now open on Quick pick**, so free-text specs must choose a lane first. | Test change | `web/tests/fixtures/lanes.ts` (`openFreeText`, `chooseLane`). | `keyless-lane-ui.spec.ts`. |

## Step 6 — verify-script rollup

`scripts/verify-phase0411.sh` has 32 static checks (Steps 1–6) and a V1–V6
rollup in the layout of `verify-phase046.sh`. Modes: `--fast` (about 1 s),
`--web`, `--service`, `--security`, `--all`, `--post`.

| Finding | Class | Destination | Guard |
| --- | --- | --- | --- |
| **The production dependency audit failed.** `npm audit --omit=dev` reported 1 critical (Next.js: server-action DoS and SSRF, response-cache confusion, image-optimizer RCE) and 3 high advisories already on `main`. | Security | Fixed here: `npm audit fix` (next 15.5.19 → 15.5.27, sharp, protobufjs, nanoid, postcss) and an `overrides` entry for the postcss that Next vendors. Production audit: 0 vulnerabilities. Closes **#890**. | `--security` runs `npm audit --omit=dev --audit-level=high` on every PR. |
| **bandit flagged a fixed `/tmp` path** in `service/app/recommend.py`. | SAST | Fixed: inline-justified `# nosec B108` (the one writable path on Fluid Compute; public template content). | `--security` runs `bandit -r src/ service/app`. |
| **The roadmap's security block described a pre-commit secret scan that did not exist.** `.githooks/pre-commit` only guarded the branch. | Spec rot | Fixed: the hook also runs `gitleaks git --staged` (a missing binary is a notice, not a block). | Static check 32 asserts the hook runs gitleaks. |
| **The invariant as first specified would fire daily on legitimate rows.** The operator lane writes rows with no `funding_reason` and no spend: `rate_limited`, `burst_dropped`, `daily_cost_cap`, `bypassed_rate_limit`. | Spec rot | Fixed: the alarm judges operator rows that spent money (outcome `ok` or `cost_usd` above zero). Documented in `scripts/check_funding_invariant.py`. | `tests/test_funding_invariant.py` pins each case. |
| **`/api/roadmap` writes no `funding_reason`**, so once the builder is re-enabled the alarm would fire on every turn. | Latent alarm | Issue **#920**; owned by the step that re-enables the builder. | The alarm itself. |
| **`pip-audit` of the local venv reports its age, not the project's.** | Tooling | `--security` audits the declared dependencies of the root package and the service (`pip-audit .`, `pip-audit ./service`), independent of the venv. | `--security`. |
| **`:3000` is held by another local server**, so `--web` cannot start Playwright. | Local environment | `PLAYWRIGHT_PORT=3107 ./scripts/verify-phase0411.sh --web`. | `reuseExistingServer` stays off (it once adopted a stranger on `:3000`). |
| **`--post` needed the Upstash REST host.** The keychain holds the TCP-form URL. | Tooling | The probe keeps only the hostname and sends its own token. | `--post` run, below. |

### The live lane probe (V6.5)

`scripts/probe-funding-lanes.ts`, run on 2026-10-05 against production with
`./scripts/verify-phase0411.sh --post`:

| Probe | Lane | Result |
| --- | --- | --- |
| Signed-out free text | refused | `402` with options |
| The uninvited probe account (created and deleted by the probe) | refused | `402` |
| A bogus visitor key | visitor | `401 visitor_key_rejected` |
| An anonymous Quick pick | keyless | `200`, three rungs |
| The founder, no bypass header | operator | `200` |

The operator spend counter did not move across the first four probes. The
fifth wrote exactly one `funded_by = 'operator'` row, and the counter moved by
$0.006061, equal to that row's `cost_usd`. The probe account wrote no operator
row.

### The funding-invariant alarm (V6.6)

`scripts/check_funding_invariant.py` runs daily from `cron-health.yml`. Its
logic is covered by `tests/test_funding_invariant.py` (reasons, the anonymous
rule, refusals that spent nothing, paging past 1,000 rows, ids-only output).
The fire drill (a synthetic violating row, a failing run, the row removed, a
green run) is run by the maintainer with `scripts/drill-funding-invariant.sh`, because
it writes to the production ledger:

| Run | State of the ledger | Expected | Result |
| --- | --- | --- | --- |
| 1 | One synthetic violating row (`/__invariant-drill`) | `failure`, tracking issue opened or updated | _recorded below when the drill runs_ |
| 2 | Row deleted | `success`, tracking issue closed | _recorded below when the drill runs_ |

## Pre-ship items

These are not defects in this phase; each has an owner.

- **The invite list is empty in production.** `RECOMMEND_INVITED_USER_IDS` is
  unset, so the invited lane has no members until the first invitee signs in
  and the maintainer seeds the variable. Owner: the maintainer.
- **Phase 4 Step 8** may lift the pre-launch gate once Phase 4.5's quality bar
  is met. The lanes, caps and alarm above are what a public launch relies on.
- **Phase 8.1** owns provider-console hardening for the operator key (a
  dedicated project key for the web app, auto-recharge off, a per-key spend
  limit) and per-account dollar caps; **Phase 8.2** owns CAPTCHA and bot
  controls. Until then the rejected-key limiter is the minimum defense against
  using roadmodel to check stolen keys.
- **Phase 5** owns stored, encrypted keys and paid tiers. A paid subscription
  becomes one more way into the operator lane, under the same cap and alarm.
- **Issues carried:** #916, #917, #920, #921 and #655, each described above.
