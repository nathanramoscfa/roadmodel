<!--
=============================================================
PHASE ROADMAP TEMPLATE
=============================================================
PURPOSE
  A reusable skeleton for a deep-dive roadmap of ONE phase
  (or sub-phase) of a larger project. Use this when a phase
  in the parent project roadmap is large enough that it needs
  its own dedicated planning document — typically because it
  introduces new architecture, has its own multi-week task
  breakdown, or carries its own acceptance criteria.

WHEN TO USE
  - The parent ROADMAP.md treats this phase as a single
    section; this file expands that section into an
    executable plan.
  - Numbering convention: `phaseNN-roadmap.md` where NN is
    the phase number (e.g. `phase31-roadmap.md` for
    Phase 3.1, `phase04-roadmap.md` for Phase 4).

STYLE RULES (the AI MUST follow)
  - All prose wraps at 80 characters per line.
  - Use Markdown tables for any list of >3 structured items.
  - Use ASCII boxes (┌ ┐ └ ┘ │ ─ ▶) for diagrams.
  - Use fenced code blocks for SQL, schemas, configs, shell.
  - Numbered sub-sections (#### N.1, #### N.2, …) under each
    work area.
  - End the document with a testable Acceptance Criteria
    section. No phase roadmap is complete without one.
  - Prefer concrete, declarative sentences. No hedging.
  - Mark every unknown as "TBD".
  - Output the finished document in raw Markdown only.
  - Strip every <!-- ... --> instruction block before
    delivery.
=============================================================
-->

# <PROJECT_NAME> — Phase <N[.M]>: <Phase Title>

> **Status:** <Planned | In progress | Blocked | Done>
> **Owner:** <NAME, ROLE>
> **Parent roadmap:** [<ROADMAP.md or link>](<path>)
> **Depends on:** <Phase X complete | none>
> **Unblocks:** <Phase Y, Phase Z>
> **Target dates:** <Start: Mon YYYY · End: Mon YYYY>
> **Last updated:** <Month YYYY>

---

## 1. Context

<!--
2-4 paragraphs. Answer:
  - Where does this phase fit in the parent roadmap?
  - What did the previous phase deliver that we now build on?
  - What single problem does this phase solve?
  - Why is it worth its own dedicated document (rather than a
    section in the parent roadmap)?
-->

<Paragraph 1: project context.>

<Paragraph 2: what the previous phase delivered.>

<Paragraph 3: the problem this phase solves and why it
deserves its own document.>

---

## 2. Goal & Non-Goals

### Goal

<One sentence describing the outcome of this phase.>

### Non-goals

<!-- Be explicit about what this phase will NOT do. -->
- <Item explicitly deferred>.
- <Item explicitly deferred>.
- <Item explicitly deferred>.

### Metadata

**Complexity:** <Low | Medium | High> · **Risk:**
<Low | Medium | High> · **Cost impact:**
<$0 | <$X–Y / month>> · **Estimated effort:** <N person-weeks>

---

## 3. Prerequisites

<!--
Concrete checklist of what MUST be true before this phase
starts. Tools, access, data, prior phases, sign-offs.
-->

- [ ] <Prerequisite 1>.
- [ ] <Prerequisite 2>.
- [ ] <Prerequisite 3>.

---

## 4. Design

<!--
Technical design for the phase. Include only the subsections
that apply. Drop the ones that don't.
-->

### 4.1 Architecture changes

<!--
ASCII diagram showing the delta between the current state and
the post-phase state. Highlight what's new with `[NEW]` tags.
-->

```
   ┌──────────────────┐         ┌──────────────────┐
   │  <Existing>      │  ──▶    │  <Existing>      │
   └──────────────────┘         └──────────┬───────┘
                                           │ [NEW]
                                           ▼
                                ┌──────────────────┐
                                │  <New component> │
                                └──────────────────┘
```

### 4.2 Data model changes

<!-- Include only if the phase touches the schema. -->

```sql
-- New table or column added in this phase.
<table_name> (
    <column>    <TYPE> <constraints>,
    ...
)
```

### 4.3 API changes

<!-- Include only if the phase touches the API surface. -->

| Method | Path                  | Auth      | Purpose         |
|--------|-----------------------|-----------|-----------------|
| GET    | <`/api/...`>          | <scope>   | <one line>      |
| POST   | <`/api/...`>          | <scope>   | <one line>      |

### 4.4 Configuration & secrets

<!-- New env vars, feature flags, secrets. Include or drop. -->

| Key                  | Source                | Required | Default |
|----------------------|-----------------------|----------|---------|
| `<ENV_VAR_NAME>`     | <Vault | .env | …>    | <Y/N>    | <value> |

---

## 5. Work Breakdown

<!--
The executable task list. Each work area is a numbered
sub-section. Tasks under each are concrete, action-verb
bullets that a single PR could close.
-->

### 5.1 <Work area title>

- <Action item>.
- <Action item>.
- <Action item>.

### 5.2 <Work area title>

- <Action item>.
- <Action item>.

### 5.3 <Work area title>

- <Action item>.
- <Action item>.

<!-- Add 5.4, 5.5, … as needed. Aim for 3–6 work areas. -->

---

## 6. Test Plan

<!--
How will you prove the phase works? Combine unit, integration,
and manual checks. List the actual test names or scenarios.
-->

### Unit tests
- <Test scenario>.
- <Test scenario>.

### Integration tests
- <Scenario covering end-to-end behaviour>.
- <Scenario covering error path>.

### Manual / exploratory
- <Manual check 1>.
- <Manual check 2>.

### Performance / load (if applicable)
- <Target metric and how it's measured>.

---

## 7. Rollout Plan

<!--
How does the phase reach users? Include a rollback path.
Drop this section for purely-internal phases (refactors).
-->

1. <Step 1 — e.g. deploy to staging behind feature flag>.
2. <Step 2 — e.g. internal smoke test>.
3. <Step 3 — e.g. enable for pilot users>.
4. <Step 4 — e.g. enable for all users>.

**Rollback:** <One sentence describing how to revert.>

---

## 8. Risks & Mitigations

| Risk                                  | Likelihood | Mitigation              |
|---------------------------------------|-----------:|-------------------------|
| <Risk description>                    | <L/M/H>    | <Mitigation>            |
| <Risk description>                    | <L/M/H>    | <Mitigation>            |
| <Risk description>                    | <L/M/H>    | <Mitigation>            |

---

## 9. Branch & PR Plan

<!--
Concrete branches and PRs that will be opened. This makes the
phase auditable in the git history.
-->

| Branch                                 | Closes              |
|----------------------------------------|---------------------|
| `feature/phase-<N>-<slug-1>`           | §5.1                |
| `feature/phase-<N>-<slug-2>`           | §5.2                |
| `feature/phase-<N>-<slug-3>`           | §5.3                |

**Squash-merge to `main`** with Conventional Commits messages.
**Tag** `v0.<N0>.0-phase-<N>` once all PRs land and acceptance
criteria pass.

---

## 10. Acceptance Criteria

<!--
Testable, binary statements. The phase is "done" when every
bullet is true. Aim for 4–8 bullets. Each must be observable
in CI, the app, or the database — not aspirational.
-->

- [ ] <Statement that can be verified by an automated test>.
- [ ] <Statement that can be verified by inspecting the UI>.
- [ ] <Statement that can be verified by a SQL query>.
- [ ] <Statement that can be verified by a metric/dashboard>.
- [ ] <Statement that can be verified by a doc deliverable>.

---

## 11. Open Questions

<!--
Anything that needs decision/research before or during the
phase. Each item names an owner and a needed-by date. Drop
this section if the design is fully settled.
-->

| #  | Question                                  | Owner    | Needed by   |
|----|-------------------------------------------|----------|-------------|
| 1  | <Question>                                | <name>   | <Mon YYYY>  |
| 2  | <Question>                                | <name>   | <Mon YYYY>  |
