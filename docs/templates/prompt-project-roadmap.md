<!-- planning/prompts/project-roadmap.md -->
# Paste-prompt — write the project roadmap

Fill the `{{placeholders}}`, then paste everything below the rule
into a **new** chat in the project and submit. Defaults are shown
for every placeholder; delete a bracketed line if it does not
apply.

| Placeholder    | Meaning                                                  | Default                     |
| -------------- | -------------------------------------------------------- | --------------------------- |
| `{{BRIEF}}`    | Where the project is described: files, or inline prose   | `@README.md`                |
| `{{OUTPUT}}`   | Where the roadmap is written                             | `ROADMAP.md`                |
| `{{CONSTRAINTS}}` | Hard constraints the roadmap must respect (optional)  | —                           |

---

Write the project roadmap for this project.

Step 0 — refresh the planning kit so the templates and catalog are
current. Run `pip install -U roadmodel && roadmodel export-kit . --force`
(where roadmodel is not installed, run
`scripts/export-planning-kit.sh .` instead). Then open
`planning/templates/project-roadmap-template.md` and confirm its Step
lifecycle Stage 6 reads "Dispose of every finding, declare completion,
then new conversation". If it instead tells you to put findings in a
"Follow-ups (non-blocking)" note after the completion line, STOP and
tell me the kit is stale — do not write the roadmap from it.

Step 1 — write `{{OUTPUT}}` from
`@planning/templates/project-roadmap-template.md`. The project brief
is {{BRIEF}}. [Hard constraints: {{CONSTRAINTS}}.] Read the codebase
as needed to fill "Current State Assessment" from what actually
exists, not from the brief alone.

Keep every mandatory §5 section the template marks for a project with
this project's surfaces (security & privacy, release & deployment,
operations & observability, worktree strategy, defect handling), and
say explicitly which optional ones you omitted and why.

Where the roadmap names a model or platform for a phase, run the
model selector in `@planning/model-selector.txt` (prices from
`@planning/model-tier-cost-scale.md`, display rules from
`@planning/settings-display.md`) against `@planning/user-context.md`.
You are the engine — do not call any external API. Honor every
availability exclusion in the selector.

Honor the template's style rules: 80-column prose, no `<PLACEHOLDER>`
tokens left, every `<!-- ... -->` guidance block stripped, numbers
marked "TBD" rather than invented.

When the file is written, reply with its path and the phase list with
one line each. Do not start Phase 1 — each phase gets its own phase
roadmap in a separate conversation (see
`planning/prompts/phase-roadmap.md`).
