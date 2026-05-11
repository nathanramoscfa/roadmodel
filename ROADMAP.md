# roadmodel — From Docs-as-Recommender to Simple SaaS

> **Status:** Draft v1
> **Owner:** Nathan Ramos, sole maintainer
> **Audience:** Internal (solo project) — public once Phase 4 ships
> **Target environment:** Local through Phase 3; managed cloud (TBD —
> Fly.io / Railway / Render for backend, Vercel for frontend) from
> Phase 4 onward
> **Last updated:** May 2026

This roadmap takes [roadmodel](README.md) from a pair of
hand-curated documents that an LLM consults during chat
(`@model-selector.txt`) to a small hosted web app where any visitor
can paste a prompt, slide a quality-vs-cost dial, and get back a
model recommendation grounded in the same source-of-truth docs.

The existing weekly refresh, schema tests, and auto-remediation
pipeline are not changed by this work — they continue to be the
authority on pricing and benchmarks. The SaaS reads from those docs;
it does not fork them.

---

## 1. Executive Summary

roadmodel is today a documentation project: two source-of-
truth files plus a weekly Opus 4.7 refresh that keeps prices and
benchmark numbers fresh, plus the two roadmap templates
([PROJECT_ROADMAP_TEMPLATE.md](docs/PROJECT_ROADMAP_TEMPLATE.md) and
[PHASE_ROADMAP_TEMPLATE.md](docs/PHASE_ROADMAP_TEMPLATE.md)) used in
tandem with `model-selector.txt` to plan AI-cost-aware projects. It
now needs to expose that workflow — paste a project brief, get back a
phased roadmap with a `MODEL / MAX MODE / CONVERSATION / RATIONALE`
block before every prompt — as a hosted web app, with a single-prompt
advisor mode as a secondary surface. The differentiated wedge is the
planning artifact: incumbents (Cursor Auto, OpenRouter, native
platform routing) handle one request at a time and do not generate a
shareable, cost-aware plan that spans N future prompts. Constraints:

1. **Source-of-truth invariance.** The SaaS reads `docs/` and never
   forks the data. The Monday refresh remains the only writer.
2. **Solo-operator economics.** Pilot infra under $50/month all-in
   (excluding Anthropic API usage, which scales with traffic).
3. **Staged rollout.** Each phase deploys and is verified before the
   next is built — no parallel layers in flight.
4. **Quality-first, cost-aware.** Default behavior matches today's
   "quality wins; cost only resolves true ties." A user-supplied
   weight in `[0.0, 1.0]` shifts the balance toward cost when set
   below the default.

The path: **extract → expose → ship UI → deploy → gate**. Each
phase is independently shippable. Phases 1–3 run locally at $0;
Phase 4 is the cutover to a public endpoint; Phases 5 and 6 are
gated on validation thresholds (see §4) before any account or
billing infra is built. Pricing strategy lives in §6;
projections live in [PRO_FORMA.md](PRO_FORMA.md).

---

## 2. Current State Assessment

### What works today

- `docs/model-selector.txt` — XML source of truth with every
  `<model>` element, tier ratings, headline benchmarks, and the
  prose `<selection-algorithm>`.
- `docs/model-tier-cost-scale.md` — full Cursor catalog with
  Input / Cache Write / Cache Read / Output prices and tier.
- `docs/model-selector.md` — auto-generated human-readable mirror
  of `.txt`, regenerated on every refresh.
- Weekly Opus 4.7 refresh ([update/update_models.py](update/update_models.py))
  keeps prices and benchmark numbers in sync with upstream.
- Three-tier test suite ([tests/](tests/)): live-source health,
  schema and cross-doc consistency, freshness heartbeat.
- Auto-remediation workflow opens a PR (or issue, after 3 failed
  attempts) when scheduled tests fail.

### Gaps blocking the SaaS destination

| #  | Gap                                                           | Severity |
|----|---------------------------------------------------------------|----------|
| 1  | Selection algorithm is prose; cannot be invoked from a server | Critical |
| 2  | No programmatic parser for `<model-options>` XML              | Critical |
| 3  | No prompt classifier — task category and complexity are       | Critical |
|    | inferred implicitly by the chat LLM today                     |          |
| 4  | No programmatic roadmap planner — the planning workflow       | Critical |
|    | depends on a chat LLM with the templates pasted in            |          |
| 5  | No quality-vs-cost weight parameter — cost is currently a     | High     |
|    | strict tie-breaker only                                       |          |
| 6  | No HTTP API surface                                           | High     |
| 7  | No web UI                                                     | High     |
| 8  | No hosted environment, no domain, no TLS                      | High     |
| 9  | No rate limiting or abuse controls                            | High     |
| 10 | No user accounts, API keys, or usage tracking                 | Medium   |
| 11 | No billing                                                    | Medium   |

These gaps drive the phase ordering below.

---

## 3. Target Architecture

```
        ┌──────────────────────────────────┐
        │  Visitor / browser               │
        └───────────────┬──────────────────┘
                        │ HTTPS
                        ▼
        ┌──────────────────────────────────┐
        │  Frontend (static SPA, Vercel)   │
        │  modes: roadmap | phase | prompt │
        └───────────────┬──────────────────┘
                        │ HTTPS / JSON
                        ▼
        ┌──────────────────────────────────┐
        │  Backend (FastAPI, managed PaaS) │
        │  /recommend  /annotate-roadmap   │
        │  /healthz  /models               │
        └────┬───────────────────┬─────────┘
             │                   │
             ▼                   ▼
   ┌──────────────────┐   ┌──────────────────┐
   │  Anthropic API   │   │  docs/ (read)    │
   │  Haiku: classify │   │  pinned to       │
   │  Sonnet: plan    │   │  main commit     │
   └──────────────────┘   └──────────────────┘

                        ┌──────────────────┐
   added in Phase 5 ──▶ │  Postgres        │  users, keys, usage
                        └──────────────────┘
                        ┌──────────────────┐
   added in Phase 6 ──▶ │  Stripe          │  subscriptions
                        └──────────────────┘
```

Region: TBD (single region — pick whichever the chosen PaaS defaults
to). The only public ingress is the frontend's static origin and
the backend's `/recommend` and `/healthz` endpoints. Anthropic is
the only outbound dependency through Phase 4.

---

## 4. Phased Roadmap

### Phase 1 — Extract the recommender into a Python library

**Goal:** Turn `<selection-algorithm>` from prose into executable
code that imports a parsed `<model-options>` and returns a
recommendation object, with a quality-vs-cost weight parameter.

**Complexity:** Medium · **Risk:** Low · **Cloud cost:** $0

#### 1.1 Parse the source-of-truth doc
- Add `app/recommender/parser.py` that reads
  `docs/model-selector.txt` and returns typed model entries
  (Pydantic): id, name, prices, per-category tier ratings, headline
  benchmarks, pricing notes, best-for.
- Reuse the same XPath / regex patterns the schema test
  ([tests/test_doc_schema.py](tests/test_doc_schema.py)) already
  validates against — single source of truth for the shape.

#### 1.2 Implement the selection algorithm in code
- Port steps 1–6 of `<selection-algorithm>` to
  `app/recommender/select.py`.
- Inputs: `task_primary`, `task_secondary`, `complexity_overall`,
  `quality_weight ∈ [0.0, 1.0]`.
- Default `quality_weight = 1.0` reproduces today's behavior:
  filter by minimum tier, rank by tier, cost only on true ties.
- For `quality_weight < 1.0`, replace the strict tie filter with a
  scored ranking:
  `score = quality_weight · tier_score + (1 − quality_weight) · cost_score`
  where `tier_score` maps S/A/B/C/D → 5/4/3/2/1 and `cost_score` is
  the inverse of `output-price-per-1m` normalized to `[0, 1]` over
  the candidate set.

#### 1.3 Encode the guardrails as code
- Multimodal-only filter (S/A in `tier-multimodal`).
- Long-context preference for native large-context models.
- Coding S-tier candidate set.
- Default to `composer-2` when coding-A suffices.

#### 1.4 Unit tests
- Add `tests/test_recommender.py` with eyeball-tested fixtures: at
  least one fixture per task category, plus one fixture per
  guardrail. Each fixture pins (prompt, expected_model,
  expected_max_mode) and asserts deterministic output.
- Sweep `quality_weight ∈ {0.0, 0.25, 0.5, 0.75, 1.0}` on a single
  high-complexity coding fixture and snapshot the recommendation
  curve.

**Acceptance criteria**
- `pytest tests/test_recommender.py -v` passes locally.
- Calling `recommend(prompt_meta, quality_weight=1.0)` reproduces
  the recommendations from the existing chat workflow on at least
  five hand-picked prompts.
- Lowering `quality_weight` to `0.0` on a coding-S prompt selects
  the cheapest coding-A or better candidate, never a coding-D.
- The library has zero network dependencies — classification is
  passed in by the caller.

---

### Phase 2 — Wrap the library in a local HTTP API

**Goal:** Stand up a FastAPI service that accepts either a single
prompt or a project brief and returns a model-annotated
recommendation or roadmap.

**Complexity:** Medium · **Risk:** Low · **Cloud cost:** $0
(local; uses the developer's own `ANTHROPIC_API_KEY`)

#### 2.1 The classifier
- Add `app/recommender/classify.py`.
- Single Anthropic API call to Haiku 4.5
  (`claude-haiku-4-5-20251001`) with a tight system prompt: input
  is a user prompt, output is structured JSON with `task_primary`,
  `task_secondary` (nullable), and `complexity_overall ∈ {Low,
  Medium, High}`.
- Use prompt caching on the system prompt (cache breakpoint at the
  end of instructions) to keep classifier cost flat across
  requests.
- Validate the JSON response with Pydantic; on parse failure,
  return a typed classifier error (no silent fallbacks).

#### 2.2 The roadmap planner
- Add `app/recommender/plan.py`.
- Single Anthropic API call to Sonnet 4.6 with a system prompt
  built from
  [docs/PROJECT_ROADMAP_TEMPLATE.md](docs/PROJECT_ROADMAP_TEMPLATE.md)
  and the recommender's `<task-categories>` list. Input: a 1–3
  paragraph project brief plus the global `quality_weight`.
  Output: structured JSON of phases, each phase carrying an
  ordered list of prompt steps; each step is pre-classified with
  `task_primary`, `task_secondary` (nullable), and
  `complexity_overall`.
- A second mode `annotate_existing(roadmap_md)` parses an
  already-written roadmap (extracts each prompt step) and feeds
  it to the classifier — no new draft is generated, only model
  blocks added.
- Use prompt caching on the template + system instructions (cache
  breakpoint at the end of instructions). The brief is the only
  varying input.
- Validate the JSON response with Pydantic; on parse failure,
  return a typed planner error (no silent fallbacks).

#### 2.3 The FastAPI app
- `POST /recommend`
  - Request: `{ prompt: str, quality_weight: float }`.
  - Pipeline: classifier → selector → response.
  - Response: `{ model, max_mode, conversation, rationale,
    classification, candidates_considered }`.
- `POST /annotate-roadmap`
  - Request: `{ brief?: str, existing_roadmap?: str,
    quality_weight: float, mode: 'project' | 'phase' |
    'annotate-only' }`.
  - Pipeline: planner (or roadmap parser) → per-step classifier
    → per-step selector → render the appropriate template
    (PROJECT_ROADMAP_TEMPLATE.md or PHASE_ROADMAP_TEMPLATE.md)
    with a model block before each prompt step.
  - Response: `{ roadmap_markdown: str, steps: [{...}],
    estimated_cost_band: str }`.
- `GET /healthz` returns `{ ok: true, doc_commit: <sha> }` so
  monitoring can verify the docs version the API is serving.
- `GET /models` returns the parsed `<model-options>` as JSON for
  the frontend to render (e.g., the slider's tooltip preview).

#### 2.4 Operational wiring
- Pin which `docs/model-selector.txt` commit the API is reading at
  boot; expose it via `/healthz`.
- Structured logging (one JSON line per request) including:
  request type (`recommend` | `annotate-roadmap`), prompt or
  brief length, classification, recommendation, latency,
  classifier-token usage, planner-token usage.
- Local-only — no auth, no rate limit yet. Document in
  `app/README.md` that the service is bound to `127.0.0.1` until
  Phase 4.

**Acceptance criteria**
- `curl -X POST localhost:8000/recommend -d '{...}'` returns a
  structurally valid JSON response on the Phase 1 fixture set.
- `curl -X POST localhost:8000/annotate-roadmap -d '{...}'` with
  a project brief returns Markdown that conforms structurally to
  PROJECT_ROADMAP_TEMPLATE.md (validated by a parser test) and
  has a valid model block before every prompt step.
- The `annotate-only` mode round-trips an existing roadmap by
  preserving its phase headings and inserting model blocks
  without rewriting prose.
- p95 latency under 3 s on `/recommend` and under 15 s on
  `/annotate-roadmap` on a developer laptop with primed caches.
- Classifier and planner token usage bounded — system-prompt
  cache-hit rate verified in logs for both endpoints.
- `/healthz` reports the current `docs/` commit SHA.

---

### Phase 3 — Minimal web UI (local)

**Goal:** A single-page app whose primary mode is the roadmap
annotator and whose secondary mode is the single-prompt advisor.

**Complexity:** Low · **Risk:** Low · **Cloud cost:** $0

#### 3.1 The page
- One static page (vanilla HTML + a single JS file, or a tiny
  Next.js / SvelteKit app — choose the option with the fewest
  dependencies).
- Top-level mode tabs: **Project roadmap** (default), **Phase
  deep-dive**, **Single prompt**.
- Shared elements: large textarea (project brief in the roadmap
  modes, prompt in single-prompt mode), quality-vs-cost slider
  (`0.00 – 1.00`, default `1.00`), submit button, result panel.
- A fourth implicit mode: in roadmap and phase tabs, an "I already
  have a draft — just annotate it" toggle flips the textarea from
  brief-input to roadmap-paste and switches the API call to
  `mode: 'annotate-only'`.

#### 3.2 The result panel — split by mode
- **Single-prompt mode:** renders `MODEL`, `MAX MODE`,
  `CONVERSATION`, `RATIONALE` in the exact format defined by
  `<output-format>` in `docs/model-selector.txt`. Below: a
  collapsible details panel with primary/secondary task category,
  overall complexity, and the top three candidates with scores.
- **Roadmap modes:** renders the filled-in
  PROJECT_ROADMAP_TEMPLATE or PHASE_ROADMAP_TEMPLATE as Markdown,
  with each prompt step preceded by its model block. "Copy as
  Markdown" button. Per-phase estimated cost band displayed
  inline; whole-roadmap total at the top.

#### 3.3 Slider UX
- Three labeled stops on the track: `Cost`, `Balanced`, `Quality`,
  mapped to `0.0`, `0.5`, `1.0`. Continuous value behind it.
- Hovering the slider shows a one-line tooltip: "At this weight, a
  coding-S prompt would recommend ___". Computed client-side from
  `/models` and the same scoring formula. The slider applies
  globally to whichever mode is active.

**Acceptance criteria**
- Submitting any of the Phase 1 fixture prompts in single-prompt
  mode at `quality_weight = 1.0` shows the same recommendation the
  API returns.
- Submitting a project brief in roadmap mode produces Markdown
  that conforms structurally to PROJECT_ROADMAP_TEMPLATE.md and
  has a valid model block before every prompt step.
- The "annotate-only" toggle round-trips a pasted roadmap: every
  prompt step gains a model block, and no other prose is altered.
- The "Copy as Markdown" button copies a string that round-trips
  through the `annotate-only` API mode to produce the same model
  blocks.
- Sliding from `Quality` to `Cost` on a coding-S prompt visibly
  changes the recommendation in the tooltip without a server
  round-trip.
- The page works in current Chrome and Safari with no console
  errors.

---

### Phase 4 — Public deployment (no accounts, IP rate-limited)

**Goal:** Move backend and frontend to a managed cloud, behind a
custom domain over HTTPS, with abuse controls strong enough to
allow anonymous access.

**Complexity:** Medium · **Risk:** Medium · **Cloud cost:** ~$10/mo
+ Anthropic API usage (TBD, scales with traffic)

#### 4.1 Backend deployment
- Dockerfile for the FastAPI app; build pinned to a Git SHA.
- Deploy to the chosen PaaS (Fly.io / Railway / Render — TBD).
  Single instance, smallest paid plan that supports custom domains
  and HTTPS.
- Secrets: `ANTHROPIC_API_KEY` set via PaaS secret store (never
  committed).
- Health check on `/healthz`.

#### 4.2 Frontend deployment
- Vercel (or Netlify) free tier for the static SPA.
- Custom domain TBD; HTTPS via the host.
- Frontend reads the backend URL from a build-time env var.

#### 4.3 Abuse controls
- IP rate limit: TBD requests per minute, TBD per day, enforced in
  middleware on the backend.
- Hard cap on prompt length (e.g., 10 KB) to bound classifier cost
  per request.
- Cloudflare (free tier) in front of both origins for DDoS shield
  and WAF.
- Refuse requests whose prompt looks like a jailbreak or prompt
  injection attempt — pattern matching only at this stage; do not
  rely on the classifier for safety decisions.

#### 4.4 Observability
- Backend ships structured logs to the PaaS log drain.
- A single dashboard view (PaaS metrics or Grafana Cloud free
  tier — TBD): request count, p95 latency, error rate, Anthropic
  spend per day.
- Alert on: error rate > 5% over 5 min, p95 > 5 s, daily
  Anthropic spend > TBD threshold.

**Acceptance criteria**
- Public URL serves the SPA over HTTPS with a valid cert.
- A `/recommend` round-trip from an external network completes in
  under 5 s p95.
- Sustained load test at 2× expected pilot traffic stays under
  rate-limit thresholds and does not exhaust the backend instance.
- Anthropic-spend alert fires on a forced overspend test.

---

### Validation gate — before Phase 5

Phases 5 and 6 add real complexity (auth, payments, quota
enforcement, churn handling). Don't pour that infra into a public
artifact that nobody is using. Treat the following as the gate:
**all three** signals must be true within 4 weeks of the Phase 4
launch, or pivot the product framing before continuing.

| Signal                                            | Threshold       |
|---------------------------------------------------|-----------------|
| Weekly recommendations served                     | ≥ 1,000         |
| Weekly distinct visitors                          | ≥ 200           |
| Inbound asks for accounts / API / Pro features    | ≥ 50 cumulative |

If the gate is missed, candidate pivots in priority order:

1. **Cursor cost optimizer.** Browser extension or CLI that
   ingests Cursor session history and shows the bill on cheaper
   models. Concrete dollar savings; narrow audience that's
   actively bleeding money.
2. **Router play.** SDK that drops in front of Anthropic / OpenAI
   calls and routes by classification. Real token savings,
   stickier business — but head-to-head with OpenRouter et al.
3. **Narrower planning-artifact wedge.** Niche to one audience
   (e.g. AI consultants planning client work) and distribute via
   that community rather than mass SEO.

A pivot decision must be a one-page memo before any code change;
don't lurch.

---

### Phase 5 — Accounts, API keys, free tier

**Goal:** Optional sign-up that unlocks a higher request quota and
issues an API key for programmatic access.

**Complexity:** High · **Risk:** Medium · **Cloud cost:** ~$15–25/mo

#### 5.1 Storage
- Postgres on the same PaaS (smallest tier).
- Schema: `users(id, email, created_at)`,
  `api_keys(id, user_id, prefix, hash, created_at, revoked_at)`,
  `usage(id, user_id_or_ip, ts, endpoint, latency_ms,
  classifier_tokens_in, classifier_tokens_out, model_returned)`.

#### 5.2 Auth
- Email + magic link (no passwords) — provider TBD (Resend +
  hand-rolled, or a managed auth service like Clerk/Supabase Auth
  on free tier).
- Session cookie for the SPA; bearer-token API key for
  programmatic clients.

#### 5.3 Quotas
- Anonymous (no account): unlimited single-prompt advisor calls
  rate-limited per IP (the Phase 4 limit); zero roadmap
  generations.
- Free signed-in: unlimited single-prompt advisor; **3 roadmaps
  per rolling calendar month**; Markdown export only.
- Quota enforcement in the same middleware as Phase 4 rate
  limiting; the roadmap counter resets on the first of each
  month.
- Roadmap output for free-tier users carries a "Generated by
  roadmodel" footer link that Pro removes (see Phase 6).

**Acceptance criteria**
- A new visitor can sign up, receive a magic link, log in, and see
  their personal quota counter.
- A revoked API key returns `401` within 60 s of revocation.
- Usage rows are written for every successful `/recommend`.
- Anonymous and signed-in quotas are independently enforced and
  tested.

---

### Validation gate — before Phase 6

Phase 6 adds paid billing and the Pro feature surface. Build only
after the free tier proves users come back to the artifact, not
just visit once. Treat the following as the gate: **both** signals
must be true over a rolling 4-week window after Phase 5 launches.

| Signal                                            | Threshold       |
|---------------------------------------------------|-----------------|
| Week-over-week retention on roadmap generations   | ≥ 30%           |
| Free-tier MAUs hitting the 3-roadmaps/month cap   | ≥ 5%            |

If retention is below 30%, the artifact isn't sticky enough for a
subscription business — fix the product before adding Stripe. If
the second signal is missed, the free quota is too generous and
Pro has no obvious upgrade trigger; tighten the free quota before
adding billing.

---

### Phase 6 — Pro tier (Stripe)

**Goal:** Ship a single paid Pro plan that lifts roadmap quotas
and unlocks history, custom templates, and the savings dashboard.
No team plans, no per-call billing.

**Complexity:** Medium · **Risk:** Medium · **Cloud cost:** Stripe
fees only (~2.9% + $0.30 per charge; no incremental infra)

#### 6.1 Tier definitions

| Tier | Price             | Gates                                                                                                       |
|------|-------------------|-------------------------------------------------------------------------------------------------------------|
| Free | $0                | Unlimited single-prompt advisor; 3 roadmaps/month; Markdown export; output footer link                      |
| Pro  | $15–19/mo (TBD)   | Unlimited roadmaps; phase deep-dives; saved history; custom templates; est-savings dashboard; no footer     |

Launch Pro at **$15**. Raise to $19 only if churn at $15 falls
below 5% per month over a rolling 8 weeks. Lower below $15 only
after explicit price-elasticity testing — never reactively.

#### 6.2 Stripe wiring
- One Stripe product, one Pro price (USD/month).
- Stripe Checkout for upgrade; Stripe Customer Portal for
  cancellation, payment-method update, and plan view.
- Schema additions: `users.plan ∈ {free, pro}`,
  `users.stripe_customer_id`, `users.stripe_subscription_id`.

#### 6.3 Webhook
- `/stripe/webhook` handles `checkout.session.completed`,
  `customer.subscription.updated`,
  `customer.subscription.deleted`, `invoice.payment_failed`.
  Signature-verified.
- On state change, flip `users.plan` and the corresponding quota
  live — no cache stale, no redeploy.

#### 6.4 Pro-only feature gates
- Roadmap quota lifted to unlimited for `users.plan == 'pro'`.
- History, custom-template, and savings-dashboard endpoints check
  `users.plan == 'pro'` and return `402 Payment Required` for
  free.
- Free-tier roadmap output gets a Markdown footer link that Pro
  omits.

#### 6.5 Billing safety
- Idempotency on webhook handlers (Stripe `event.id` as the
  dedup key).
- Reconciliation script (cron or on-demand) compares Stripe state
  with `users.plan` and flags mismatches.
- Monthly metrics: MRR, voluntary churn, involuntary churn
  (failed payments), free→Pro conversion rate.

**Acceptance criteria**
- A test-mode upgrade flips a user from `free` to `pro` and
  raises their quota live, without a redeploy.
- A test-mode cancellation reverts the user at period end (not
  immediately).
- Replaying the same webhook twice does not double-apply.
- Reconciliation script reports zero mismatches on a clean test
  ledger.
- A Pro-only endpoint returns `402` for a free user and `200` for
  a Pro user.
- The free-tier output footer renders on free responses and is
  absent on Pro responses.

---

## 5. Cross-Cutting Concerns

### Cost projection (monthly, USD, pilot scale)

| Service                                  | Estimate      |
|------------------------------------------|---------------|
| Backend PaaS (smallest paid tier)        | $5–15         |
| Postgres (added Phase 5)                 | $0–10         |
| Frontend hosting (Vercel/Netlify free)   | $0            |
| Domain                                   | ~$1           |
| Cloudflare (free tier)                   | $0            |
| Anthropic API (classify + plan)          | TBD           |
| Stripe fees (added Phase 6)              | 2.9% + $0.30  |
| **Total infra (excluding Anthropic)**    | **~$10–30**   |

### Sequencing & dependencies

```
Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5 ──▶ Phase 6
 (lib)      (API)       (UI)         (deploy)    (accounts)  (billing)
                                       │
                                       └─ irreversible cutover:
                                          public endpoint exposed
```

- Phases 1–3 are local-only and ship at $0. Each is a single PR.
- Phase 4 is the cutover phase. Once a public URL exists, abuse
  controls and Anthropic-spend alerts must be live before
  announcing it.
- **Validation gate A** sits between Phase 4 and Phase 5: traffic
  + inbound thresholds must be met or the framing pivots before
  any account / payments work begins.
- **Validation gate B** sits between Phase 5 and Phase 6:
  retention thresholds must be met before Stripe ships.
- Phases 5 and 6 build on the deployed Phase 4 stack — no rework
  of backend or frontend, only additions.
- Per the staged-rollout preference, do not begin Phase N+1 until
  Phase N is verified in its target environment (local for 1–3,
  cloud for 4–6).

### Branch management strategy

#### Branching model

`main` is the single source of truth. All work happens on
short-lived branches (≤ 1 week) that merge into `main` via pull
request. `main` must always be:

- Green on CI (existing `tests.yml` plus the new
  `test_recommender.py` from Phase 1).
- Deployable to the target environment.
- Tagged with semver on every production release from Phase 4
  onward.

#### Branch naming convention

| Prefix     | Purpose                          | Example                     |
|------------|----------------------------------|-----------------------------|
| `feature/` | Phase work or new feature        | `feature/phase-1-recommender` |
| `fix/`     | Non-urgent bug fix               | `fix/classifier-json-parse` |
| `hotfix/`  | Urgent production fix from `main`| `hotfix/rate-limit-bypass`  |
| `chore/`   | Tooling, deps, housekeeping      | `chore/bump-fastapi`        |
| `docs/`    | Documentation-only changes       | `docs/roadmap-update`       |
| `perf/`    | Performance work                 | `perf/classifier-cache`     |
| `release/` | Pre-release stabilisation        | `release/v0.40.0`           |

#### Pull request rules

1. **Scope discipline.** One PR per phase sub-section.
2. **PR template.** Roadmap reference, summary, test plan,
   screenshots for UI, breaking-change notes, rollback plan.
3. **CI green required.** Lint, type-check, tests, security scans
   all pass before merge.
4. **No force-push to `main`.** Allowed on personal branches only
   before review opens.
5. **Squash-merge** to `main` so each phase reads as one clean
   commit.
6. **Conventional Commits** on the squash message.

#### Release & tagging

| Milestone tag         | Marker                                       |
|-----------------------|----------------------------------------------|
| `v0.10.0-phase-1`     | Recommender library + tests merged           |
| `v0.20.0-phase-2`     | Local FastAPI service answers `/recommend`   |
| `v0.30.0-phase-3`     | Local web UI demos end-to-end                |
| `v0.40.0-phase-4`     | Public URL live, IP-rate-limited             |
| `v0.50.0-phase-5`     | Accounts and free-tier quotas live           |
| `v1.0.0`              | Pro plan generally available                 |

### Risks & mitigations

| Risk                                        | Mitigation                  |
|---------------------------------------------|-----------------------------|
| Classifier cost runaway                     | Haiku + prompt cache;       |
|                                             | daily Anthropic-spend alert |
| Doc drift breaks the parser                 | Phase 1 parser shares the   |
|                                             | regex set used by           |
|                                             | `test_doc_schema.py`        |
| Anonymous abuse spikes Anthropic spend      | IP rate limit + Cloudflare  |
|                                             | + spend alert in Phase 4    |
| Quality-weight scoring produces surprising  | Snapshot tests across the   |
| recommendations at intermediate values      | weight sweep; tune the      |
|                                             | tier→score mapping if a     |
|                                             | fixture regresses           |
| PaaS lock-in on the chosen vendor           | Container is portable;      |
|                                             | Postgres dump is portable;  |
|                                             | re-deploy elsewhere if      |
|                                             | needed                      |
| Stripe webhook missed / replayed            | Idempotent handlers +       |
|                                             | reconciliation script       |

---

## 6. Monetization Strategy

### Pricing thesis

Subscription only. No display ads, no affiliate links, no
bring-your-own-key (BYOK), no per-call usage billing through
Phase 6. The free tier is acquisition spend; the Pro tier is the
revenue driver. Team and Enterprise are deferred (§7) with
explicit demand gates before they get built.

The thesis follows from three observations:

- Display CPMs at realistic launch traffic (≤ 10k uniques/month)
  net low single-digit dollars per month and degrade the UX of
  the artifact.
- The major model vendors (Anthropic, OpenAI, Cursor) do not run
  public referral programs today; affiliate revenue is unreliable
  and orthogonal to the product.
- BYOK eliminates variable cost but kills the Pro value prop —
  if the user supplies the key, the perceived value is "templates
  and a slider," which doesn't sustain $15/month.

### Tier ladder

| Tier        | Price       | Build phase / gate                       |
|-------------|-------------|------------------------------------------|
| Free        | $0          | Phase 5 (after gate A in §4)             |
| Pro         | $15–19/mo   | Phase 6 (after gate B in §4)             |
| Team        | TBD         | Deferred (§7); ≥ 5 unsolicited asks      |
| Enterprise  | TBD         | Deferred (§7); ≥ 3 paying contracts      |

Pro launches at **$15/month**. Raise to $19 only if churn at $15
falls below 5% per month over a rolling 8 weeks. Reactive
discounting is forbidden — see Phase 6.1.

### What each tier unlocks

| Feature                              | Free   | Pro    |
|--------------------------------------|--------|--------|
| Single-prompt advisor                 | ∞      | ∞      |
| Project-roadmap generation            | 3 / mo | ∞      |
| Phase deep-dive generation            | —      | ✓      |
| Saved roadmap history                 | —      | ✓      |
| Custom templates                      | —      | ✓      |
| Estimated savings dashboard           | —      | ✓      |
| Markdown export                       | ✓      | ✓      |
| Output footer link                    | shown  | hidden |

### Unit economics

Per-request variable cost (API only):

| Request                | LLM calls                           | Cost        |
|------------------------|-------------------------------------|-------------|
| Single-prompt advisor   | 1× Haiku 4.5 classify               | ~$0.001     |
| Roadmap, annotate-only  | 1× Sonnet parse + N× Haiku classify | ~$0.05–0.15 |
| Roadmap, from brief     | 1× Sonnet plan + N× Haiku classify  | ~$0.15–0.50 |

Single-prompt is essentially free to serve. Roadmaps carry the
real cost; pricing has to defend roadmap unit economics.

Per-Pro-user margin (illustrative, $15 price):

| Pro user behavior      | API cost / month  | Margin       |
|------------------------|-------------------|--------------|
| 5 roadmaps / month      | ~$1.50            | ~93%         |
| 15 roadmaps / month     | ~$4.50            | ~77%         |
| 30 roadmaps / month     | ~$9.00            | ~52%         |
| 50+ roadmaps / month    | ~$15              | breakeven    |

A "fair-use" cap (e.g. 100 roadmaps/month) on Pro is deferred. If
heavy-tail abuse appears in usage logs, introduce it before
discounting or rate-limiting.

### Free-tier economics

The free tier is acquisition spend. Three roadmaps/month at
~$0.30 each is ~$0.90/month for a fully-utilizing free user; most
free users never hit the cap, so realistic average is closer to
~$0.30/month/free-user.

Conversion math: one Pro user at $15 net of ~30% all-in cost
(API + Stripe + amortized fixed) is ~$10.50 contribution. That
covers ~12 fully-utilizing free users or ~35 average free users.
A 1% free→Pro conversion rate keeps the free tier paying for
itself; 3% makes it net-positive.

### Revenue drivers (in order of MRR impact)

1. **Top-of-funnel volume.** Visitors / month, driven by SEO,
   launch posts (HN, r/cursor, Twitter), and the artifact's own
   shareability — every generated roadmap is a marketing
   surface.
2. **Free signup conversion.** Visitors → free signed-in. Driven
   by demo quality on the landing page, magic-link friction, and
   pre-signup value (one free roadmap before account required).
3. **Cap-hit rate.** Of free users, what fraction generate ≥ 3
   roadmaps/month. The product-engagement metric.
4. **Free→Pro conversion.** Of cap-hitters, what fraction
   upgrade. Driven by visible Pro-only value (history, savings
   dashboard).
5. **Pro retention.** 1 − monthly churn. Driven by saved history
   (sunk-cost stickiness) and habit formation.
6. **Pro pricing.** $15 → $19 lever; only after retention data
   shows headroom.

A 12-month pro-forma with three scenarios (conservative, base,
optimistic) and a sensitivity analysis on the levers above lives
in [PRO_FORMA.md](PRO_FORMA.md).

### Out of strategy

- Display advertising, content sponsorships, vendor affiliate
  links — see §7.
- Per-call or per-token usage billing.
- BYOK as a pricing axis.
- Promotions, coupons, "launch sales" before 6+ months of churn
  data exist.

---

## 7. Out of Scope

The following are deliberately deferred to a future version. Each
has a defined gate before it gets pulled in.

- **Team tier** (3–10 seats, shared roadmap library, team cost
  report, API access for CI). Build only after ≥ 5 unsolicited
  inbound asks for team features.
- **Enterprise tier** (SSO, custom model curation, SLA,
  white-label). Treated as a services-led offering until volume
  justifies productization (≥ 3 paying enterprise contracts
  signed manually first).
- **Per-call usage-based billing.** Subscription pricing only
  through Phase 6.
- **Display ads** / **affiliate links** (no reliable referral
  programs from the major model vendors today; revisit if one
  ships).
- **BYOK (bring-your-own-Anthropic-key).** Revisit only as a
  Team/Enterprise option, never as the MVP path — it destroys the
  Pro value prop.
- **Webhook integrations or third-party app installs** (Slack,
  Linear, GitHub apps).
- **A fine-tuned classifier.** Haiku-via-API is the only
  classifier through Phase 6.
- **On-prem or self-hosted distribution.**
- **Per-prompt cost or token-count estimates** in the response
  body.
- **Native mobile apps.**
- **Localization beyond English.**

---

## 8. Glossary

| Term              | Meaning                                              |
|-------------------|------------------------------------------------------|
| `<model-options>` | The XML block in `docs/model-selector.txt` listing every recommendable model and its tier ratings |
| Tier rating       | One of S/A/B/C/D, per task category, per model       |
| Quality weight    | A user-supplied float in `[0.0, 1.0]` controlling how strongly cost competes with quality in the final ranking |
| Max Mode          | Cursor feature that extends a model's context window; recommended on or off per the selection algorithm |
| PaaS              | Managed application-hosting service (Fly.io, Railway, Render — choice TBD) |

---

## 9. Phase Complexity Summary

| Phase | Description                                     | Complexity |
|-------|-------------------------------------------------|------------|
| 1     | Extract recommender library                     | Medium     |
| 2     | Local HTTP API + classifier                     | Medium     |
| 3     | Minimal local web UI                            | Low        |
| 4     | Public deployment, IP rate-limited              | Medium     |
| 5     | Accounts, API keys, free tier                   | High       |
| 6     | Pro tier via Stripe                             | Medium     |
