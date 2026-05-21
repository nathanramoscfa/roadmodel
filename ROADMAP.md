# roadmodel — From CLI Prototype to Bundled SaaS MVP

> **Status:** Phases 1 and 2 shipped on PyPI (`roadmodel` v0.1.x and
> v0.2.0 — the latter adds the cost estimator, structured CLI output,
> and the `roadmodel-mcp` MCP server); Phases 3–9 below remain the
> forward execution plan.
> **Owner:** Nathan Ramos, founder and sole maintainer
> **Target environment:** Local through Phase 2; managed cloud from
> Phase 3 onward (managed Next.js host for the web tier, managed
> Python runtime for the recommender service, managed Postgres + Auth
> + Storage)
> **Last updated:** May 2026

This roadmap takes roadmodel from a local Python CLI that ranks AI
models by prompt fit to a bundled SaaS at `roadmodel.ai`. The SaaS
offers two paid surfaces — a model-plus-platform-plus-settings
recommender and an AI-assisted roadmap builder — alongside a free,
open-source CLI that ships the recommender alone.

---

## 1. Executive Summary

roadmodel today is a local CLI that takes a prompt and returns a
recommended AI model, scored against the Artificial Analysis
benchmark catalog augmented with Cursor's model roster and raw-data
benchmarks (τ²-bench, LiveCodeBench). It now needs to become a
hosted SaaS that adds (1) a platform layer recommending Claude Code,
Cursor, Codex, or raw API based on subscription state and estimated
session size, (2) a conversational roadmap builder driven by the
existing PROJECT and PHASE roadmap templates, and (3) tiered,
model-aware monetization — while shipping the recommender as both a
Python CLI and an MCP (Model Context Protocol) server publicly under
Apache 2.0 so devs can invoke roadmodel from inside their IDE with
full project context. These constraints drive the work:

1. **Solo builder bandwidth.** Every phase must be independently
   shippable so partial completion still leaves a working product.
2. **AI inference is variable cost.** Free-tier surfaces must run on
   cheap models so anonymous usage stays sustainable pre-PMF.
3. **Open-core, not open-everything.** The recommender CLI is
   Apache 2.0; the hosted SaaS, branded exports, and deliverable
   generators are closed-source.
4. **Bundled MVP.** Recommender and roadmap builder ship together
   at v1 because they serve a single project-planning workflow.
5. **No free hosted tier at launch.** Paid-only hosted at launch.
   Revisit a free hosted tier only after paid demand is validated.

The path: **open → catalog → recommend → roadmap → monetize →
export → harden → launch**. Each phase is independently shippable;
phases 1 and 2 require zero cloud spend.

### Capability matrix by tier

| Tier            | /recommend   | /roadmap          | Model class                                | Exports                       | History       |
|-----------------|--------------|-------------------|--------------------------------------------|-------------------------------|---------------|
| Anonymous web   | 3/day per IP | Soft sign-up wall | Cheap (Haiku 4.5 / Flash)                  | None                          | No            |
| Free signed-in  | Capped       | Capped            | Cheap (rec) / mid (roadmap)                | MD                            | Yes (cloud)   |
| Paid Pro hosted | Unlimited*   | Unlimited*        | Frontier (Sonnet 4.6 default; Opus opt-in) | MD / HTML / PDF / DOCX + deck | Yes (cloud)   |
| OSS CLI + MCP   | Unlimited    | Repo-aware (MCP)  | Any (BYO API key)                          | MD                            | Local files   |

\* Fair-use soft cap; BYO API key path covers overage.

---

## 2. Current State Assessment

### What works today
- CLI ranks AI models for a given prompt using AA benchmark data,
  Cursor's catalog, and supplementary raw-data sources
  (τ²-bench, LiveCodeBench).
- Project renamed from `model-selector` to `roadmodel` on GitHub.
- [project-roadmap-template.md](docs/templates/project-roadmap-template.md)
  and [phase-roadmap-template.md](docs/templates/phase-roadmap-template.md)
  exist and produce usable structured roadmaps when paired with a
  project brief.
- Domain `roadmodel.ai` is owned.

### Gaps blocking SaaS launch

Grouped by gap category. The phase ordering below is driven by
these gaps.

**Recommender surface**

- No platform recommendation (Claude Code / Cursor / Codex).
- No subscription-aware cost math.
- No IDE-native surface for in-project workflows.

**Hosted product surface**

- No web frontend, no auth, no billing.
- No conversational roadmap interface.
- No usage caps, rate limits, or abuse controls.

**Distribution and packaging**

- CLI not packaged or licensed for public release.

**Deliverables and exports**

- No branded export formats (HTML / PDF / DOCX).
- No deliverable generators (pitchdeck).

**Operations and catalog**

- No automated pricing-catalog refresh.
- No analytics, error tracking, or observability.

---

## 3. Target Architecture

```
        ┌─────────────────────────────────────┐
        │  Browser  ·  CLI user               │
        └────────────┬────────────────────────┘
                     │ HTTPS (TLS)
                     ▼
   ┌──────────────────────────────────────────────┐
   │  roadmodel.ai — web frontend (SSR)           │
   │  /  /recommend  /roadmap  /pricing  /account │
   └──────────────────┬───────────────────────────┘
                      │ session cookie + CSRF
                      ▼
   ┌──────────────────────────────────────────────┐
   │  API tier — recommender + roadmap engine     │
   │  Rate limit · auth · tier check · audit log  │
   └─┬───────────┬────────────────┬────────────┬──┘
     ▼           ▼                ▼            ▼
   ┌──────┐  ┌─────────┐  ┌──────────────┐  ┌──────────┐
   │  Pg  │  │ Object  │  │ AI providers │  │ Managed  │
   │  DB  │  │ store   │  │ Anthropic /  │  │ payments │
   │      │  │         │  │ OpenAI /     │  │          │
   │      │  │         │  │ Google       │  │          │
   └──────┘  └─────────┘  └──────────────┘  └──────────┘
```

Single public ingress at `roadmodel.ai` over HTTPS. A managed
Next.js host serves the web tier; a managed Python runtime serves
the API tier, which is the only component that holds AI provider
keys — the browser never sees them. Persistent state lives in a
single managed Postgres + Auth + Storage offering (users, history,
audit logs); user uploads and generated exports live in the same
provider's object store. A managed payments provider delivers
billing events via signed webhooks to the API tier.

The OSS surfaces — Python CLI and MCP server — run entirely
client-side under the user's BYO API key and never touch the
hosted infrastructure above. The MCP server is reached by any
MCP-capable client (Cursor, Claude Code, Claude Desktop, VS Code
+ Continue) over local stdio; the calling agent supplies repo
context, and roadmodel returns recommendations or roadmap drafts
grounded in the bundled selector + template docs.

---

## 4. Phased Roadmap

### Phase 1 — Open-source the Recommender CLI

**Goal:** Ship the existing recommender as a public Apache 2.0
package on PyPI so early adopters can install and use it with their
own API keys.

#### 1.1 Licensing and repo hygiene
- Apply Apache 2.0 LICENSE file at repo root.
- Add NOTICE, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md.
- Issue and PR templates under `.github/`.

#### 1.2 CLI polish for public consumption
- Audit all internal references and complete the rename to
  `roadmodel` (renamed from `model-selector`).
- Replace local-only paths with config-driven equivalents.
- Add `--help` text and error messages for every command.
- Document BYO API key setup for Anthropic, OpenAI, Google.

#### 1.3 Packaging and distribution
- Define `pyproject.toml` with the `roadmodel` package name.
- Publish to PyPI; verify install via fresh virtualenv.
- Tag `v0.1.0` and publish a GitHub release with changelog.

**Acceptance criteria**
- A third-party developer can run `pip install roadmodel`,
  configure their own API key, and successfully execute
  `roadmodel recommend "<prompt>"` against the live catalog.
- The repo carries an OSI-recognised Apache 2.0 license.
- GitHub release `v0.1.0` is published with a written changelog.
- Phase 1 verification automation: `.github/workflows/phase-verify.yml`
  runs `scripts/verify-phase01.sh --fast` on every push and pull
  request to `main`, covering static deliverable checks 1–33 plus
  the V1.1–V7.3 rollup.

---

### Phase 2 — Platform Recommendation, MCP Server, and Catalog v2

**Goal:** Extend the recommender beyond "which model" to "which
model on which platform with which settings," driven by subscription
state and estimated session size; and ship an MCP server in the
same OSS package so devs can invoke roadmodel from inside any
MCP-capable IDE (Cursor, Claude Code, Claude Desktop, VS Code +
Continue) with their project's full context already on hand.

#### 2.1 Pricing catalog expansion
- Add API pricing for Anthropic, OpenAI, Google, xAI to the catalog
  JSON.
- Add subscription tier data for Cursor (Pro, Ultra), Claude Code
  (Pro, Max), and ChatGPT (Plus, Pro).
- Encode Cursor Max Mode pricing rules.
- Document a weekly manual refresh procedure.

#### 2.2 Recommendation engine extension
- New inputs: user subscription state, budget priority
  (`cheap | balanced | best`), latency tolerance.
- New output schema: `{model, platform, settings,
  session_cost_estimate, comparison_table}`.
- Platform-aware settings: Claude Code returns
  switch-model / effort / thinking; Cursor returns its native
  settings plus a Max Mode flag; raw API returns plain params.

#### 2.3 CLI surface upgrade
- Update CLI output to display the platform recommendation, cost
  estimate, and side-by-side cost comparison across alternatives.
- Ship as `v0.2.0` on PyPI.

#### 2.4 MCP server
- Ship an MCP server alongside the CLI in the same `roadmodel`
  PyPI package, exposed as a separate console-script entry point
  (`roadmodel-mcp`) that speaks the MCP stdio protocol.
- Tools exposed: `recommend_model(task_description, *, context?)`,
  `generate_phase_roadmap(project_brief, phase_number, *, prior_phases?)`,
  and `read_catalog()` (returns the bundled `model-selector.txt`
  and `model-tier-cost-scale.md` so the calling agent can reason
  over the catalog directly).
- Compatible with Cursor, Claude Code, Claude Desktop, and VS
  Code + Continue; configuration via each client's standard MCP
  server registration JSON. No per-IDE plugin code.
- BYO API key model unchanged: the MCP server reads the same
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY`
  precedence chain the CLI uses. The calling agent supplies repo
  context; roadmodel does no filesystem walking of its own.
- Ship `docs/mcp-setup.md` covering per-client install for Cursor
  and Claude Code at minimum; reference docs for additional
  clients link out to upstream MCP installation guides.

**Acceptance criteria**
- CLI returns a platform recommendation, settings block, and cost
  estimate for any prompt against the cached catalog.
- The CLI runs fully offline against the cached catalog data.
- The catalog refresh procedure is documented and reproducible by
  a contributor with no prior context.
- A Cursor or Claude Code user can register `roadmodel-mcp` in
  their client's MCP config, invoke the `recommend_model` and
  `generate_phase_roadmap` tools from within a real project, and
  receive output that demonstrably incorporates the repo context
  the calling agent supplied.

---

### Phase 3 — Marketing Site and Anonymous Web Recommender

**Goal:** Stand up `roadmodel.ai` with a marketing home and a
working anonymous recommender so a first-time visitor can paste a
prompt and receive a recommendation without signing up.

#### 3.1 Stack provisioning
- Provision the managed Next.js host project for the web tier
  (Next.js 15, App Router).
- Provision the managed Python runtime project for the FastAPI
  recommender service; expose only via authenticated internal
  call from the Next.js API routes.
- Provision the managed Postgres + Auth + Storage project.
- Configure staging and production environments behind DNS, TLS,
  and basic uptime monitoring.
- The Python FastAPI service imports the same scoring engine the
  OSS CLI ships; both consume a single shared catalog JSON.

#### 3.2 Marketing home page
- Hero with headline, subhead, and a try-it-now textarea above the
  fold (no auth required).
- How-it-works section (3 steps with screenshots).
- Pricing teaser (two cards), footer with GitHub, docs, terms.

#### 3.3 `/recommend` page
- Two-column layout: input column (textarea, attachment dropzone,
  collapsible "your context") and output column (model, platform,
  settings, cost comparison, expandable "why?").
- Anonymous usage rate-limited by IP; cheap model
  (Haiku 4.5 / Gemini Flash) powers the backend.
- Free-tier model is labeled in the output with a placeholder
  upgrade CTA (live in Phase 5).

#### 3.4 Abuse controls and baseline cost ceilings
- Rate limit anonymous requests by IP and by recent burst pattern.
- Cap free-trial recommendations at 3/day per IP.
- Log every request for audit and abuse review.
- Configure provider-side billing caps on every AI provider in use
  from day one of cloud spend.

**Acceptance criteria**
- An anonymous visitor can paste a prompt at
  `roadmodel.ai/recommend` and receive a complete recommendation
  (model, platform, settings, cost) within 5 seconds.
- IP-level rate limits trigger correctly at the documented
  thresholds.
- TLS is valid, DNS is correct, and uptime monitoring alerts the
  maintainer's email on outage.

---

### Phase 4 — Auth and Roadmap Builder MVP

**Goal:** Add account signup and ship the conversational roadmap
builder with live preview and markdown export.

#### 4.1 Authentication
- Wire the managed Auth provider into the Next.js app.
- Enable email magic-link plus Google and GitHub OAuth providers.
- Session cookie, CSRF protection, server-side session validation
  on every API call into the Next.js and Python tiers.

#### 4.2 `/roadmap` chat surface
- Chat UI on the left; live structured preview panel on the right
  (artifact-style).
- Conversation opens with "Describe your project. Paste, type, or
  attach anything."
- System prompt references
  [project-roadmap-template.md](docs/templates/project-roadmap-template.md)
  and
  [phase-roadmap-template.md](docs/templates/phase-roadmap-template.md).
- AI asks at most 3–5 clarifying questions before drafting.

#### 4.3 Markdown export and history
- "Looks good" button unlocks an export panel; MD download
  available to all signed-in users.
- Conversation and resulting roadmap saved to the user's history.

#### 4.4 Model tiering scaffold
- Free signed-in tier uses a mid-tier model (cost-aware).
- Frontier model is feature-flagged off; payment gates it in
  Phase 5.

#### 4.5 First-session onboarding
- After first sign-in, present a single optional screen capturing
  subscription state (Claude / Cursor / ChatGPT) and budget
  priority (see §5 UX principles).
- Persist captured preferences to the user's profile in Postgres.
- Skip is a one-click action; recommender uses sane defaults when
  preferences are absent.

#### 4.6 Prompt caching (mandatory)
- Enable Anthropic prompt caching on every roadmap-builder call
  and every recommender call that carries a system prompt.
- Cache the system prompt (templates + scoring rules) and the
  rolling conversation history.
- Target: 70%+ cache-hit rate on roadmap conversations after the
  first user turn.

#### 4.7 Performance and warm-path latency
Phase 3 shipped at noticeably-slower-than-spec latency on the
anonymous `/recommend` flow (warm-path acceptance budget is
under 5 seconds). This sub-section closes that gap and
establishes a measured latency budget that later phases inherit.

- Instrument and profile the current `/recommend` warm-path
  response (anonymous, cached catalog) end-to-end: API-tier
  dispatch, scoring engine, AI provider call, and web-tier
  render. Record pre-fix vs post-fix numbers in a phase-4
  performance findings document.
- Targets (warm path, anonymous `/recommend`): P50 ≤ 3 seconds,
  P95 ≤ 5 seconds, measured over a representative request sample
  on production.
- Apply targeted fixes informed by profiling: prompt caching
  (already required by §4.6), tightened model output-token caps,
  parallel fan-out for the comparison-table call where the
  scoring engine permits, and any easy wins surfaced by the
  profiler.
- Document the cold-start budget separately; do not let cold
  starts eat the warm budget. Apply a warm-pool or keep-alive
  mitigation if cold-start P95 exceeds 8 seconds.
- Surface warm-path latency as a first-class metric so Phase 9
  observability inherits the data without a retrofit.

#### 4.8 Public Readiness Gate — deliberate launch
roadmodel.ai has been behind a Routing Middleware password gate
plus `noindex` posture since the 2026-05-20 hotfix that followed
Phase 3 Step 7's DNS cut. Phase 4 closes the gate as a deliberate
launch, not a side effect of any other step.

- Run a public-readiness audit of every gated surface:
  - Footer and any byline / attribution show
    Arcforge Digital Labs LLC only — no personal names,
    handles, or contributor credits.
  - Open Graph image, Twitter card, and sitemap.xml are
    present, correct, and reference the apex domain
    (not `staging.`).
  - Copy sweep removes placeholder strings, `TODO`s, and
    pre-launch language ("staging", "preview", "beta") on
    `/`, `/recommend`, `/privacy`, `/terms`, 404, and any
    other public route.
  - 404 and error pages render the production design.
  - Lighthouse scores on `/` and `/recommend` clear the
    Phase 3 SEO follow-up bar (issue #99): ≥ 0.9 for SEO
    and Best Practices, ≥ 0.85 for Performance.
- Stand up an internal beta tester loop before lifting:
  - Hand the shared `SITE_PASSWORD` to at least three
    external testers via a controlled channel.
  - Collect one structured round of feedback covering the
    recommend flow, copy, and any visible bugs.
  - Resolve or explicitly defer every reported blocker
    before scheduling the lift.
- Lift the gate in a single PR that:
  - Removes `web/middleware.ts`, `web/app/gate/`,
    `web/app/api/gate/`, `web/lib/gate.ts`.
  - Removes `robots: { index: false, follow: false }` from
    `web/app/layout.tsx`.
  - Replaces `public/robots.txt` Disallow with the
    launch-mode policy (Allow `/`, Disallow `/api/*`).
  - Removes the `SITE_PASSWORD` env var from all Vercel
    scopes on `roadmodel-web`.
  - Submits the sitemap to Google Search Console (and Bing
    Webmaster Tools if cost-free).
- Post-lift monitoring (24 hours minimum):
  - Watch the audit log for unexpected traffic, elevated
    error rates, and rate-limit hit volume.
  - Hold a documented rollback recipe (revert the gate-lift
    PR, not just the env vars) and use it if anomalies
    appear.
- Memory hygiene: archive
  `project_site_pre_launch_gate` with the lift date; keep
  `feedback_public_readiness_gate` as durable guidance for
  future DNS-cut milestones.

**Acceptance criteria**
- A signed-in user can complete a full roadmap conversation, see
  the structured preview update live, and download a
  template-compliant markdown roadmap.
- Auth flow works for email magic-link and at least one OAuth
  provider end-to-end.
- A signed-in user can revisit history and re-download any past
  roadmap.
- First-session onboarding captures or skips cleanly, and
  persisted preferences influence subsequent recommendations.
- Prompt caching is live and achieves ≥70% cache-hit rate on
  roadmap conversations beyond the first turn, measured over a
  representative sample.
- Warm-path P95 latency for the anonymous `/recommend` flow is
  ≤ 5 seconds end-to-end, P50 ≤ 3 seconds, measured over a
  representative sample on production with pre/post numbers
  recorded.
- The pre-launch site gate has been lifted via a deliberate
  Public-Readiness-Gate PR: middleware and noindex removed,
  `robots.txt` set to launch-mode policy, `SITE_PASSWORD`
  env var purged from all Vercel scopes, sitemap submitted to
  Search Console, attribution and copy audits complete, and at
  least three external beta testers have validated the gated
  experience end-to-end with no outstanding blockers.

---

### Phase 5 — Monetization Layer

**Goal:** Turn on paid tier with a managed payments provider,
usage caps, model gating, and BYO API key overage.

#### 5.1 Payments integration
- Hosted checkout for new subscriptions; customer portal for
  self-service billing changes.
- Signed webhook handler updates user tier in Postgres.

#### 5.2 `/pricing` and `/account`
- `/pricing`: two cards (Free CLI, Pro Hosted), feature
  comparison, FAQ.
- `/account`: subscription status, usage caps, BYO API key entry
  (encrypted at rest), link to the customer portal.

#### 5.3 Usage caps and model gating
- Free hosted: documented daily-anonymous and monthly signed-in
  caps for both the recommender and the roadmap surface.
- Paid hosted: unlimited within a fair-use soft cap; BYO key path
  kicks in for overage.
- Frontier models unlocked only for paid users.
- Free-tier output displays the model label and a live upgrade CTA.

#### 5.4 Legal and compliance scaffolding
- Privacy policy covering prompt content, conversation history,
  payment data, and AI provider sub-processors.
- Terms of service.
- Cookie notice for analytics and session cookies.
- User-initiated account and data deletion flow with a documented
  SLA; export-before-delete option for paid users.

**Acceptance criteria**
- A new user can sign up, subscribe, hit the paid model tier,
  exceed the included cap, and continue using the product via
  their own API key — without manual intervention.
- A paid user can downgrade via the customer portal, and the next
  request correctly enforces the free tier.
- All API keys at rest are encrypted with a key the API tier
  rotates per documented procedure.
- Privacy policy, terms of service, and a working data deletion
  flow are live and linked from the global footer.

---

### Phase 6 — Branded Exports and Pitchdeck Deliverable

**Goal:** Ship the paid-tier export experience: branded HTML / PDF /
DOCX roadmaps and a pitchdeck deliverable.

#### 6.1 Branded export pipeline
- HTML export with theme tokens.
- PDF export via headless browser or server-side library (decide
  during phase).
- DOCX export via templated generator.

#### 6.2 Branding capture
- Logo upload (PNG / SVG) with dimension and file-size limits.
- Color theme via picker, screenshot upload (palette-extracted),
  or freeform text description.

#### 6.3 Pitchdeck generator
- Slide-by-slide preview tab inside the roadmap conversation.
- Export to PDF and PPTX.
- This is the only deliverable shipped at MVP. One-pager, long-form
  slides, UI mockup, and pro-forma deliverables remain deferred
  (see §6 Out of Scope).

#### 6.4 `/history` upgrade
- Paid users see past recommendations, roadmaps, and generated
  deliverables, searchable by date and project name.

**Acceptance criteria**
- A paid user can produce a roadmap PDF carrying their logo and
  color theme.
- The same roadmap can be exported as a coherent pitchdeck PDF
  with consistent branding.
- The `/history` page renders all of a user's past artifacts with
  working re-download links.

---

### Phase 7 — Product Polish and v2 Redesign

**Goal:** Take v1 — the feature-complete proof of concept that
emerges from Phases 3–6 — and polish it into a v2 product that
looks and feels worthy of a paid SaaS. Iterate on visual design,
UI/UX flow, microcopy, and component-level interactions using a
screenshot-driven review loop until every surface meets a
documented design bar. v1 is the stepping stone; v2 is the
public-launch surface.

#### 7.1 v1 → v2 surface inventory and design bar
- Catalog every shipped surface as of end-of-Phase-6: marketing
  home, `/recommend`, `/roadmap`, `/pricing`, `/account`,
  `/history`, auth flows, export panels, onboarding, and the
  full error / empty / loading-state set.
- Capture v1 screenshot baselines (mobile, tablet, desktop) for
  every surface into a phase-7 design folder.
- Write a design bar covering: layout density, typographic
  hierarchy, color usage, spacing scale, motion language,
  illustration and iconography direction, and content tone. The
  bar is the acceptance contract for the rest of the phase.

#### 7.2 Visual system v2
- Audit current design-token usage and component primitives;
  redesign the type scale, color palette, spacing system, radii,
  shadows, and primitives toward the §7.1 design bar.
- Replace any placeholder copy, ad-hoc icons, or default
  framework theming with intentional choices.
- Update the marketing home above-the-fold so a first-time
  visitor immediately understands what the product is, who it
  is for, and how to try it — without scrolling.

#### 7.3 Surface-by-surface redesign loop
- Take one surface at a time through a screenshot → critique →
  revise loop driven by an AI design reviewer.
- Each pass updates the live page, captures fresh screenshots at
  all three viewports, and re-checks against the §7.1 design bar.
- Continue per surface until two consecutive review passes
  surface no new defects above a documented severity threshold.
- Order: marketing home → `/recommend` → `/roadmap` →
  `/pricing` and `/account` → `/history` → auth and onboarding
  → error / empty / loading states.

#### 7.4 Interaction polish and microcopy
- Loading skeletons and progressive-disclosure patterns on every
  surface that hits the API tier; no spinners-on-blank-page.
- Empty-state and error-state copy reviewed for clarity, tone,
  and recovery affordance.
- Microcopy pass on every CTA, label, tooltip, and inline help
  string; align with the §7.1 tone.
- Keyboard and focus-state polish: visible focus rings, logical
  tab order, escape-key dismissals.
- Motion: subtle, purposeful transitions; no gratuitous animation.

#### 7.5 Cross-device and responsive verification
- Capture v2 screenshots at three viewports (mobile, tablet,
  desktop) per surface.
- Resolve any responsive regressions from the v1 baseline.
- Verify the chat-plus-preview tab-collapse pattern on narrow
  viewports survives the v2 changes.

#### 7.6 Accessibility re-audit at v2
- Re-run a WCAG 2.1 AA audit on the v2 surfaces; the design bar
  must not regress accessibility relative to v1.
- Color-contrast checks on the new palette, focus-visible coverage
  on every interactive element, ARIA labeling on new primitives,
  reduced-motion preference respected.

#### 7.7 First-impression user testing
- Recruit at least five uninvolved testers; record a five-second
  test on the marketing home and a first-task test on
  `/recommend`.
- Acceptance: ≥80% of testers correctly identify the product
  category within five seconds; ≥80% complete a first
  recommendation without prompted help.

**Acceptance criteria**
- Every shipped surface from Phases 3–6 has v1 baseline and v2
  final screenshots committed under a phase-7 design folder,
  with the v2 versions meeting the §7.1 design bar.
- A first-time visitor can identify the product category, the
  value proposition, and how to start using it within five
  seconds of landing on the home page (verified per §7.7).
- No design-bar defects above the documented severity threshold
  remain open across two consecutive review passes on each
  surface.
- Accessibility audit shows no WCAG 2.1 AA regressions vs. v1.
- Phase 4 warm-path latency targets (§4.7) still hold after the
  v2 redesign ships — visual polish does not regress
  performance.

---

### Phase 8 — Security Hardening and Cost Controls

**Goal:** Make the platform safe to operate at scale before public
launch: hard cost ceilings that hold under attack, abuse-resistant
from day one, and clean against routine threat models.

The detailed hardening playbook — provider-by-provider cost-ceiling
internals, bot-mitigation vendor specifics, payment-fraud rules,
and pre-launch security-audit findings — is maintained outside this
public roadmap. The public commitments below are the externally
visible guarantees the phase exists to deliver.

#### 8.1 Hard global AI cost ceilings
- Daily and monthly spend ceilings per AI provider, enforced both
  at the provider billing layer and in the application before
  every model call.
- Alerting and automatic shut-off when a ceiling is reached.
- Per-account daily token and dollar cap enforced before any
  provider call.

#### 8.2 Bot and anonymous abuse hardening
- WAF in front of every `roadmodel.ai` route.
- CAPTCHA challenge triggered on burst patterns at `/recommend`
  and `/roadmap`.
- IP reputation scoring and behavioural fingerprinting feed the
  rate-limit decision.

#### 8.3 Account abuse and payment fraud
- Email verification on signup; reject disposable email domains.
- Payment-fraud screening with documented rules and review
  thresholds.
- Velocity checks on signups per IP and per email domain.
- Card-on-file required at signup for the paid tier.

#### 8.4 Auth and session hardening
- 2FA via TOTP (optional at v1, encouraged in UI copy).
- Session timeout and concurrent session caps.
- Sign-in alerts on new device or geography.

#### 8.5 Infrastructure and secrets
- All provider API keys in a managed secrets store — never in
  environment-variable plaintext.
- Documented key rotation procedure.
- Dependabot, secret scanning, and image scanning enabled on the
  OSS and SaaS repos.
- Security headers (CSP, HSTS, X-Frame-Options, Referrer-Policy)
  on every web response.
- Incident response runbook covering: provider API key
  compromise, database breach, payment fraud spike, denial of
  service, and AI ceiling breach.

#### 8.6 Prompt and output safety
- Per-request hard caps on input and output tokens.
- Output filtering blocks responses containing API key patterns
  or recognised credential formats before returning to the user.
- System prompt isolation: recommender and roadmap system prompts
  are never echoed in user-visible output.
- Sanitisation of user-uploaded files before AI processing
  (strip macros, executable content, oversized payloads).

#### 8.7 Pre-launch security audit
- Run an iterative security audit scoped against the OWASP Top 10
  and the threat surfaces enumerated in 8.1–8.6.
- Iterate until two consecutive runs surface no new critical or
  high findings.
- All critical and high findings remediated before public launch.

**Acceptance criteria**
- A simulated high-volume bot attack against `/recommend` cannot
  drive AI spend above the documented daily ceiling on any
  provider, verified in a staging load test.
- The manual emergency shut-off disables every AI call within
  60 seconds of activation, verified in a live drill.
- The pre-launch security audit shows zero open critical or high
  findings.
- WAF blocks ≥95% of synthetic bot traffic in pre-launch load
  tests.

---

### Phase 9 — Production Launch and Observability

**Goal:** Reach a state where `roadmodel.ai` is safe to announce
publicly and operate as a real paying-customer service.

#### 9.1 Observability and error handling
- Error tracking wired into the web and API tiers.
- Conversion-funnel analytics (home → recommend → signup → paid).
- Uptime monitoring with alerting to the maintainer.

#### 9.2 Pricing-catalog automation
- Weekly automated job re-fetches public pricing pages, diffs
  against the catalog JSON, and surfaces flagged changes for
  manual review.
- Manual approval merges the diff into the OSS repo and triggers
  a cache refresh in the SaaS.

#### 9.3 Launch readiness
- Public docs site for the CLI on a dedicated subdomain or
  `/docs`.
- Status page and incident response playbook.
- Pre-arrange increased AI provider quotas with each provider in
  use for the launch week.

#### 9.4 Public launch
- Announcement on HN, dev social, and relevant communities.
- Founder availability for support during the first 72 hours.

**Acceptance criteria**
- `roadmodel.ai` serves real paying customers with <1% request
  error rate over 7 consecutive days.
- The weekly catalog-diff job runs unattended and emails the
  maintainer when pricing pages change.
- A public incident at any single AI provider does not take down
  the recommender for that provider's competitors.

---

## 5. Cross-Cutting Concerns

### UX principles

The following principles bind every phase that adds a UI surface
and should not be re-litigated during phase planning.

**Three conversion moments**

1. **Anonymous → Free signup.** Trigger inline beneath the first
   completed recommendation. Never block the first try.
2. **Roadmap soft wall.** Anonymous visitors may see the chat
   input and type their first message; signup is required only at
   submit time.
3. **Free → Paid upgrade.** One CTA per free-tier output, placed
   next to the model label. No floating banners or popup nag at
   launch.

**Onboarding capture**

First signed-in session presents one optional screen capturing
subscription state (Claude / Cursor / ChatGPT) and budget priority
(`cheap | balanced | best`). Skip-friendly; defaults assume no
subscriptions and balanced priority.

**Model auto-routing**

Paid users are auto-routed to the best-fit frontier model by
default. An "advanced: choose model" override lives under
`/account/prefs`, with a small `(change)` affordance next to the
model label on each output.

**Accessibility**

WCAG 2.1 AA is the target for every UI surface from Phase 3
onward. Each phase audits before merge.

**Mobile**

Responsive web through v1; no dedicated mobile flows. The chat
plus preview panel collapses to a tab toggle on narrow viewports.
Native mobile is out of scope (see §6).

### Sequencing and dependencies

```
Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5 ──▶ Phase 6 ──▶ Phase 7 ──▶ Phase 8 ──▶ Phase 9
```

- Phases 1 and 2 run entirely on the maintainer's laptop with zero
  cloud spend; ship them before any infrastructure is provisioned.
- Phase 3 is the cutover phase — first paid cloud resources, first
  public DNS record, first TLS certificate. Provider-side billing
  caps go on at this point as the day-one cost ceiling.
- Phase 5 is the monetization cutover; everything before it is
  free-with-rate-limit.
- Phase 7 is the polish gate — v1 is feature-complete after
  Phase 6, but the v2 redesign is what ships to the public. No
  hardening or launch work runs in parallel; redesign defects
  routinely surface flow bugs that change the surfaces Phase 8
  has to harden.
- Phase 8 is the hardening gate; no public launch happens until
  the cost ceilings and security-audit results are green.
- Phase 9 is the irreversible "we are live" phase; the public
  announcement makes scaling-back visible to early adopters.

### Branch management strategy

#### Branching model

`main` is the single source of truth. All work happens on
short-lived branches (≤ 1 week) that merge into `main` via pull
request. `main` must always be:

- Green on CI.
- Deployable to the target environment.
- Tagged with semver on every production release.

#### Branch naming convention

| Prefix     | Purpose                            | Example                        |
|------------|------------------------------------|--------------------------------|
| `feature/` | Phase work or new feature          | `feature/phase-3-recommender`  |
| `fix/`     | Non-urgent bug fix                 | `fix/cost-comparison-rounding` |
| `hotfix/`  | Urgent production fix from `main`  | `hotfix/webhook-500`           |
| `chore/`   | Tooling, deps, housekeeping        | `chore/upgrade-next-15`        |
| `docs/`    | Documentation-only changes         | `docs/byo-key-setup`           |
| `perf/`    | Performance work                   | `perf/catalog-load-time`       |
| `release/` | Pre-release stabilisation          | `release/v1.0.0`               |

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
7. **No direct pushes to `main` — for anyone, including the
   repo owner.** Branch protection is configured with
   `enforce_admins: true`, so AI agents running with the
   maintainer's credentials cannot bypass the PR workflow.

#### Release and tagging

| Milestone tag      | Marker                                            |
|--------------------|---------------------------------------------------|
| `v0.1.0-phase-1`   | OSS CLI on PyPI                                   |
| `v0.2.0-phase-2`   | Platform recommendation + MCP server + catalog v2 |
| `v0.3.0-phase-3`   | roadmodel.ai live, anonymous recommender          |
| `v0.4.0-phase-4`   | Roadmap builder + auth + MD export                |
| `v0.5.0-phase-5`   | Paid tier + caps                                  |
| `v0.6.0-phase-6`   | Branded exports + pitchdeck                       |
| `v0.7.0-phase-7`   | Product polish + v2 redesign                      |
| `v0.8.0-phase-8`   | Security hardening + cost ceilings live           |
| `v1.0.0`           | Public launch                                     |

---

## 6. Out of Scope

Deliberately deferred to a future version:

- **Pro+ tier** with Opus 4.7 as default frontier, higher caps,
  priority support. Plan-in-architecture so the tier can be added
  quickly post-launch, but defer the actual SKU until usage data
  shows demand.
- Free hosted tier with included AI usage (revisit only after the
  paid tier validates demand).
- Multi-seat or team plans.
- Enterprise pricing tier.
- One-pager, long-form slide deck, UI/UX mockup, and pro-forma
  deliverables — pitchdeck is the only deliverable at MVP.
- Voice input or transcription for the roadmap chat surface.
- Public API access for paid users.
- Self-hosted version of the SaaS (only the CLI is OSS).
- Mobile app or mobile-optimised flows beyond responsive web.

---

## 7. Glossary

| Term  | Meaning                                              |
|-------|------------------------------------------------------|
| AA    | Artificial Analysis (benchmark data source)          |
| BYO   | Bring Your Own (e.g., API key)                       |
| MVP   | Minimum Viable Product                               |
| OSS   | Open Source Software                                 |
| PMF   | Product-Market Fit                                   |
| SaaS  | Software as a Service                                |
| SSR   | Server-Side Rendering                                |
| TLS   | Transport Layer Security                             |
