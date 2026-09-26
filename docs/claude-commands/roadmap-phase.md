---
description: Write phase N roadmap via the roadmodel planning kit (usage: /roadmap-phase 6 [output-path])
effort: xhigh
---
Write the Phase $ARGUMENTS roadmap for this project using the roadmodel
planning kit's paste-prompt.

If `planning/prompts/phase-roadmap.md` does not exist yet, first run
`pip install -U roadmodel && roadmodel export-kit . --force` (or
`scripts/export-planning-kit.sh .` where roadmodel is not installed).

Then read `planning/prompts/phase-roadmap.md` and execute everything
below its horizontal rule exactly as written, with:
- `{{N}}` = the first token of "$ARGUMENTS"
- `{{OUTPUT}}` = the second token of "$ARGUMENTS" if given, else the
  prompt's default (`docs/roadmap/phaseNN-roadmap.md`, beside
  `docs/roadmap/ROADMAP.md`; `private/` only if this project keeps its
  roadmaps git-excluded there)
- every other placeholder = the prompt's stated default
