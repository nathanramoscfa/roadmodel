<!--
=============================================================
PHASE ROADMAP TEMPLATE
=============================================================
PURPOSE
  A reusable skeleton for a deep-dive roadmap of ONE phase
  (or sub-phase) of a larger project. Use this when a phase
  in the parent project roadmap is large enough that it needs
  its own dedicated planning document — typically because it
  spans multiple steps, each of which is itself a discrete
  Cursor / Claude Code session with its own model selection,
  context bundle, and acceptance criteria.

WHEN TO USE
  - The parent ROADMAP.md treats this phase as a single
    section; this file expands that section into an
    executable plan that can be handed to a coding agent
    one step at a time.
  - Numbering convention: `phaseNN-roadmap.md` where NN is
    the phase number (e.g. `phase31-roadmap.md` for
    Phase 31, `phase04-roadmap.md` for Phase 4).

PLACEHOLDER SYNTAX
  - Prose placeholders use {{double-curly}} form so that
    Markdown renderers never mistake them for HTML tags
    (`<like-this>` gets eaten by the renderer — never use it
    outside fenced code blocks).
  - Inside fenced ```xml <task>``` blocks, normal XML angle
    brackets are fine — the fence protects them.
  - Replace every {{token}} with concrete content before
    shipping. A finished roadmap should contain zero
    {{...}} tokens.

STYLE RULES (the AI MUST follow)
  - All prose wraps at 80 characters per line.
  - Use Markdown tables for any list of >3 structured items.
  - Use ASCII boxes / arrows (┌ ┐ └ ┘ │ ─ ▶ ↓) for the
    execution-order diagram.
  - Use fenced code blocks for SQL, schemas, configs, shell,
    and for the XML <task> prompts handed to coding agents.
  - Numbered steps (## Step N — Title). Each step is a
    self-contained Cursor / Claude Code session.
  - Every step carries: Goal blockquote, Branch line
    (`feature/phaseNN-stepM-<slug>` — see the Overview
    "Branch strategy", "Branch-first execution rule", and
    "Step lifecycle" paragraphs; the operator runs
    `git checkout -b <branch>` BEFORE reading files or editing
    anything in the step, follows the six-stage lifecycle for
    the rest of the step, and starts the next step in a fresh
    conversation), Settings table, Model rationale paragraph,
    XML <task> prompt (which MUST carry a <security> block
    alongside its <lifecycle> block — see below), and an
    Acceptance Criteria bullet list whose FINAL bullet is
    always a security check. The Settings table is
    PLATFORM-specific so it mirrors the actual surface the
    operator will see — each surface exposes a different
    dial, and the table rows must match the panel labels
    exactly:
      • Claude Code: Model / Platform / Effort / Thinking
        (On/Off) / Conversation. Effort values are Low /
        Medium / High / Extra High / Max. The Thinking
        toggle is a Claude-Code-only label; no Max Mode
        dial.
      • Codex (single Platform covering both the CLI binary
        and the Cursor IDE extension — operator picks the
        surface): Model / Platform / Intelligence /
        Conversation. Intelligence values are Low / Medium
        / High / Extra High. The Codex panel exposes NO
        Max Mode and NO Thinking field — Intelligence is
        the only reasoning dial.
      • Cursor / ChatGPT / API: Model / Platform / Max
        Mode / Thinking (Off/Low/Medium/High/XHigh/N/A) /
        Conversation. Max Mode is a Cursor-surface dial
        (exposed in both of Cursor's UI modes — Composer
        and Chat); on ChatGPT / API surfaces it documents
        intent ("ON" when the rationale calls for extended
        cross-file reasoning) even though the literal
        toggle is absent.
    Every Settings table MUST include Platform (the access
    method picked by `<access-selection>` in
    docs/model-selector.txt against docs/user-context.md);
    the rationale paragraph MUST name the subscription or
    API key that pays for the chosen Platform AND justify
    each dial value using the surface's native vocabulary
    (Effort vs Intelligence vs Max Mode; On/Off vs
    Low/Medium/High/Extra High/Max vs reasoning level).
  - End the document with a Post-Implementation Verification
    section (V1-Vn check tables), a Summary Table, optional
    Model-selection blocks, and a Not-in-scope section.
  - Prefer concrete, declarative sentences. No hedging.
  - Mark every unknown as "TBD".
  - Output the finished document in raw Markdown only.
  - Strip every <!-- ... --> instruction block before
    delivery, EXCEPT the inline guidance comments inside
    each section header that help the next author fill it
    in. (Those are explicitly marked "KEEP" below.)
=============================================================
-->

# Phase {{N}} Roadmap — {{Phase Title}}

## Overview

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

The Overview is 3-6 paragraphs of declarative prose that
answers:
  1. What gate does this phase open? (What comes next is
     blocked on this phase shipping.)
  2. What does this phase NOT do? (Two or three negatives,
     to set expectations.)
  3. The phase "lands in N layers" enumeration — one
     paragraph that names every step in order with the
     concrete deliverable each one ships.
  4. The "ship test" paragraph — one paragraph that
     summarizes the testable conditions for phase exit.
  5. Pre-requisite paragraph — which prior phases must be
     closed, with one-sentence rationale per dependency.
  6. Dependency paragraph — which downstream phases consume
     this phase's deliverables, with one-sentence rationale.
  7. Optional "Design rationale" paragraph if this phase
     embodies a non-obvious design choice that reviewers
     will question.
-->

{{Opening paragraph: 2-4 sentences framing what gate this
phase opens, what it explicitly does NOT do, and why the
work is bundled into one phase rather than spread across
several. Reference the prior phase(s) by number where
useful.}}

The phase lands in {{N}} layers:

1. **{{Step 1 short label}}** — {{multi-sentence
   description of the concrete deliverable Step 1 ships.
   Name files, callables, schema fields, UX surfaces.}}
2. **{{Step 2 short label}}** — {{description}}.
3. **{{Step 3 short label}}** — {{description}}.
4. **{{Step N-1 short label}}** — {{description}}.
5. **QA + `verify-phase{{N}}.sh`** — verification script
   (`--fast`, `--swift`, `--node`, `--ui`, `--all`,
   `--post`), `docs/phase{{N}}-qa-findings.md` rollup, and
   `phase-verify.yml` matrix entry that binds the phase to
   CI.

The ship test for Phase {{N}} is straightforward:
{{one long sentence that lists every testable exit
condition, separated by semicolons — e.g. "deliverable X
ships; Jest test Y passes; doc Z carries the verbatim
spec text; and `scripts/verify-phase{{N}}.sh --fast`
exits 0 on Ubuntu CI with the `phase-verify.yml` matrix
entry green"}}.

**Pre-requisite:** {{Phase X closed (one-sentence
rationale). Phase Y closed (one-sentence rationale). Phase
Z closed (one-sentence rationale).}}

**Dependency:** {{Phase N+1 does not start until Phase N's
V-checks are green; one-sentence rationale for what
downstream consumers inherit.}}

**Design rationale ({{short label}}).** {{Optional. Include
only if this phase embodies a non-obvious design choice —
a build-vs-buy call, a synthetic-vs-real trade-off, an
ephemeral-vs-persistent pattern, etc. One or two
paragraphs. Drop the whole subsection if the design is
self-evident from the Overview.}}

**Branch strategy.** Every step in this phase lands on its own
short-lived feature branch
(`feature/phase{{N}}-step{{M}}-<slug>`), opens a pull request
against `main`, waits for the project's CI workflow to go green,
and squash-merges with a Conventional Commits subject line.
Direct pushes to `main` are blocked by branch protection. See
the parent project's ROADMAP "Branch management strategy"
section for the canonical naming convention, PR rules, and
release tagging — this paragraph confirms those rules apply
unchanged within this phase. Per-step branches are listed on
each step header below as `**Branch:**` so reviewers can map
commits 1:1 to the step they implement.

**Branch-first execution rule.** The very first action of every
step — before reading any files, before running any tool, before
drafting any change — is to check out the branch named in that
step's `**Branch:**` line:

```sh
git checkout -b feature/phase{{N}}-step{{M}}-<slug>
```

This is non-negotiable. `main` is protected with
`enforce_admins: true`, so a commit on `main` cannot be pushed and
must be rewound or rebased onto the feature branch before the PR
can open — an avoidable round-trip. If you discover mid-step that
you started on `main`, recover by running the same
`git checkout -b` command immediately (uncommitted changes carry
over to the new branch), then continue. AI coding agents executing
a step from this roadmap must treat the branch checkout as Step 0
of every step.

**Security-first execution rule.** Security is not a phase — it is
a gate on every commit of every step. Before each `git commit`,
the step's work must pass the local, fail-closed security gate:
secret/PII scan clean, SAST clean, dependency audit clean, and a
diff review confirming no sensitive data (PII, credentials,
tokens) and no new insecure pattern (injection, weak crypto,
over-broad scope, secret in a client bundle or log line). This
gate is wired into the pre-commit hook and re-run in CI, so a
security issue introduced while implementing a step is caught
during development — before it reaches the branch, the PR, or
`main`. See the parent project's ROADMAP "Security & privacy
strategy" → "Per-step security gate" for the canonical checks and
tooling; each step's XML `<task>` carries a `<security>` block
restating them for the agent, and each step's Acceptance Criteria
ends with a security check. AI coding agents executing a step MUST
treat the security gate as part of the step's definition of done,
exactly like its tests. This matters most on projects handling
client PII or secrets: the operator running a step's prompt must
not be able to introduce a data-exposure risk that only surfaces
after merge.

**Step lifecycle.** Every step in this phase follows the exact
same six-stage lifecycle, in order, with no exceptions. Each
stage is a hard checkpoint — if a stage is skipped, branch
protection or the next step's Stage 1 will fail loudly, and that
is the safety net. AI coding agents MUST execute all six stages
before declaring a step complete.

1. **Create the branch.** Before any Read / Edit / Bash, run
   `git checkout -b feature/phase{{N}}-step{{M}}-<slug>` from a
   clean, up-to-date `main`. The exact branch name comes from
   this step's `**Branch:**` line.

2. **Work on the branch, passing the security gate before every
   commit.** All commits land here. Never push to `main` directly
   — branch protection (`enforce_admins: true`) rejects it. Before
   each `git commit`, run the local security gate (secret/PII
   scan, SAST, dependency audit, sensitive-data diff review — see
   the step's `<security>` block and the parent ROADMAP "Per-step
   security gate"). It is fail-closed: a finding blocks the commit,
   so a security issue in this step's work is caught here, before
   the PR and before `main`.

3. **Open the PR.** `gh pr create --base main --head <branch>`
   with a Conventional Commits title and a body that references
   this roadmap step and its acceptance criteria. One PR per
   step; never bundle two steps into one PR.

4. **Wait for green checks, then squash-merge.** Every required
   status check (lint, type-check, test-matrix, package-smoke,
   security-scan, the aggregate `test` gate, and the
   `phase-verify.yml` matrix entry for this phase) must report
   success. If the PR goes BEHIND main while waiting, refresh
   with `gh pr update-branch --rebase` — never merge `main` into
   the branch; `required_linear_history: true` enforces rebase.
   Once every check is green:

   ```sh
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

5. **Retire the branch (remote + local).** The
   `--delete-branch` flag plus the repo's
   `delete_branch_on_merge: true` setting retire the remote
   automatically. Sync local state and prune the merged branch
   plus any other `[gone]` labels left over from prior PRs:

   ```sh
   git switch main
   git pull --ff-only origin main
   git fetch --prune origin
   git branch -vv | grep ': gone]' | awk '{print $1}' \
     | xargs -r git branch -D
   ```

   Confirm with `git branch -vv` that only `main` and any
   intentional long-lived branches remain locally.

6. **New conversation, next step.** Phase-boundary hygiene:
   close this Claude Code / Cursor / Codex session and open a
   fresh one before starting Step {{M+1}}. The new conversation
   begins again at Stage 1 of this lifecycle, with the next
   step's `**Branch:**` line driving the `git checkout -b`
   command. No work straddles two steps.

---

## Current State (as of Phase {{N-1}})

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

Break the Current State into named "surfaces" — one
sub-section per area of the codebase / product the phase
will touch. Typical surface names:
  - Server / Cloud Functions surface
  - iOS app surface
  - Schema / data model surface
  - Observability surface
  - Payment / entitlement surface
  - Security & sensitive-data surface
  - Verification surfaces

Include a "Security & sensitive-data surface" whenever the
phase touches auth, secrets, PII, payments, or any external
input. It states what sensitive data the phase's steps will
handle, what the current controls are (secret manager, authz
checks, input validation, the pre-commit security gate + CI
security checks), and what pattern each step must mirror so it
does not regress them. This is what lets each step's
`<security>` block name a concrete, project-specific check
instead of a generic one.
  - Documentation surface

Each surface answers: what exists today, what is missing,
what file paths the next step will edit, what pattern the
next step should mirror.

The final surface is ALWAYS "Verification surfaces" — it
notes which prior verify-phaseNN.sh templates are the
closest precedent and which entries are already in the
.github/workflows/phase-verify.yml matrix.
-->

### {{Surface 1 — e.g. Matchmaking surface}}

- {{Multi-sentence bullet describing one concrete piece of
  current state. Name file paths. Reference the prior
  phase that established the pattern. State what is
  present today and what is missing. Each surface
  typically has 2-5 such bullets, NOT a "what exists /
  what is missing" two-bullet split.}}
- {{Multi-sentence bullet ...}}
- {{Multi-sentence bullet ...}}

### {{Surface 2 — e.g. iOS app surface}}

- {{Multi-sentence bullet ...}}
- {{Multi-sentence bullet ...}}

### {{Surface N}}

- {{Multi-sentence bullet ...}}

### Verification surfaces

- `scripts/verify-phase{A..N-1}.sh` exist;
  `verify-phase{{N-1}}.sh` is the most recent template
  (Phase {{N-1}} follows the canonical `--fast` / `--swift`
  / `--node` / `--ui` / `--all` / `--post` mode contract).
- `.github/workflows/phase-verify.yml` matrix includes
  {{list of prior phases}}. Phase {{N}} adds {{N}}.

---

## Execution Order

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

ASCII flow diagram showing the sequential dependency between
steps. Use box characters consistently. After the steps,
include a "post-implementation" section listing the
V-checks at a glance. Below the diagram, a short prose
paragraph explains WHY the steps are sequential (which
step depends on which prior step's output).
-->

```
Step 1  ({{short label}})                 {{one-line deliverable
                                          summary}}
                                          → implement
  ↓
Step 2  ({{short label}})                 {{one-line deliverable
                                          summary}}
                                          → implement
  ↓
Step 3  ({{short label}})                 {{one-line deliverable
                                          summary}}
                                          → implement
  ↓
...
  ↓
Step N  (QA + verify-phase{{N}}.sh)       scripts/verify-phase{{N}}.sh
                                          + docs/phase{{N}}-qa-findings.md
                                          + phase-verify.yml matrix entry
                                          → create

--- post-implementation ---

V1  {{one-line restatement of Step 1
    acceptance criteria.}}
V2  {{one-line restatement of Step 2
    acceptance criteria.}}
...
Vn  {{one-line restatement of Step N
    acceptance criteria.}}
```

Steps are sequential by dependency: one paragraph explaining
which step's output the next step consumes (e.g. "Step 2's
escalation ladder must exist before Step 3's bot spawn
callable can target the bot-fill leaf; Step 4 is ordered
after Step 3 to keep the schema migrations clean; Step N is
sequential after every prior step.").

---

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

SUB-PHASE LABEL CONVENTION
When a phase has multiple distinct work streams (e.g.
"the matchmaking ladder + the bot spawn + the async cap"
all in one phase), label each work stream with a letter:
30A, 30B, 30C, 31A, 31B, etc. Step titles then carry both
the sub-phase label and the descriptive title:

  ## Step 1 — 30A Product Decision Document
  ## Step 2 — 30A Matchmaker Escalation Ladder
  ## Step 3 — 30A Ephemeral Bot Spawn + Teardown
  ## Step 4 — 30C Async Game Concurrency Cap
  ## Step 5 — 30B Trial Harness + Observability
  ...

For single-work-stream phases, the sub-phase label is
optional — `## Step 1 — Database Schema Migration` is
fine. Use sub-phase labels when they help reviewers see
which steps share an owner / surface / acceptance gate.

TERMINAL VERBS
Every step in the Execution Order diagram ends its
right-column deliverable summary with one of three
arrows:
  → implement  AI-driven coding step.
  → operate    Operator wall-clock work (e.g. running a
               7-day trial, doing cross-browser QA).
  → create     QA scaffolding step (the verify script,
               findings doc, CI matrix update).
-->

## Step 1 — {{Step Title}}

> **Goal:** {{One dense paragraph (4-8 sentences) describing
> the concrete deliverable of this step. Reference every
> file path that gets added or edited (use backticks).
> Reference any verification hook (Jest test, XCTest, doc
> test) the step ships alongside. Often frames as: "Land
> the X chassis: a new Y callable that does Z; the iOS-
> side W view that consumes Y; the verification Jest /
> XCTest covering both. This step lands the foundation;
> Steps N-M layer A / B / C on top of the chassis Step 1
> builds." Use semicolons to chain deliverables in one long
> sentence rather than splitting into multiple short
> sentences.}}

**Branch:** `feature/phase{{N}}-step1-{{slug}}`

<!-- Typical model values: GPT-5.3 Codex (long-running
     autonomous agentic sessions), GPT-5.4 (knowledge
     work / writing / domain expertise), Sonnet 4.6
     (correctness-sensitive cross-cutting implementation),
     Composer 2 (multi-file mechanical editing, roadmap
     execution), Gemini 3.1 Pro (multimodal visual
     analysis). Settings table values match the model-
     selector's roadmap-annotation format.

     PLATFORM is the access method picked by
     `<access-selection>` in docs/model-selector.txt against
     the user-specific state in docs/user-context.md.
     Typical values: Claude Code (Claude models when
     claude.ai Max is active), Cursor (single Platform
     covering Cursor's Composer mode for routine multi-file
     editing AND Chat mode for frontier-model picks against
     the Cursor pool; operator picks the mode at task time
     based on the chosen Model), Codex (GPT/Codex models on
     a ChatGPT subscription; single Platform covering both
     the CLI binary and the Cursor IDE extension — operator
     picks the surface), Anthropic API / OpenAI API /
     Google API (pay-per-token fallback when no subscription
     path applies). The
     Settings table MUST name PLATFORM so reviewers can see
     which subscription pays for the step — a step's
     "Sonnet 4.6 via Claude Code" reads very differently
     from "Sonnet 4.6 via Anthropic API" on the cost line.

     SETTINGS TABLE SHAPE IS PLATFORM-SPECIFIC. Each
     surface exposes a different tuning UI, and the table
     MUST mirror what the operator will actually see in
     that surface so reviewers can audit the choice
     1:1 against the panel. Three variants exist:

     CLAUDE CODE variant (use when PLATFORM is "Claude
     Code"). The Settings panel exposes Model, Effort, and
     a Thinking on/off toggle — there is NO Max Mode dial
     and NO Intelligence dial on this surface. Table rows:
     Model / Platform / Effort / Thinking / Conversation.
     EFFORT values: Low / Medium / High / Extra High / Max.
     Map from overall complexity per `<thinking-context>`:
     Low → Low, Medium → Medium, High → High, High with
     novel problem-solving or cross-file multi-step proof
     → Extra High, ceiling-class tasks demanding the
     highest available reasoning budget → Max; bump up
     one level for planning / knowledge prompts with
     cross-cutting scope. THINKING values: On / Off.
     Default On for any step where extended reasoning is
     desirable; Off only when the step is purely
     mechanical and latency matters.

     CODEX variant (use when PLATFORM is "Codex" — covers
     both the CLI binary and the Cursor IDE extension as a
     single Platform; operator picks the surface at task
     time). The Codex panel exposes Model + Intelligence +
     Speed — there is NO Max Mode dial and NO Thinking
     field on this surface, so the table omits both. Table
     rows: Model / Platform / Intelligence / Conversation.
     INTELLIGENCE values: Low / Medium / High / Extra High.
     Map from overall complexity per `<thinking-context>`:
     Low → Low, Medium → Medium, High → High, S-tier coding
     / cross-file multi-step proof → Extra High.

     CURSOR / CHATGPT / API variant (use for every other
     PLATFORM — Cursor (single Platform covering both
     Composer mode and Chat mode), ChatGPT app, claude.ai
     web, Anthropic API, OpenAI API, Google API, etc.).
     Table rows: Model / Platform / Max Mode / Thinking /
     Conversation. MAX MODE values: ON / OFF (Cursor-
     surface dial; on non-Cursor surfaces resolve to ON
     when the rationale calls for extended cross-file
     reasoning, OFF otherwise — the value still documents
     intent even when the literal toggle is absent).
     THINKING values: Off / Low / Medium / High / XHigh /
     N/A. N/A applies when the PLATFORM does not expose a
     reasoning-level dropdown (e.g. Cursor — neither its
     Composer mode nor its Chat mode surfaces the toggle).
     -->

Settings table — Claude Code variant ({{use this shape
when PLATFORM is "Claude Code"; the Claude Code Settings
panel exposes Effort + Thinking toggle, never Max Mode
and never Intelligence}}):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | {{Model name}}                 |
| Platform     | Claude Code                    |
| Effort       | {{Low/Medium/High/Extra High/Max}} |
| Thinking     | {{On or Off}}                  |
| Conversation | **{{New or Continue}}**        |

Settings table — Codex variant ({{use this shape when
PLATFORM is "Codex" — covers both the CLI binary and the
Cursor IDE extension as a single Platform; the Codex panel
exposes Intelligence as its only reasoning dial — there is
NO Max Mode and NO Thinking field, so the table omits both
rows}}):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | {{Model name}}                 |
| Platform     | Codex                          |
| Intelligence | {{Low/Medium/High/Extra High}} |
| Conversation | **{{New or Continue}}**        |

Settings table — Cursor / ChatGPT / API variant ({{use
this shape when PLATFORM is a Cursor surface (Composer,
Chat) or any non-Codex, non-Claude-Code surface
(ChatGPT app, claude.ai web, Anthropic API, OpenAI API,
Google API). Max Mode is a Cursor-native dial; on
non-Cursor surfaces the value still documents intent
even though the literal toggle is absent}}):

| Setting      | Value                       |
| ------------ | --------------------------- |
| Model        | {{Model name}}              |
| Platform     | {{Access method name}}      |
| Max Mode     | {{ON or OFF}}               |
| Thinking     | {{Off/Low/Medium/High/XHigh/N/A}} |
| Conversation | **{{New or Continue}}**     |

**Model rationale:** {{3-5 sentences explaining the choice.
Lead with the task characteristics (long-running agentic
session / multi-file editing / multimodal visual analysis /
correctness-sensitive reasoning / mechanical translation)
and map them to the model's documented strengths. Name the
PLATFORM and identify the subscription or API key that pays
for it (claude.ai Max funding Claude Code, Cursor Ultra pool
funding Cursor, ChatGPT Pro funding Codex,
Anthropic API direct as pay-per-token fallback, etc.) —
this is the line that distinguishes "Sonnet 4.6 on a flat
$100/mo Max plan" from "Sonnet 4.6 burning $15/M output
tokens." Note the tuning choices in the language of the
actual surface: for Claude Code, why EFFORT is at the
stated level and why THINKING is on or off; for Codex, why
INTELLIGENCE is at the stated level (the surface exposes
no other dial); for every other PLATFORM, why MAX MODE is
on or off and why THINKING is at the stated level (or N/A
because the surface does not expose the toggle). Close
with why the conversation is new or continued (almost
always "New per phase-boundary hygiene").}}

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5 are AS BINDING as any
    `<requirement>` below. Do not
    declare the step complete
    until Stage 5 finishes.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase{{N}}-step{{M}}-<slug>`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches.

    6. NEW CONVERSATION, NEXT
       STEP. Phase-boundary
       hygiene: close this session
       and open a fresh one before
       Step {{M+1}}.
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI:

    1. SECRET / PII SCAN. No
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (bandit / semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment.

    3. DEPENDENCY AUDIT. Any new
       or bumped dependency passes
       the audit (pip-audit / npm
       audit / osv-scanner); no
       known-vulnerable, yanked,
       or typo-squatted package.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue
    from reaching the branch, the
    PR, or `main`.
  </security>

  <context>
    {{Project name}}. Phase {{N}}.
    Step 1: {{step title}}.

    Current state (as of Phase
    {{N-1}}, post-Phase-{{N}} Step
    {{prior step if any}}):

    - Bullet describing relevant
      current state. Include file
      paths the agent will need.
    - Bullet ...
    - Bullet ...

    Files to read (every file
    before drafting):
    - {{repo-relative path}}
      ({{one-line reason this file
      matters}}).
    - {{repo-relative path}}
      ({{reason}}).
    - {{repo-relative path}}
      ({{reason}}).
  </context>

  <goal>
    2-6 sentences describing what
    the agent must ship. Be
    concrete: name the files, the
    function signatures, the
    schema fields, the UX
    surfaces. Reference acceptance
    criteria implicitly through
    precise language.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      First concrete requirement.
      Be specific about file
      paths, function names,
      contract shapes. Multi-line
      where needed.
    </requirement>

    <requirement>
      Second requirement.
    </requirement>

    <requirement>
      Add {{test file path}}:
      - test{{scenario 1}}.
      - test{{scenario 2}}.
      - test{{scenario 3}}.
    </requirement>

    <requirement>
      Filepath comment: every new
      Swift / TS / Bash / YAML /
      Markdown file gets the
      repo-relative path as the
      first line where the file
      type accepts comments
      (Swift: `// path`; TS:
      `// path`; Bash: `# path`;
      YAML: `# path`; Markdown:
      check sibling docs/
      conventions and match).
    </requirement>
  </requirements>
</task>
```

### Step 1 acceptance criteria

- Testable statement. Verifiable by an automated test, a
  UI inspection, a SQL query, a CI run, or a doc grep.
- Testable statement.
- Testable statement.
- Testable statement.
- `{{test file}}.swift` / `{{test file}}.test.ts` pass.
- **Security gate clean** (always the final criterion): the
  pre-commit security gate passed on this step's diff — secret/
  PII scan clean, SAST clean, dependency audit clean, and the
  {{surface this step touches}} handles sensitive data per the
  project ROADMAP "Security & privacy strategy" ({{name the
  concrete check — e.g. "no PII in the new log lines", "the new
  endpoint enforces authz", "the added dependency passes
  pip-audit"}}).

---

## Step 2 — {{Step Title}}

> **Goal:** One paragraph.

**Branch:** `feature/phase{{N}}-step2-{{slug}}`

{{Settings table — pick the variant that matches PLATFORM
per the Step 1 guidance. Claude Code variant uses Model /
Platform / Effort / Thinking / Conversation. Codex variant
uses Model / Platform / Intelligence / Conversation
(no Max Mode, no Thinking row). Cursor / ChatGPT / API
variant uses Model / Platform / Max Mode / Thinking /
Conversation.}}

| Setting      | Value                       |
| ------------ | --------------------------- |
| Model        | {{Model name}}              |
| Platform     | {{Access method name}}      |
| Max Mode     | {{ON or OFF}}               |
| Thinking     | {{Off/Low/Medium/High/XHigh/N/A}} |
| Conversation | **{{New or Continue}}**     |

**Model rationale:** 3-5 sentences. Name the PLATFORM and
the subscription or API key that pays for it. For Claude
Code, state why EFFORT is at the stated level and why
THINKING is on or off. For Codex, state why INTELLIGENCE
is at the stated level (the surface exposes no other
reasoning dial). For every other PLATFORM, state why
MAX MODE is on or off and why THINKING is at the stated
level (or N/A because the surface does not expose the
toggle).

{{Every step's `<task>` opens with the SAME `<lifecycle>` and
`<security>` blocks shown in full in Step 1 — copy both
verbatim (updating the branch slug). They are omitted here only
to keep the template short; a finished roadmap MUST include
both in every step so the agent gates security on every
commit.}}

```xml
<task>
  <lifecycle>
    {{Six-stage lifecycle — copy
    verbatim from Step 1.}}
  </lifecycle>

  <security>
    {{Security gate — copy
    verbatim from Step 1. Add any
    check specific to what THIS
    step touches, e.g. "the new
    endpoint enforces authz" or
    "no PII in the new events".}}
  </security>

  <context>
    Always restate the project,
    the phase, the step, and the
    current state — every step is
    a fresh conversation so the
    agent has no prior context.

    Files to read:
    - ...
  </context>

  <goal>
    ...
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      ...
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 2 acceptance criteria

- ...
- ...
- **Security gate clean** (always the final criterion): the
  pre-commit security gate passed on this step's diff, with the
  concrete check for the surface this step touches named
  explicitly.

---

<!--
Repeat the Step pattern for Step 3, Step 4, ... as many as
the phase requires. Typical phase has 4-7 steps. The final
step is ALWAYS "QA + verify-phaseN.sh".

EVERY step, without exception, carries: the <lifecycle> and
<security> blocks in its <task> (both copied from Step 1), and
a final "Security gate clean" acceptance-criterion bullet. This
is how "security at every step" is enforced mechanically rather
than left to memory.
-->

## Step {{N}} — QA & Verification Script

> **Goal:** Package the verification matrix into
> `scripts/verify-phase{{N}}.sh` (with `--fast`, `--swift`,
> `--node`, `--ui`, `--all`, and `--post` modes), produce
> `docs/phase{{N}}-qa-findings.md`, and add `{{N}}` to the
> `phase-verify.yml` matrix. The script greps for every
> Step 1 through Step {{N-1}} deliverable and runs the
> Phase {{N}} XCTest + Jest suites in the appropriate
> modes; the `--post` mode invokes any phase-specific post
> checks (Lighthouse CI, regression sweep, day-completeness
> validator, readiness report consolidator, etc.).

**Branch:** `feature/phase{{N}}-step{{N}}-verify`

{{Settings table — pick the variant that matches PLATFORM
per the Step 1 guidance. The Claude Code variant uses
Effort + Thinking-toggle, the Codex variant uses
Intelligence (no Max Mode, no Thinking row), and the
Cursor / ChatGPT / API variant uses Max Mode +
Thinking-levels.}}

| Setting      | Value                       |
| ------------ | --------------------------- |
| Model        | {{Model}}                   |
| Platform     | {{Access method name}}      |
| Max Mode     | ON                          |
| Thinking     | {{Off/Low/Medium/High/XHigh/N/A}} |
| Conversation | **New**                     |

**Model rationale:** Why this model fits the mechanical
translation of the prior verify-script template into this
phase's deliverables. Name the PLATFORM and the subscription
or API key that pays for it. For Claude Code, state why
EFFORT is at the stated level and why THINKING is on or off.
For Codex, state why INTELLIGENCE is at the stated level
(the surface exposes no other reasoning dial). For every
other PLATFORM, state why MAX MODE is on or off and why
THINKING is at the stated level (or N/A because the surface
does not expose the toggle).

```xml
<task>
  <lifecycle>
    {{Six-stage lifecycle — copy
    verbatim from Step 1.}}
  </lifecycle>

  <security>
    {{Security gate — copy
    verbatim from Step 1. This
    step also AUTHORS the
    --security verify mode, so its
    own diff must still pass the
    gate before commit.}}
  </security>

  <context>
    {{Project}}. Phase {{N}}.
    Step {{N}}: QA + verification
    script.

    Steps 1 through {{N-1}} have
    been implemented. Now create
    the verification script, QA
    findings doc, and CI matrix
    update.

    Reference scripts (pattern
    templates):
    - scripts/verify-phase{{N-1}}.sh
      (closest structural
      precedent).
    - scripts/verify-phase{{N-2}}.sh
      (secondary pattern
      reference).

    Phase {{N}} deliverables to
    verify ({{K}} static checks
    across Steps 1 through {{N-1}}
    plus 4+ Step {{N}}
    self-checks):

    Step 1 ({{scope}}) — checks
    1-{{x}}:
    1.  Concrete static-check
        description.
    2.  ...

    Step 2 ({{scope}}) — checks
    {{x+1}}-{{y}}:
    {{x+1}}. ...

    Step {{N}} self-checks — checks
    {{last-3}}-{{last}}:
    {{last-3}}. scripts/verify-
        phase{{N}}.sh exists +
        executable.
    {{last-2}}. docs/phase{{N}}-qa-
        findings.md exists.
    {{last-1}}. docs/phase{{N}}-
        roadmap.md exists (this
        doc).
    {{last}}. .github/workflows/
        phase-verify.yml matrix
        includes `{{N}}`.

    Files to read:
    - scripts/verify-phase{{N-1}}.sh
      (primary structural
      template).
    - all Phase {{N}} implementation
      files from Steps 1 through
      {{N-1}}.
  </context>

  <goal>
    Create scripts/verify-phase{{N}}.sh
    with {{K}}+ static deliverable
    checks (Steps 1 through {{N-1}})
    plus 4+ Step {{N}} self-checks
    plus a post-implementation
    V1-V{{N}} matrix. Create
    docs/phase{{N}}-qa-findings.md.
    Add `{{N}}` to the
    phase-verify.yml matrix.
  </goal>

  <requirements>
    <requirement>
      Read scripts/verify-phase{{N-1}}.sh
      end-to-end for structure,
      flag parsing, output format,
      record_pass / record_fail
      conventions, and the final
      summary table. Mirror the
      format exactly so the Phase
      {{N}} script is visually
      continuous with the Phase
      {{N-1}} script in CI logs.
    </requirement>

    <requirement>
      scripts/verify-phase{{N}}.sh
      modes:
      - default (no flag): static
        checks + Phase {{N}} Swift
        XCTest suite (macOS +
        Xcode).
      - --fast: static checks
        only, CI-safe on Linux /
        Ubuntu. MUST NOT shell
        out to xcodebuild, any
        Simulator, or any
        macOS-only tool. Static
        checks are grep / test
        -f / test -x / git ls-
        files based.
      - --swift: same as default;
        runs the Phase {{N}}
        XCTest suite.
      - --node: static + `npm
        --prefix functions run
        lint` (must continue to
        pass with `--max-warnings
        0`) + `npm --prefix
        functions test --
        --testPathPattern phase{{N}}`
        for the Phase {{N}} Jest
        slice.
      - --ui: phase-specific UI
        smoke configuration.
      - --security: the security
        gate for this phase's
        surface — secret/PII scan,
        SAST, and dependency audit
        over the phase's files
        (the same checks the
        pre-commit hook and CI
        run). CI-safe on Ubuntu;
        exits non-zero on any
        finding.
      - --all: static + swift +
        node + ui + security.
      - --post: static + V1-V{{N}}
        + phase-specific post
        invocations (lighthouse,
        regression sweep, day-
        completeness validator,
        readiness consolidator,
        etc.) + (when `gh` CLI is
        logged in) `gh pr checks`
        against the current branch.

      Static checks: {{K}}+
      numbered checks. Each check
      must use grep / test -f /
      test -x / git ls-files only;
      print a clear PASS / FAIL
      line referencing the
      deliverable number; be
      independent.

      At least ONE static check
      must be security-oriented and
      confirm the security gate is
      wired, not bypassed: e.g. the
      pre-commit hook config exists
      and runs the secret/SAST/dep
      scans, the phase's security
      checks appear in CI
      (phase-verify.yml / a
      security workflow), and no
      obvious secret pattern is
      committed under the phase's
      paths (grep for private-key
      headers, `AKIA`, `-----BEGIN`,
      etc.). This is the CI-side
      backstop to the per-commit
      gate.
    </requirement>

    <requirement>
      Post-implementation V-checks
      section mirroring the Phase
      {{N-1}} structure (V1-V{{N}}):

      V1 — Step 1 scope
      - V1.1 Static checks
        {{range}} all PASS.
      - V1.2 {{Swift XCTest name}}
        passes (--swift).
      - V1.3 {{TS Jest name}}
        passes (--node).

      V2 — Step 2 scope
      - V2.1 ...
      - V2.2 ...
      - V2.3 ...

      ...

      V{{N}} — CI integration +
      security
      - V{{N}}.1 verify-phase{{N}}
        .sh --fast exits 0 on
        Ubuntu CI.
      - V{{N}}.2 phase-verify.yml
        matrix includes `{{N}}`.
      - V{{N}}.3 All static checks
        pass.
      - V{{N}}.4 verify-phase{{N}}
        .sh --security exits 0
        (secret/PII scan, SAST, and
        dependency audit clean over
        the phase's surface).
    </requirement>

    <requirement>
      Create the
      Phase{{N}}VerificationTests
      Swift test file (path
      mirrors the project's
      existing test layout) with:
      - testRoadmapDocExists.
      - testQaFindingsDocExists.
      - testVerifyScriptExistsAnd
        Executable.
      - testPhaseVerifyMatrix
        Includes{{N}}.
    </requirement>

    <requirement>
      Update .github/workflows/
      phase-verify.yml to include
      `{{N}}` in the matrix —
      append `{{N}}` to the
      existing `matrix.phase`
      list. Preserve every prior
      phase entry; this is an
      additive change.
    </requirement>

    <requirement>
      Create docs/phase{{N}}-qa-
      findings.md with rollup
      sections for every Step 1
      through Step {{N-1}}, a Step
      {{N}} verify-script rollup,
      and a "Pre-ship items"
      section noting documented
      limitations + downstream-
      phase follow-ups.
    </requirement>

    <requirement>
      Update docs/ROADMAP.md:
      - Verify the Phase {{N}}
        entry's "Acceptance
        criteria" section matches
        this roadmap's V1-V{{N}}
        checks (consistency
        audit).
      - Update the closing-
        paragraph status line
        after Phase {{N}} ships.
    </requirement>

    <requirement>
      Script must be executable
      (chmod +x), print clear
      pass / fail per check, exit
      0 on success, exit 1 on
      any failure. Mirror the
      exact output format, check-
      numbering convention, and
      summary table from
      verify-phase{{N-1}}.sh so
      CI log diffing across
      phases is frictionless.

      --fast must complete in
      under 30 seconds on Ubuntu
      CI.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step {{N}} acceptance criteria

- `scripts/verify-phase{{N}}.sh` exists, is executable, and
  passes on a clean tree post-implementation.
- Script has {{K}}+ deliverable checks plus V1-V{{N}}
  post-implementation checks ({{total}}+ total).
- `--fast` runs in under 30 seconds on Ubuntu CI.
- `--post` mode runs cleanly on macOS with all
  phase-specific post-invocations green.
- `docs/phase{{N}}-qa-findings.md` complete with every
  rollup section.
- `.github/workflows/phase-verify.yml` matrix includes
  `{{N}}`; the new check appears on every PR.
- `--security` mode exists and exits 0 (secret/PII scan,
  SAST, and dependency audit clean over the phase's surface);
  V{{N}}.4 is green.
- Branch protection still passes on the resulting PR.
- **Security gate clean** (always the final criterion): the
  pre-commit security gate passed on this step's diff and the
  security workflow is green.

---

## Post-Implementation Verification

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

Open the section with a paragraph explaining what runs
automatically in CI vs what is operator wall-clock work
(e.g. a 14-day soak, a 7-day trial, a cross-browser sweep
on Safari iOS that can't be GitHub-Actions-driven).

Follow with a top-level "Mode" table mapping each verify-
script mode to the workflow that runs it, the runner OS,
and the V-checks it covers.

Follow with a list of local invocation examples (one per
mode).

Then one V-section per step (V1 ... V{{N}}) with a table
listing every check id, what it verifies, and which
workflow runs it.
-->

Every V1-V{{N}} check below runs **automatically in CI** on
every push and pull request — no manual invocation
required, except where noted (list any operator wall-clock
exceptions here).

| Mode             | Workflow                                              | Runner | Coverage                                                                  |
| ---------------- | ----------------------------------------------------- | ------ | ------------------------------------------------------------------------- |
| `--fast`         | `phase-verify.yml` (matrix entry `{{N}}`)             | Ubuntu | Static checks 1-{{K}}, V1.1, V2.1, V3.1, ...                              |
| `--node`         | `phase{{N}}-post.yml` (or `phase-post.yml`)           | Ubuntu | V1.3, V2.3, ... (Phase {{N}} Jest slice + functions ESLint)               |
| `--swift`        | Xcode Cloud (`{{scheme}}` scheme)                     | macOS  | V1.2, V2.2, ... (XCTest)                                                  |
| `--ui`           | Xcode Cloud (`{{UI scheme}}` scheme)                  | macOS  | One-shot smoke / soak / etc.                                              |
| `--security`     | `phase-verify.yml` / security workflow                | Ubuntu | V{{N}}.4 (secret/PII scan + SAST + dependency audit)                      |
| `--post`         | {{workflow or local on macOS}}                        | {{OS}} | V{{n}}.{{m}} (phase-specific post check) + the full V-check sweep         |

Local invocations remain available for ad-hoc runs and
pre-release sweeps:

```bash
./scripts/verify-phase{{N}}.sh --post   # static + V1-V{{N}} + post checks
```

`--post` is the canonical command to run before tagging the
phase release.

Other modes:

```bash
./scripts/verify-phase{{N}}.sh              # static + V-checks + Swift unit tests
./scripts/verify-phase{{N}}.sh --fast       # static + V-checks only (Ubuntu CI)
./scripts/verify-phase{{N}}.sh --node       # static + functions Jest + lint
./scripts/verify-phase{{N}}.sh --swift      # static + Swift XCTest
./scripts/verify-phase{{N}}.sh --ui         # static + UI smoke
./scripts/verify-phase{{N}}.sh --security   # secret/PII scan + SAST + dep audit
./scripts/verify-phase{{N}}.sh --all        # static + Swift + Node + UI + security
```

The script reports each V-check by id (V1.1, V2.1, ...) so
a failure in any workflow above maps directly to the
corresponding row below.

### V1 — {{Step 1 scope}}

> **Automated in CI.** `phase-verify.yml` → V1.1; Xcode
> Cloud / `phase-post.yml` → V1.2 through V1.{{n}}.

| ID   | Check                                                              | Automation                                                                |
| ---- | ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| V1.1 | Static checks {{range}} all PASS ({{short summary}}).              | `phase-verify.yml` runs `verify-phase{{N}}.sh --fast` on every push/PR.   |
| V1.2 | {{XCTest name}} passes; {{what it verifies}}.                      | Xcode Cloud `{{scheme}}` scheme XCTest run (`--swift` locally).           |
| V1.3 | {{Jest name}} passes; {{what it verifies}}.                        | `phase{{N}}-post.yml` runs `verify-phase{{N}}.sh --node`.                 |

### V2 — {{Step 2 scope}}

> **Automated in CI.** `phase-verify.yml` → V2.1; Xcode
> Cloud → V2.2; `phase{{N}}-post.yml` → V2.3.

| ID   | Check                                                              | Automation                                                                |
| ---- | ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| V2.1 | Static checks {{range}} all PASS.                                  | `phase-verify.yml --fast`.                                                |
| V2.2 | {{XCTest name}} passes.                                            | Xcode Cloud (`--swift` locally).                                          |
| V2.3 | {{Jest name}} passes.                                              | `phase{{N}}-post.yml --node`.                                             |

<!-- Repeat V3, V4, ... V{{N-1}} for each step. Every V
     section opens with a one-line `> **Automated in CI.**`
     blockquote that maps the V-checks to the workflows
     that run them. -->

### V{{N}} — CI integration + security

> **Automated in CI.** `phase-verify.yml` → V{{N}}.1
> through V{{N}}.4 on every push/PR.

| ID         | Check                                                          | Automation                                                                |
| ---------- | -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| V{{N}}.1   | `verify-phase{{N}}.sh --fast` exits 0 on Ubuntu CI.            | `phase-verify.yml` matrix entry `{{N}}`.                                  |
| V{{N}}.2   | `phase-verify.yml` matrix includes `{{N}}`.                    | `phase-verify.yml --fast` static check.                                   |
| V{{N}}.3   | All static checks in `verify-phase{{N}}.sh` pass.              | `phase-verify.yml --fast` records pass only when `STATIC_DELIVERABLE_FAIL == 0`. |
| V{{N}}.4   | `verify-phase{{N}}.sh --security` exits 0 (secret/PII scan + SAST + dep audit clean). | `phase-verify.yml` / security workflow runs `--security` on every push/PR. |

---

## Summary Table

<!-- Summary Table column "Reasoning dial" carries
     whichever dial the step's PLATFORM exposes, written
     in the surface's native vocabulary so reviewers can
     audit each row 1:1 against the panel:
       • Claude Code → "Effort {{Low/Med/High/XHigh/Max}}"
         (and the Thinking column carries "On" or "Off").
       • Codex → "Intelligence {{Low/Med/High/XHigh}}"
         (the Thinking column is "--" because the surface
         exposes no Thinking field; Codex covers both the
         CLI binary and the Cursor IDE extension as a
         single Platform).
       • Cursor / ChatGPT / API → "Max ON" or "Max OFF"
         (and the Thinking column carries the level or
         N/A). -->

| Step    | Scope                     | Model       | Platform     | Reasoning dial  | Thinking         | Conv |
| ------- | ------------------------- | ----------- | ------------ | --------------- | ---------------- | ---- |
| 1       | {{Step 1 short scope}}    | {{Model}}   | {{Platform}} | {{Effort Low/Med/High/XHigh/Max or Intelligence Low/Med/High/XHigh or Max ON/OFF}} | {{level / On / Off / N/A / --}} | New  |
| 2       | {{Step 2 short scope}}    | {{Model}}   | {{Platform}} | {{Effort Low/Med/High/XHigh/Max or Intelligence Low/Med/High/XHigh or Max ON/OFF}} | {{level / On / Off / N/A / --}} | New  |
| ...     | ...                       | ...         | ...          | ...             | ...              | ...  |
| {{N}}   | QA + verify-phase{{N}}.sh | {{Model}}   | {{Platform}} | {{Effort Low/Med/High/XHigh/Max or Intelligence Low/Med/High/XHigh or Max ON/OFF}} | {{level / On / Off / N/A / --}} | New  |
| V1      | {{Step 1 scope}}          | CI: {{wf}}  | --           | --              | --               | --   |
| V2      | {{Step 2 scope}}          | CI: {{wf}}  | --           | --              | --               | --   |
| ...     | ...                       | ...         | --           | --              | --               | --   |
| V{{N}}  | CI integration            | CI: phase-verify.yml | --  | --              | --               | --   |

---

## Model selection blocks

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

Optional but recommended. The per-step Settings tables
above carry the canonical Model / Max Mode / Conversation
values; the rationale paragraphs map task characteristics
to model strengths. The text block below restates the same
selections in a roadmap-annotation output format for ease
of audit by a roadmodel script.

Include this section if your project has a roadmodel
audit tool that consumes the text format. Skip it if not.
-->

<!-- Block field shape is platform-specific, mirroring the
     per-step Settings tables. Three variants:
       • Claude Code → "EFFORT: {{Low/Medium/High/Extra
         High/Max}}" + "THINKING: {{On or Off}}".
       • Codex → "INTELLIGENCE: {{Low/Medium/High/Extra
         High}}" only; no MAX MODE line and no THINKING
         line, because the Codex panel exposes neither
         dial. Covers both the CLI binary and the Cursor
         IDE extension as a single Platform.
       • Cursor / ChatGPT / API → "MAX MODE: {{On or
         Off}}" + "THINKING: {{Off/Low/Medium/High/XHigh
         /N/A}}".
     The roadmodel audit tool keys on the PLATFORM line
     to decide which dial-name to expect. -->

```text
PROMPT: Step 1 — {{step title}}
MODEL: {{model}}
PLATFORM: {{access method name}}
{{For Claude Code:}}
EFFORT: {{Low/Medium/High/Extra High/Max}}
THINKING: {{On or Off}}
{{For Codex (single Platform; operator picks CLI binary or Cursor IDE extension at task time):}}
INTELLIGENCE: {{Low/Medium/High/Extra High}}
{{For Cursor / ChatGPT / API:}}
MAX MODE: {{On or Off}}
THINKING: {{Off/Low/Medium/High/XHigh/N/A}}
CONVERSATION: {{New or Continue}}
RATIONALE: {{One-paragraph restatement of the Step 1
Model-rationale paragraph, condensed for audit. Lead with
the task characteristic (e.g. "Long-running autonomous
coding session spanning X + Y + Z"), name the model's
strength that fits, name the subscription or API key that
pays for the PLATFORM, state why the surface's dial
(EFFORT, INTELLIGENCE, or MAX MODE + THINKING) is at the
chosen value (use the dial name of the actual surface),
and close with "New per phase-boundary hygiene." Keep to
3-5 sentences.}}

PROMPT: Step 2 — {{step title}}
MODEL: {{model}}
PLATFORM: {{access method name}}
{{Claude Code → EFFORT + THINKING(On/Off);
Codex → INTELLIGENCE only;
Cursor / ChatGPT / API → MAX MODE + THINKING(level/N/A)}}
CONVERSATION: {{New or Continue}}
RATIONALE: {{Same shape as Step 1 — task characteristic,
model strength, PLATFORM funding source, dial-value
justification in the surface's native vocabulary, hygiene
note.}}

PROMPT: Step 3 — {{step title}}
MODEL: {{model}}
PLATFORM: {{access method name}}
{{Claude Code → EFFORT + THINKING(On/Off);
Codex → INTELLIGENCE only;
Cursor / ChatGPT / API → MAX MODE + THINKING(level/N/A)}}
CONVERSATION: {{New or Continue}}
RATIONALE: {{...}}

PROMPT: Step {{N}} — QA + verify-phase{{N}}.sh
MODEL: {{model}}
PLATFORM: {{access method name}}
{{Claude Code → EFFORT + THINKING(On/Off);
Codex → INTELLIGENCE only;
Cursor / ChatGPT / API → MAX MODE + THINKING(level/N/A)}}
CONVERSATION: {{New or Continue}}
RATIONALE: {{Mechanical translation of the prior verify-
script template into this phase's deliverables; known
pattern, no novel reasoning — roadmodel's
"standard implementation, multi-file changes, and
roadmap execution" default. New per phase-boundary
hygiene.}}
```

---

## Not in scope (from product roadmap)

<!--
KEEP NONE OF THESE COMMENTS IN THE FINAL DOC.

Two sub-lists:
  1. Items the parent ROADMAP.md explicitly marks
     out-of-scope for this phase — quote / paraphrase from
     the parent roadmap.
  2. Additional items the AI / author has identified as
     out-of-scope during this roadmap's drafting (typical
     surfaces: cross-platform parity, formal load testing,
     marketing surfaces, post-launch iteration, separate
     follow-up phase territory).

Each item is one bullet, two sentences max. Lead with the
deferred thing, follow with where / when it lives instead.
-->

Per [`docs/ROADMAP.md`](ROADMAP.md) Phase {{N}} "Not in
scope":

- Item explicitly deferred by the parent roadmap, with a
  one-sentence pointer to where / when it lives instead.
- Item.
- Item.

Additionally not in scope for this phase:

- Item identified during drafting, with a pointer to the
  follow-up phase that owns it.
- Item.
- Item.

---

_This roadmap is the execution plan for Phase {{N}}. Update
step status as each is completed. After all steps and
verification pass, Phase {{N}} is complete and Phase
{{N+1}} ({{title}}) inherits {{one-sentence summary of the
deliverables the next phase consumes from this one}}._

<!--
=============================================================
POST-MERGE BACK-PATCH PATTERN (optional, append as needed)
=============================================================
When an issue is discovered AFTER a step has been merged
and the phase has moved on, do NOT rewrite the step
in-place. Append a back-patch subsection so the git
history of the decision is preserved.

Pattern: append a `#### Step N back-patch (YYYY-MM-DD) —
short title` subsection under the affected step (or, for
broader changes, a `## Post-merge addendum (YYYY-MM-DD) —
short title` section at the bottom of the file).

The back-patch records:
  - What was discovered post-merge.
  - What was actually shipped to fix it.
  - Cross-references to the audit / QA / backlog rows.
  - Any acceptance criteria that need re-running.
  - Whether the back-patch was later REVERTED — if so,
    keep the original text as a record but mark it
    "⚠️ REVERTED on YYYY-MM-DD by the next subsection"
    so future readers don't re-introduce the rejected
    direction.

Example skeleton:

  #### Step 3 back-patch (2026-MM-DD) — {{short title}}

  {{One paragraph describing what was discovered, what
  shipped to fix it, and where the canonical record of the
  decision lives. Reference the audit doc finding id, the
  QA findings rollup, and any tests that need re-running.}}

  Audit cross-reference: see
  [`docs/phase{{N}}-website-audit.md`](phase{{N}}-website-audit.md)
  finding `PHASE{{N}}-AUDIT-NNN`. QA cross-reference: see
  [`docs/phase{{N}}-qa-findings.md`](phase{{N}}-qa-findings.md)
  § "{{Back-patch rollup heading}}".
=============================================================
-->
