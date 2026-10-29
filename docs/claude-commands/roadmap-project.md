---
description: Write the project ROADMAP.md via the roadmodel planning kit (usage: /roadmap-project [brief files and/or a description])
effort: max
---
Write this project's roadmap using the roadmodel planning kit's
paste-prompt.

A roadmap is written from a **brief**: what the operator wants this
project to become. Settle the brief before anything else.

- **Given:** "$ARGUMENTS" is the brief when it is not empty. It may
  name files (a brief, notes, a spec, a README, in any format you can
  read: `.md`, `.txt`, `.pdf`, `.docx`, ...), describe the project in
  prose, or both. Read every file it names.
  For a `.docx`, extract its text first (`pandoc -t plain`, `textutil
  -convert txt -stdout` on macOS, or Python's `zipfile` reading
  `word/document.xml`). A file that does not exist or cannot be read
  is a question for the operator, not something to guess around.
- **Not given:** ASK, in one message, before writing anything:
  - what the project is for, and who uses it;
  - what "done" looks like: the outcomes the roadmap must reach;
  - hard constraints: stack, hosting, budget, deadlines, anything to
    avoid;
  - whether a document already describes it, and where. Mention
    `README.md` as an option only when it exists and says what the
    project is for. Never assume it is the brief.

  Then wait for the answer. The answer, and any files it names, is the
  brief.

If `planning/prompts/project-roadmap.md` does not exist yet, first run
`pip install -U roadmodel && roadmodel export-kit . --force` (or
`scripts/export-planning-kit.sh .` from a reviewed checkout to bootstrap a released wheel).

Then read `planning/prompts/project-roadmap.md` and execute everything
below its horizontal rule exactly as written, with:

- `{{BRIEF}}` = the brief settled above: the files it names and the
  operator's description
- `{{CONSTRAINTS}}` = the hard constraints the brief states, else the
  prompt's default
- every other placeholder = the prompt's stated default
