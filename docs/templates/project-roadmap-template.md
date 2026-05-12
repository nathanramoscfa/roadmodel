<!--
=============================================================
PROJECT ROADMAP TEMPLATE
=============================================================
PURPOSE
  A reusable skeleton for a multi-phase project roadmap.
  Hand this file to the AI together with a short brief of the
  project. The AI fills in every <PLACEHOLDER>, removes any
  HTML-comment guidance, and produces a finished roadmap in the
  exact style this template enforces.

STYLE RULES (the AI MUST follow)
  - All prose wraps at 80 characters per line.
  - Use Markdown tables for any list of >3 structured items
    (gaps, controls, costs, risks, milestones, etc.).
  - Use ASCII boxes (┌ ┐ └ ┘ │ ─ ▶) for architecture diagrams.
  - Every phase ends with an "Acceptance criteria" section
    written as a bulleted list of testable statements.
  - Every phase carries a one-line metadata badge:
      **Complexity:** … · **Risk:** … · **Cloud cost:** …
  - Prefer short, declarative sentences over hedged paragraphs.
  - Never invent numbers; mark unknowns as "TBD".
  - Output the finished document in raw Markdown only.
  - Strip every <!-- ... --> instruction block before delivery.
=============================================================
-->

# <PROJECT_NAME> — <ROADMAP_SUBTITLE>

> **Status:** <Draft v1 | Approved | In progress>
> **Owner:** <NAME, ROLE>
> **Audience:** <Internal team | External stakeholders | …>
> **Target environment:** <Local | AWS | Azure | GCP | …>
> **Last updated:** <Month YYYY>

<!--
1-3 paragraph executive lead. Answer:
  - What does this roadmap take the project FROM and TO?
  - Why now?
  - Link to any prior/archived roadmap that this supersedes.
-->

---

## 1. Executive Summary

<!--
4-6 sentences describing the current state and the destination.
Then enumerate the 3-5 hard constraints driving the work.
Close with a one-line "path" sentence summarising the order of
operations (e.g. "clean → secure → authenticate → cloud →
operate").
-->

The <PROJECT_NAME> is <one-line current-state summary>. It now
needs to <one-line destination summary> while satisfying these
constraints:

1. **<Constraint 1>.** <one sentence>.
2. **<Constraint 2>.** <one sentence>.
3. **<Constraint 3>.** <one sentence>.
4. **<Constraint 4>.** <one sentence>.

The path: **<verb> → <verb> → <verb> → <verb>**. <One sentence
on phase independence and sequencing.>

### <Optional: Initial user roster / scope table>

| <Header A> | <Header B>             | <Header C>          |
|------------|------------------------|---------------------|
| <row>      | <row>                  | <row>               |

---

## 2. Current State Assessment

### What works today
<!-- Bullet list of features/capabilities already in place. -->
- <Capability 1>.
- <Capability 2>.
- <Capability 3>.

### Gaps blocking <DESTINATION_STATE>

<!--
Numbered table of every concrete gap. Severity is one of:
Critical | High | Medium | Low. Order rows by severity, then
by phase that addresses them.
-->

| #  | Gap                                       | Severity |
|----|-------------------------------------------|----------|
| 1  | <Gap description>                         | Critical |
| 2  | <Gap description>                         | High     |
| 3  | <Gap description>                         | Medium   |
| …  | …                                         | …        |

These gaps drive the phase ordering below.

---

## 3. Target Architecture

<!--
ASCII diagram of the destination architecture. Use the same
box-drawing characters demonstrated below. Label every
component, every trust boundary, and every data flow direction.
Keep the diagram under 30 lines. Follow with a 2-3 sentence
description of where everything lives and what the only public
surface is.
-->

```
        ┌──────────────────────────────┐
        │  <External identity / edge>  │
        └────────────┬─────────────────┘
                     │ <protocol>
                     ▼
   ┌─────────────────────────────────────────┐
   │  <Compute tier — frontend>              │
   └────────────────────┬────────────────────┘
                        │ <protocol + auth>
                        ▼
   ┌─────────────────────────────────────────┐
   │  <Compute tier — backend>               │
   └─────┬─────────────────────────────┬─────┘
         ▼                             ▼
   ┌──────────────┐               ┌──────────────┐
   │  <Data>      │               │  <Secrets>   │
   └──────────────┘               └──────────────┘
```

<One paragraph describing region, network boundary, and the
single public ingress point.>

---

## 4. Phased Roadmap

<!--
The heart of the document. Produce 3–8 phases. Each phase MUST
have:
  1. ### Phase N — <Title>
  2. **Goal:** one sentence.
  3. Metadata line: **Complexity:** … · **Risk:** … ·
     **Cloud cost:** …
  4. Numbered sub-sections (#### N.1, #### N.2, …) describing
     concrete work.
  5. Tables, code blocks, or schema dumps where they clarify.
  6. **Acceptance criteria** — bulleted, testable list.
Phases are ordered so each is independently shippable and the
dependency graph in §5 is honoured.
-->

### Phase 1 — <Phase Title>

**Goal:** <One sentence describing the outcome of this phase.>

**Complexity:** <Low | Medium | High> · **Risk:**
<Low | Medium | High> · **Cloud cost:** <$0 | …>

#### 1.1 <Sub-section title>
- <Action item>.
- <Action item>.

#### 1.2 <Sub-section title>
- <Action item>.
- <Action item>.

<!-- Add more sub-sections (1.3, 1.4, …) as needed. -->

**Acceptance criteria**
- <Testable statement 1>.
- <Testable statement 2>.
- <Testable statement 3>.

---

### Phase 2 — <Phase Title>

**Goal:** <one sentence>.

**Complexity:** … · **Risk:** … · **Cloud cost:** …

#### 2.1 <Sub-section title>
- <Action>.

#### 2.2 <Sub-section title>
- <Action>.

**Acceptance criteria**
- <Testable statement>.

---

<!-- Repeat the phase block for Phase 3, 4, … N. -->

### Phase N — <Final Phase Title>

**Goal:** <one sentence>.

**Complexity:** … · **Risk:** … · **Cloud cost:** …

#### N.1 <Sub-section title>
- <Action>.

**Acceptance criteria**
- <Testable statement>.

---

## 5. Cross-Cutting Concerns

### Cost projection (monthly, USD, <pilot|prod> scale)

<!-- Skip this section if cost is irrelevant to the project. -->

| Service                                  | Estimate    |
|------------------------------------------|-------------|
| <Service 1>                              | <$X–Y>      |
| <Service 2>                              | <$X–Y>      |
| **Total**                                | **<$X–Y>**  |

### Sequencing & dependencies

<!--
ASCII flow showing which phases depend on which. Use ──▶ for
sequential dependency and branch with ┌─ when phases can run
in parallel.
-->

```
Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5
                                                  │
                                                  ▼
                                          Phase 6 ──▶ Phase 7
```

- <One bullet per dependency or sequencing rule.>
- <Note any phase that can be done locally with zero spend.>
- <Note the cutover phase (the irreversible one).>

### Branch management strategy

<!--
Include this section for any project with >1 contributor or
any compliance/audit requirement. Skip for solo throwaway
work.
-->

#### Branching model

`main` is the single source of truth. All work happens on
short-lived branches (≤ 1 week) that merge into `main` via
pull request. `main` must always be:

- Green on CI.
- Deployable to the target environment.
- Tagged with semver on every production release.

#### Branch naming convention

| Prefix     | Purpose                          | Example                          |
|------------|----------------------------------|----------------------------------|
| `feature/` | Phase work or new feature        | `feature/phase-1-<slug>`         |
| `fix/`     | Non-urgent bug fix               | `fix/<slug>`                     |
| `hotfix/`  | Urgent production fix from `main`| `hotfix/<slug>`                  |
| `chore/`   | Tooling, deps, housekeeping      | `chore/<slug>`                   |
| `docs/`    | Documentation-only changes       | `docs/<slug>`                    |
| `perf/`    | Performance work                 | `perf/<slug>`                    |
| `release/` | Pre-release stabilisation        | `release/v<X.Y.Z>`               |

#### Pull request rules
1. **Scope discipline.** One PR per phase sub-section.
2. **PR template.** Roadmap reference, summary, test plan,
   screenshots for UI, breaking-change notes, rollback plan.
3. **CI green required.** Lint, type-check, tests, security
   scans all pass before merge.
4. **No force-push to `main`.** Allowed on personal branches
   only before review opens.
5. **Squash-merge** to `main` so each phase reads as one
   clean commit.
6. **Conventional Commits** on the squash message.

#### Release & tagging

| Milestone tag           | Marker                                |
|-------------------------|---------------------------------------|
| `v0.10.0-phase-1`       | <Phase 1 deliverable>                 |
| `v0.20.0-phase-2`       | <Phase 2 deliverable>                 |
| …                       | …                                     |
| `v1.0.0`                | <Production launch>                   |

### Risks & mitigations

| Risk                                  | Mitigation              |
|---------------------------------------|-------------------------|
| <Risk 1>                              | <Mitigation>            |
| <Risk 2>                              | <Mitigation>            |
| <Risk 3>                              | <Mitigation>            |

---

## 6. Out of Scope

The following are deliberately deferred to a future version:

- <Deferred item 1>.
- <Deferred item 2>.
- <Deferred item 3>.

---

## 7. Glossary

<!-- Only include if the document uses domain-specific jargon. -->

| Term       | Meaning                                          |
|------------|--------------------------------------------------|
| <ACRONYM>  | <Definition>                                     |
| <ACRONYM>  | <Definition>                                     |

---

## 8. Phase Complexity Summary

| Phase | Description                       | Complexity   |
|-------|-----------------------------------|--------------|
| 1     | <Phase 1 title>                   | <Low/Med/Hi> |
| 2     | <Phase 2 title>                   | <Low/Med/Hi> |
| 3     | <Phase 3 title>                   | <Low/Med/Hi> |
| …     | …                                 | …            |
