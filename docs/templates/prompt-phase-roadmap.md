<!-- planning/prompts/phase-roadmap.md -->
# Paste-prompt — write a phase roadmap

Fill the `{{placeholders}}`, then paste everything below the rule
into a **new** chat in the project and submit. Defaults are shown
for every placeholder; delete a bracketed line if it does not
apply.

| Placeholder          | Meaning                                   | Default                            |
| -------------------- | ----------------------------------------- | ---------------------------------- |
| `{{N}}`              | Phase number (two digits in filenames)    | —                                  |
| `{{PROJECT_ROADMAP}}` | The parent project roadmap                | `@ROADMAP.md`                      |
| `{{OUTPUT}}`         | Where the phase roadmap is written        | `docs/phase{{NN}}-roadmap.md`      |
| `{{PRIOR}}`          | Previous phase roadmap(s), for continuity | `@docs/phase{{NN-1}}-roadmap.md`   |

---

Write the Phase {{N}} roadmap for this project.

Step 0 — refresh the planning kit so the templates and catalog are
current. Run `pip install -U roadmodel && roadmodel export-kit . --force`
(where roadmodel is not installed, run
`scripts/export-planning-kit.sh .` instead). Then open
`planning/templates/phase-roadmap-template.md` and confirm its Stage 6
reads "DISPOSE OF EVERY FINDING, DECLARE COMPLETION, THEN NEW
CONVERSATION". If it instead tells you to put findings in a
"Follow-ups (non-blocking)" note after the completion line, STOP and
tell me the kit is stale — do not write the roadmap from it.

Step 1 — write `{{OUTPUT}}` from
`@planning/templates/phase-roadmap-template.md`, expanding the
Phase {{N}} section of `{{PROJECT_ROADMAP}}` into an executable plan.
Carry forward anything `{{PRIOR}}` hands to this phase (its closing
"inherits" line, its Not-in-scope items owned by this phase, and any
carry-over checklist).

For **each step's** Settings table and Model rationale, run the model
selector in `@planning/model-selector.txt` (prices from
`@planning/model-tier-cost-scale.md`, display rules from
`@planning/settings-display.md`) against `@planning/user-context.md`.
You are the engine — do not call any external API. Honor every
availability exclusion in the selector, and include a backup model per
step.

Honor the template's style rules: 80-column prose, zero `{{...}}`
tokens left, every `<task>` block carrying the full `<lifecycle>` and
`<security>` blocks verbatim, and a Post-Implementation Verification
section.

When the file is written, reply with its path and a one-paragraph
summary of the steps and their models. Do not start Step 1 of the
phase — that is a separate conversation.
