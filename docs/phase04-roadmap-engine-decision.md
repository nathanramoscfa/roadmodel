<!-- docs/phase04-roadmap-engine-decision.md -->

# Phase 4 — Roadmap engine dogfooding decision

> **Status:** Pending preview-deploy validation. The five
> dogfooding conversations required by §9.2 of the Phase 4
> private roadmap run against this PR's preview deployment.
> Update the table and the decision header below once those
> runs land.

## 1. Methodology

The Phase 4 free signed-in default engine is **Gemini 2.5 Flash**
via the `@google/genai` SDK direct from Vercel Functions — the
cost-economics override pick from the Phase 4 Overview's "Engine
selection per docs/model-selector.txt + free-tier SaaS-backend
economics" table. The selector's strict planning-A choice is
Gemini 3 Flash; the override stays on 2.5 Flash so long as the
dogfooding gate confirms 2.5 Flash produces template-compliant
roadmaps for the kinds of briefs free signed-in users actually
send.

Each row of the table below corresponds to one end-to-end
roadmap-builder conversation against the **live preview
deployment** for this PR (no mocks, no local stubs). A brief
counts as covered when:

- the assistant asked ≥1 and ≤5 clarifying questions before
  emitting a draft (the orientation segment in
  `web/lib/roadmap-prompts.ts` instructs "at most 3–5
  clarifying questions");
- the final draft loaded into `PreviewPanel` without renderer
  errors (PreviewPanel parses `RoadmapDraft` shaped events from
  the SSE stream);
- the output matched the
  `docs/templates/project-roadmap-template.md` section structure:
  Executive Summary, Phased Roadmap, Acceptance Criteria (per
  phase), Glossary.

Briefs span five domains to cover the breadth of expected user
intent: SaaS, mobile app, infra, ML pipeline, and an internal
tool.

## 2. Per-conversation assessment

The five briefs below are the dogfooding payloads — paste each
into the signed-in `/roadmap` composer on the preview deploy and
let the conversation run end-to-end (clarifying turns + final
draft). One row per brief.

| Brief slug         | Domain          | ≥1–≤5 clarifying Qs | PreviewPanel clean | Template-compliant sections | Notes |
| ------------------ | --------------- | ------------------- | ------------------ | --------------------------- | ----- |
| `saas-mvp`         | SaaS            | TBD                 | TBD                | TBD                         | TBD   |
| `mobile-coach`     | Mobile app      | TBD                 | TBD                | TBD                         | TBD   |
| `infra-rebuild`    | Infra           | TBD                 | TBD                | TBD                         | TBD   |
| `ml-pipeline`      | ML pipeline     | TBD                 | TBD                | TBD                         | TBD   |
| `internal-tool`    | Internal tool   | TBD                 | TBD                | TBD                         | TBD   |

**Brief payloads** (paste verbatim, one per conversation):

- `saas-mvp` — "I want to ship a B2B SaaS MVP for small-team
  expense reporting — receipt upload, OCR line-item extraction,
  per-employee policy rules, weekly accounting export. Solo
  founder, six-month runway, no infra team. Help me plan the
  rollout."

- `mobile-coach` — "A mobile-first habit-coaching app — daily
  check-in prompt, streak tracking, weekly summary, a small set
  of behaviorally-grounded nudges. iOS + Android, no web. Two
  engineers, twelve weeks to TestFlight. What's the roadmap?"

- `infra-rebuild` — "We're migrating an aging on-prem Kubernetes
  cluster to a managed cloud Kubernetes service. Mix of stateful
  + stateless workloads, ~40 microservices, regulated industry
  with audit requirements. Plan the cutover."

- `ml-pipeline` — "We need an offline-batch ML training pipeline
  for a recommendation model — feature store, daily training,
  versioned model artifacts, A/B-deploy hooks, drift monitoring.
  Two ML engineers + one platform engineer. Roadmap?"

- `internal-tool` — "Build an internal admin tool that lets our
  CS team unblock account-suspension cases — read-only customer
  search, audit-logged actions, role-based access, ticket-system
  integration. One engineer, eight weeks. Plan it out."

## 3. Decision

**Tentative: PASS** (Gemini 2.5 Flash stays as the Phase 4 free
signed-in default; `FRONTIER_ROADMAP_ENABLED` remains false; the
model-string default in `web/lib/roadmap-engine.ts` stays
`'gemini-2.5-flash'`). The five dogfooding rows above resolve
this decision into a final PASS or FAIL after the PR's preview
deploys.

On **FAIL**, the maintainer flips the model-string default to
`'gemini-3-flash'` in-phase, updates `infra/README.md`'s
"Environment variables" table to note the override (no env-var
change is required — the model swap is code-only and reuses the
same `GOOGLE_API_KEY`), and re-runs the same five briefs against
Gemini 3 Flash. The §4 addendum below captures that re-run.

## 4. FAIL addendum — Gemini 3 Flash re-run

> Populated only if §3 lands as FAIL. The addendum exists to
> confirm the delta is engine quality (the briefs work under 3
> Flash), not template-wiring (the briefs fail under both Google
> engines, which would indicate a system-instruction bug Step 4
> must fix before merging — at that point the dogfooding gate
> re-runs against Flash with the fixed instruction before
> escalating).

| Brief slug         | ≥1–≤5 clarifying Qs | PreviewPanel clean | Template-compliant sections | Notes |
| ------------------ | ------------------- | ------------------ | --------------------------- | ----- |
| `saas-mvp`         | —                   | —                  | —                           | —     |
| `mobile-coach`     | —                   | —                  | —                           | —     |
| `infra-rebuild`    | —                   | —                  | —                           | —     |
| `ml-pipeline`      | —                   | —                  | —                           | —     |
| `internal-tool`    | —                   | —                  | —                           | —     |

**No Anthropic SDK is added in Phase 4** — that dependency
belongs to the Phase 5 paid frontier scope. The in-phase
escalation stays inside Google (2.5 Flash → 3 Flash) so the
adapter surface, caching API, billing meter, and provider key
all stay constant; only the model string changes.

## 5. Reference

- "Engine selection per `docs/model-selector.txt` + free-tier
  SaaS-backend economics" table — `private/phase04-roadmap.md`
  Overview section.
- "Engine-choice cost arithmetic" paragraph — same file, same
  section.
- "Engine-choice dogfooding gate" paragraph — same file, same
  section. This file is the deliverable that paragraph requires.
- Prompt assembly contract — `web/lib/roadmap-prompts.ts`
  (orientation, template prefix, profile suffix; cache-prefix
  contract Step 6 builds on).
- Engine wrapper — `web/lib/roadmap-engine.ts`
  (`createRoadmapStream`, `DEFAULT_ROADMAP_MODEL`).
- Route handler — `web/app/api/roadmap/route.ts` (Zod validation,
  session, per-user 3-per-30-day cap, SSE response).
- Public ROADMAP capability matrix entry for free signed-in
  roadmaps (3 / month) — `ROADMAP.md` §9.
