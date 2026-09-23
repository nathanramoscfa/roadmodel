---
description: Upgrade roadmodel in every registered project at once — each project's own env, its planning/ kit, and these commands (usage: /roadmodel-update [project dirs to register…] [--install-schedule HH:MM])
---
Update roadmodel everywhere on this machine in one run: every registered
project's own conda env or venv, each project's `planning/` kit, and the
user-scope `/roadmap-*` commands. The operator should not have to open a
terminal — you run everything.

## 1. Fetch the updater fresh

Save it to `~/.config/roadmodel/update_projects.py` (Windows:
`%USERPROFILE%\.config\roadmodel\update_projects.py`), creating the
directory if needed. Fetching it every time is harmless: at run start it
upgrades roadmodel in a venv of its own (`~/.config/roadmodel/venv`),
replaces itself with the updater inside that release, and hands the run
over to it. Download it from:

`https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main/scripts/update_projects.py`

Use whatever fetches on this machine — `curl -fsSL … -o …`,
`curl.exe` in PowerShell, or `python -c "import urllib.request as u;
u.urlretrieve(URL, PATH)"`. Stdlib only, Python 3.9+; run it with the
machine's default `python` (or `py -3` on Windows).

## 2. Make sure the registry has projects

The registry is `~/.config/roadmodel/projects.txt` — one project dir per
line, `#` comments, optional env override: `<dir> | conda:<name>` or
`<dir> | venv:<subdir>`.

- Split "$ARGUMENTS": tokens starting with `--` (and their values, e.g.
  `--install-schedule 09:00`, `--jobs 8`, `--dry-run`) are passed to the
  script as-is; everything else is a project dir to register with
  `--add <dir> …`.
- If the registry is missing or empty and no dirs were given, ask the
  operator which projects to register. If they answer with names rather
  than paths, locate the folders yourself (search their usual code root —
  e.g. `E:\Code`, `~/code`, `~/dev` — two levels deep) and confirm the
  paths in one line before registering.

## 3. Run it

```
python ~/.config/roadmodel/update_projects.py [--add <dir> …] [--jobs N]
```

It detects each project's env (`.venv`/`venv`/`env` dir → `environment.yml`
name → conda env named like the folder → conda env inside the project),
upgrades `roadmodel` in all of them concurrently, re-exports `planning/`
where one exists (`--init-kit` to create one everywhere), and
re-downloads the five command files for every agent installed on this
machine: `~/.claude/commands` (mirroring any `~/.claude/skills/<name>/
SKILL.md` copies), `~/.gemini/commands/<name>.toml` for Gemini CLI, and
`~/.agents/skills/<name>/SKILL.md` for Codex and Cursor (both read that
directory; `$roadmap-step 1 3` in Codex, `/roadmap-step 1 3` in Cursor),
and `~/.config/opencode/commands/<name>.md` for OpenCode.
`--agents claude,gemini,codex,cursor,opencode` overrides the
auto-detection; `--commands-only` refreshes commands and nothing else.
`--dry-run` shows the plan.

## 4. Unattended runs (optional, once per machine)

`--install-schedule [HH:MM]` also registers a daily run for this user —
a launchd agent on macOS, a Task Scheduler task on Windows, a crontab
entry on Linux — that executes the same script with `--log`, appending
to `~/.config/roadmodel/update.log`. From then on every registered
project follows each roadmodel release within a day without anyone
running anything, and so does the updater itself: each run upgrades its
venv and runs the updater from that release, so nothing needs
re-fetching. On Windows a start missed while the PC was off runs once it
is back. `--uninstall-schedule` removes it.

## 5. Report

Show the result table verbatim. If the first line reads `*** self-update
FAILED`, show it with its reason: the run still happened, but on the
local copy of the updater. For any project marked FAILED:

- `no env found` → tell the operator the override syntax and offer to add
  it to the registry for them once they name the env.
- a pip error → show the last lines and the fix (usually network, or a
  Python too old for the current roadmodel — ≥ 3.11).

If any command file reports `updated` or `installed`, say that the editor
window needs a reload (`Developer: Reload Window`) before the new command
text is used. If a schedule was installed, show the "Schedule:" line and
where the log lives. The registry, the updater, and the schedule stay on
this machine; nothing here is committed to any project.
