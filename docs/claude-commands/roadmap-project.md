---
description: Write the project ROADMAP.md via the roadmodel planning kit (usage: /roadmap-project [brief files...])
effort: max
---
Write this project's roadmap using the roadmodel planning kit's
paste-prompt.

If `planning/prompts/project-roadmap.md` does not exist yet, first run
`pip install -U roadmodel && roadmodel export-kit . --force` (or
`scripts/export-planning-kit.sh .` where roadmodel is not installed).

Then read `planning/prompts/project-roadmap.md` and execute everything
below its horizontal rule exactly as written, with:
- `{{BRIEF}}` = "$ARGUMENTS" if given, else the prompt's default
- every other placeholder = the prompt's stated default
