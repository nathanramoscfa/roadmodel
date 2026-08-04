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
  - Every phase's "Acceptance criteria" MUST include at least
    one security check (secret scan clean, SAST + dependency
    audit green, sensitive-data handling verified). Security is
    a per-phase exit gate, never a final-phase afterthought —
    an issue introduced in Phase 2 must be caught in Phase 2,
    before its work is committed, pushed, or merged.
  - Every phase carries a one-line metadata badge:
      **Complexity:** … · **Risk:** … · **Cloud cost:** … ·
      **Handles sensitive data:** <Yes/No — PII, secrets, auth>
  - §5 "Security & privacy strategy" is MANDATORY for any
    project touching user data, secrets, PII, credentials, or
    auth. Only omit it for a throwaway with zero sensitive
    surface, and say so explicitly if you do.
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
     **Cloud cost:** … · **Handles sensitive data:** …
  4. Numbered sub-sections (#### N.1, #### N.2, …) describing
     concrete work.
  5. Tables, code blocks, or schema dumps where they clarify.
  6. **Acceptance criteria** — bulleted, testable list that
     INCLUDES at least one security check for the surface the
     phase touches (see §5 "Security & privacy strategy").
Phases are ordered so each is independently shippable and the
dependency graph in §5 is honoured.
-->

### Phase 1 — <Phase Title>

**Goal:** <One sentence describing the outcome of this phase.>

**Complexity:** <Low | Medium | High> · **Risk:**
<Low | Medium | High> · **Cloud cost:** <$0 | …> ·
**Handles sensitive data:** <Yes/No — PII, secrets, auth>

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
- **Security:** the §5 security gate ran clean on this
  phase's work — no secrets/PII committed, SAST + dependency
  audit green, and the new/changed surface handles sensitive
  data per §5 (least privilege, encrypted in transit + at
  rest, no PII in logs). <Name the concrete check.>

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
3. **CI green required.** Lint, type-check, tests, and the
   security scans (secret scan, SAST, dependency audit) all
   pass before merge. CI re-runs the same security gate the
   pre-commit hook ran locally — defense in depth, so a bypassed
   or skipped local hook still cannot land an issue on `main`.
4. **No force-push to `main`.** Allowed on personal branches
   only before review opens.
5. **Squash-merge** to `main` so each phase reads as one
   clean commit.
6. **Conventional Commits** on the squash message.

#### Step lifecycle

Every step / sub-section of every phase follows the same
six-stage lifecycle, in order, with no exceptions. Each stage
is a hard checkpoint — if any stage is skipped, branch
protection or the next step's Stage 1 will fail loudly, and
that is the safety net. AI coding agents executing a step MUST
complete all six stages before declaring the step done.

1. **Create the branch.** Before any Read / Edit / Bash, run
   `git checkout -b <prefix>/<slug>` from a clean,
   up-to-date `main` (e.g. `feature/phase-2-cost-estimator`).
   The branch name comes from the roadmap step's `**Branch:**`
   line, or from the naming convention above for ad-hoc work.

2. **Work on the branch, and pass the security gate before
   every commit.** All commits land here. Never push to `main`
   directly — branch protection rejects it. Before each
   `git commit`, the local security gate (see §5 "Security &
   privacy strategy" → "Per-step security gate") must run and
   pass: secret scan clean, SAST clean, dependency audit clean,
   and no sensitive data (PII, credentials, tokens) in the
   diff. The gate is wired into the pre-commit hook and is
   fail-closed — a finding blocks the commit, so a security
   issue introduced while implementing this step is caught here,
   before it ever reaches the branch, the PR, or `main`.

3. **Open the PR.** `gh pr create --base main --head <branch>`
   with a Conventional Commits title and a body referencing the
   roadmap step and its acceptance criteria. One PR per step.

4. **Wait for green checks, then squash-merge.** Every required
   status check must report success. If the PR goes BEHIND
   main, refresh with `gh pr update-branch --rebase` — never
   merge `main` into the branch when the repo enforces linear
   history. Once green:

   ```sh
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

5. **Retire the branch (remote + local).** The
   `--delete-branch` flag and the repo's
   `delete_branch_on_merge: true` setting retire the remote
   automatically. Sync local state and prune the merged branch
   plus any other `[gone]` labels:

   ```sh
   git switch main
   git pull --ff-only origin main
   git fetch --prune origin
   git branch -vv | grep ': gone]' | awk '{print $1}' \
     | xargs -r git branch -D
   ```

6. **New conversation, next step.** Phase-boundary hygiene:
   close the current Claude Code / Cursor / Codex session and
   open a fresh one before starting the next step. The new
   conversation begins again at Stage 1 with the next step's
   `**Branch:**` line driving the `git checkout -b` command.
   No work straddles two steps.

#### Release & tagging

| Milestone tag           | Marker                                |
|-------------------------|---------------------------------------|
| `v0.10.0-phase-1`       | <Phase 1 deliverable>                 |
| `v0.20.0-phase-2`       | <Phase 2 deliverable>                 |
| …                       | …                                     |
| `v1.0.0`                | <Production launch>                   |

### Security & privacy strategy

<!--
MANDATORY for any project that touches user data, secrets,
PII, credentials, payments, or auth. The point of this
section is that security is woven into EVERY step of every
phase — not bolted on at the end — so an issue introduced
while implementing a step is caught during development,
before the commit, push, and merge. Fill in the data
classification and the controls; keep the "Per-step security
gate" subsection intact — it is the mechanism the whole
roadmap relies on.
-->

#### Data classification

What sensitive data does this project touch, and how is each
class protected? Fill one row per class actually present;
delete rows that do not apply.

| Data class                     | Present? | Handling requirement                                  |
|--------------------------------|----------|-------------------------------------------------------|
| Client / user PII              | <Yes/No> | Encrypt in transit + at rest; least-privilege access; never in logs. |
| Authentication secrets / creds | <Yes/No> | Secrets manager only; never in source, env files, or client bundles. |
| API keys / service tokens      | <Yes/No> | Server-side only; rotate on exposure; scoped minimally.              |
| Payment / financial data       | <Yes/No> | Delegate to a PCI-compliant processor; never store PANs.            |
| Health / regulated data        | <Yes/No> | Meet the governing regime (HIPAA/GDPR/…); document the basis.       |

#### Threat model (one-paragraph)

<Name the assets worth protecting (the data classes above),
the trust boundaries from §3, the realistic adversaries
(external attacker, malicious insider, a compromised
dependency, a leaked coding-agent transcript), and the top
3-5 abuse cases the design must resist. Keep it to a
paragraph plus the risk rows below.>

#### Per-step security gate

This is the core control. Every step of every phase runs the
SAME local, fail-closed security gate before any commit, so a
security issue introduced while implementing a step is caught
in development — before it reaches the branch, the PR, or
`main`. A coding agent handed a phase step must treat this
gate as part of the step's definition of done, exactly like
tests.

The gate is wired into the repo's pre-commit hook (`.githooks/`
+ `git config core.hooksPath .githooks`, or a `pre-commit`
framework config) so it runs automatically, and it is
re-run in CI so a bypassed hook cannot land an issue on `main`.
It has four checks; all must be clean:

| Check                | What it catches                                   | Example tooling                                        |
|----------------------|---------------------------------------------------|--------------------------------------------------------|
| Secret / PII scan    | Committed credentials, tokens, keys, real PII     | `gitleaks`, `detect-secrets`, `trufflehog`             |
| SAST (static a.)     | Injection, unsafe deserialization, weak crypto, path traversal | `bandit` (Py), `semgrep`, `eslint-plugin-security` (JS/TS) |
| Dependency audit     | Known-vulnerable / yanked / typo-squatted deps    | `pip-audit`, `npm audit --audit-level=high`, `osv-scanner` |
| Sensitive-data review| PII in logs, secrets in client bundles, over-broad scopes, missing encryption | Diff review against the data-classification table above |

Rules for the gate:

1. **Fail-closed.** Any finding blocks the commit. The bypass
   (e.g. an env var) is for genuine emergencies only and every
   use is recorded in the PR body with a justification.
2. **Runs per commit, not per phase.** Because it is a
   pre-commit hook, the developer/agent cannot defer security
   to "the end" — the smallest unit of work is already gated.
3. **Mirrored in CI.** The same four checks run as required
   status checks so the merge is blocked even if the local
   hook was skipped (PR rule 3).
4. **Owned by acceptance criteria.** Every phase's Acceptance
   criteria names the concrete security check for its surface;
   the phase is not "done" until the gate is green on its work.

#### Security controls by layer

<!-- Skip rows that do not apply. These are the standing
controls the design must carry, distinct from the per-commit
gate above. -->

| Layer               | Control                                                       |
|---------------------|--------------------------------------------------------------|
| Identity / auth     | <MFA, session policy, token lifetime, least-privilege roles> |
| Transport           | <TLS everywhere, HSTS, cert management>                       |
| Data at rest        | <Encryption, key management, backup encryption>              |
| Secrets             | <Manager (Vault/cloud KMS/keychain); never in source/env>    |
| Network / edge      | <WAF, rate limits, allow-lists, private networking>          |
| Dependencies        | <Pinned + audited; automated update + audit cadence>         |
| Logging / audit     | <No PII/secrets in logs; tamper-evident audit trail>         |
| Incident response   | <Rotation runbook, disclosure path, on-call owner>           |

#### Vulnerability handling

Security findings — from the gate, CI, a scanner, or a report
— follow the same discover → triage → track → fix → verify
loop as any other defect, but jump the queue by severity:
Critical/High are fixed on a `hotfix/` or `fix/` branch before
new feature work continues; Medium/Low are tracked as issues
with an owner and a due date. Never silence a finding without a
recorded justification.

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
