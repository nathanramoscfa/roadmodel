#!/usr/bin/env python3
# scripts/update_projects.py
"""Upgrade roadmodel in every registered project at once.

One machine, many projects, each with its own conda env or venv. This
script reads the project list, works out each project's environment,
upgrades ``roadmodel`` in all of them concurrently, refreshes each
project's ``planning/`` kit where one exists, and re-downloads the
user-scope Claude Code commands — one run, one table.

    python update_projects.py                       # every registered project
    python update_projects.py --add C:\\dev\\app1 ... # register, then run
    python update_projects.py --dry-run             # show the plan only

Registry: ``~/.config/roadmodel/projects.txt`` — one project per line,
``#`` comments, optional environment override after a pipe::

    E:\\Code\\Python\\bot-farm
    E:\\Code\\Python\\nexiform-ai | conda:nexiform
    E:\\Code\\Python\\paperlock   | venv:.venv

Without an override the environment is detected: a ``.venv`` / ``venv`` /
``env`` directory in the project; the ``name:`` in ``environment.yml``; a
conda env named like the project folder; or a conda env whose prefix is
inside the project. Nothing is guessed into ``base`` — an undetectable env
is reported, never updated.

Stdlib only (Python 3.9+), so it runs from any interpreter on the machine.
It is fetched fresh from the roadmodel repo by ``/roadmodel-update``, so it
never goes stale.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_RAW = "https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main"
COMMANDS = ("roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-update")
CONFIG_DIR = Path.home() / ".config" / "roadmodel"
DEFAULT_PROJECTS_FILE = CONFIG_DIR / "projects.txt"
CLAUDE_DIR = Path.home() / ".claude"
GEMINI_DIR = Path.home() / ".gemini"  # Gemini CLI: commands/<name>.toml -> /<name>
CODEX_DIR = Path.home() / ".codex"  # presence marks a Codex install
AGENTS_SKILLS_DIR = Path.home() / ".agents" / "skills"  # Codex skills: <name>/SKILL.md -> $<name>
CODEX_LEGACY_SKILLS_DIR = CODEX_DIR / "skills"  # pre-.agents location; current builds read BOTH
AGENTS = ("claude", "gemini", "codex")
VENV_DIRS = (".venv", "venv", "env")
WINDOWS = os.name == "nt"
PIP_TIMEOUT = 900
KIT_TIMEOUT = 180


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass
class Entry:
    path: Path
    override: Optional[str] = None  # "conda:<name>" | "venv:<dir>"

    @property
    def name(self) -> str:
        return self.path.name


def parse_registry_line(line: str) -> Optional[Entry]:
    """``path`` or ``path | conda:name`` / ``path | venv:dir``; ``#`` comments."""
    text = line.split("#", 1)[0].strip()
    if not text:
        return None
    path_part, _, override_part = text.partition("|")
    path = Path(path_part.strip()).expanduser()
    override = override_part.strip() or None
    if override and not re.fullmatch(r"(conda|venv):\S.*", override):
        raise ValueError(f"bad environment override {override!r} (use conda:<name> or venv:<dir>)")
    return Entry(path=path, override=override)


def read_registry(file: Path) -> list[Entry]:
    if not file.exists():
        return []
    entries: list[Entry] = []
    for n, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = parse_registry_line(line)
        except ValueError as exc:
            raise SystemExit(f"{file}:{n}: {exc}") from None
        if entry:
            entries.append(entry)
    return entries


def add_to_registry(file: Path, paths: list[str]) -> list[Path]:
    """Append absolute paths not already registered. Returns what was added."""
    file.parent.mkdir(parents=True, exist_ok=True)
    known = {e.path.resolve() for e in read_registry(file)}
    added: list[Path] = []
    with file.open("a", encoding="utf-8") as fh:
        for raw in paths:
            p = Path(raw).expanduser().resolve()
            if not p.is_dir():
                raise SystemExit(f"--add: not a directory: {raw}")
            if p in known:
                continue
            fh.write(f"{p}\n")
            known.add(p)
            added.append(p)
    return added


# --------------------------------------------------------------------------
# Environment detection
# --------------------------------------------------------------------------


def _python_path(prefix: Path) -> Optional[Path]:
    """The interpreter inside an env prefix, or None.

    Windows: venvs put it at ``Scripts\\python.exe``; conda envs at the prefix
    root (``python.exe``). POSIX: ``bin/python`` (``bin/python3`` on a few
    conda builds).
    """
    rels = ("Scripts/python.exe", "python.exe") if WINDOWS else ("bin/python", "bin/python3")
    for rel in rels:
        candidate = prefix / rel
        if candidate.exists():
            return candidate
    return None


@dataclass
class Env:
    kind: str  # "venv" | "conda"
    label: str  # dir name or conda env name
    prefix: Path

    @property
    def python(self) -> Path:
        found = _python_path(self.prefix)
        return found if found else self.prefix / ("python.exe" if WINDOWS else "bin/python")


def _python_in(prefix: Path) -> bool:
    return _python_path(prefix) is not None


def _conda_exe() -> Optional[str]:
    exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if exe:
        return exe
    home = Path.home()
    candidates = [
        home / "miniconda3" / ("Scripts/conda.exe" if WINDOWS else "bin/conda"),
        home / "anaconda3" / ("Scripts/conda.exe" if WINDOWS else "bin/conda"),
        home / "miniforge3" / ("Scripts/conda.exe" if WINDOWS else "bin/conda"),
    ]
    if sys.platform == "darwin":
        # Homebrew casks (Apple Silicon under /opt/homebrew, Intel under /usr/local)
        # and the pkg installers' /opt locations.
        for brew in ("/opt/homebrew/Caskroom", "/usr/local/Caskroom"):
            for cask in ("miniconda", "miniforge", "anaconda", "mambaforge"):
                candidates.append(Path(brew) / cask / "base" / "bin" / "conda")
        candidates += [
            Path("/opt/miniconda3/bin/conda"),
            Path("/opt/anaconda3/bin/conda"),
            Path("/opt/homebrew/anaconda3/bin/conda"),
        ]
    if WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        candidates += [
            local / "miniconda3" / "Scripts/conda.exe",
            local / "anaconda3" / "Scripts/conda.exe",
            Path("C:/ProgramData/miniconda3/Scripts/conda.exe"),
            Path("C:/ProgramData/anaconda3/Scripts/conda.exe"),
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


_CONDA_ENVS: Optional[dict[str, Path]] = None


def conda_envs() -> dict[str, Path]:
    """name -> prefix for every conda env on the machine ({} without conda)."""
    global _CONDA_ENVS
    if _CONDA_ENVS is not None:
        return _CONDA_ENVS
    envs: dict[str, Path] = {}
    exe = _conda_exe()
    if exe:
        try:
            out = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [exe, "env", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            ).stdout
            for prefix in json.loads(out).get("envs", []):
                p = Path(prefix)
                envs[p.name] = p
            # The root prefix is listed by its install-dir name; expose "base" too.
            root = json.loads(out).get("envs", [None])[0]
            if root:
                envs.setdefault("base", Path(root))
        except (subprocess.SubprocessError, OSError, ValueError):
            envs = {}
    _CONDA_ENVS = envs
    return envs


def _environment_yml_name(project: Path) -> Optional[str]:
    for fname in ("environment.yml", "environment.yaml"):
        f = project / fname
        if f.exists():
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^\s*name\s*:\s*['\"]?([^'\"#\s]+)", line)
                if m:
                    return m.group(1)
    return None


def resolve_env(entry: Entry) -> tuple[Optional[Env], str]:
    """Return (env, note). env is None when nothing trustworthy was found."""
    project = entry.path
    if not project.is_dir():
        return None, "project directory does not exist"

    if entry.override:
        kind, _, value = entry.override.partition(":")
        if kind == "venv":
            venv_prefix = (project / value) if not Path(value).is_absolute() else Path(value)
            if _python_in(venv_prefix):
                return Env("venv", value, venv_prefix), "override"
            return None, f"override venv:{value} has no python"
        conda_prefix = conda_envs().get(value)
        if conda_prefix and _python_in(conda_prefix):
            return Env("conda", value, conda_prefix), "override"
        return None, f"override conda:{value} not found (conda env list)"

    for d in VENV_DIRS:
        prefix = project / d
        if _python_in(prefix):
            return Env("venv", d, prefix), "found venv dir"

    yml = _environment_yml_name(project)
    if yml:
        yml_prefix = conda_envs().get(yml)
        if yml_prefix and _python_in(yml_prefix):
            return Env("conda", yml, yml_prefix), "environment.yml name"
        return None, f"environment.yml names conda env {yml!r} but it is not created"

    envs = conda_envs()
    named = envs.get(project.name)
    if named and _python_in(named):
        return Env("conda", project.name, named), "conda env named like the folder"

    for name, prefix in envs.items():
        try:
            prefix.resolve().relative_to(project.resolve())
        except ValueError:
            continue
        if _python_in(prefix):
            return Env("conda", name, prefix), "conda env inside the project"

    return None, "no env found (add `| conda:<name>` or `| venv:<dir>` to projects.txt)"


# --------------------------------------------------------------------------
# Work
# --------------------------------------------------------------------------


@dataclass
class Result:
    entry: Entry
    env: Optional[Env]
    note: str
    before: str = "-"
    after: str = "-"
    kit: str = "-"
    ok: bool = False
    error: str = ""
    log: list[str] = field(default_factory=list)


def _run(
    argv: list[str], timeout: int, cwd: Optional[Path] = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — argv built from detected interpreter paths, no shell
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONIOENCODING": "utf-8"},
    )


def installed_version(python: Path) -> str:
    try:
        cp = _run(
            [str(python), "-c", "import roadmodel, sys; sys.stdout.write(roadmodel.__version__)"],
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return "-"
    return cp.stdout.strip() if cp.returncode == 0 and cp.stdout.strip() else "-"


def _tail(text: str, n: int = 6) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def update_project(entry: Entry, *, kit: bool, init_kit: bool, dry_run: bool) -> Result:
    env, note = resolve_env(entry)
    res = Result(entry=entry, env=env, note=note)
    if env is None:
        res.error = note
        return res
    if dry_run:
        res.ok = True
        return res

    res.before = installed_version(env.python)
    try:
        cp = _run(
            [str(env.python), "-m", "pip", "install", "--upgrade", "--quiet", "roadmodel"],
            timeout=PIP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        res.error = f"pip install timed out after {PIP_TIMEOUT}s"
        return res
    except OSError as exc:
        res.error = f"could not run {env.python}: {exc}"
        return res
    if cp.returncode != 0:
        res.error = "pip install failed:\n" + _tail(cp.stderr or cp.stdout)
        return res
    res.after = installed_version(env.python)
    if res.after == "-":
        res.error = "pip reported success but `import roadmodel` fails in that env"
        return res

    planning = entry.path / "planning"
    if kit and (planning.is_dir() or init_kit):
        try:
            cp = _run(
                [str(env.python), "-m", "roadmodel", "export-kit", str(entry.path), "--force"],
                timeout=KIT_TIMEOUT,
                cwd=entry.path,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            res.kit = "FAILED"
            res.error = f"export-kit: {exc}"
            return res
        if cp.returncode != 0:
            res.kit = "FAILED"
            res.error = "export-kit failed:\n" + _tail(cp.stderr or cp.stdout)
            return res
        res.kit = "refreshed"
    elif kit:
        res.kit = "none"  # project has no planning/ — nothing to refresh
    else:
        res.kit = "skipped"

    res.ok = True
    return res


# --------------------------------------------------------------------------
# Claude Code commands (user scope, per machine)
# --------------------------------------------------------------------------


def _split_frontmatter(body: str) -> tuple[str, str]:
    """(description, markdown body) of a docs/claude-commands/*.md file."""
    description = ""
    text = body
    if body.startswith("---\n"):
        head, _, text = body[4:].partition("\n---\n")
        for line in head.splitlines():
            if line.startswith("description:"):
                description = line.partition(":")[2].strip()
    return description, text.lstrip("\n")


TOML_LITERAL_FENCE = "'" * 3


def port_gemini(name: str, body: str) -> str:
    """Gemini CLI custom command (TOML). ``$ARGUMENTS`` becomes ``{{args}}``;
    the prompt is a literal multi-line string so backslashes survive."""
    description, text = _split_frontmatter(body)
    text = text.replace("$ARGUMENTS", "{{args}}")
    for token in ("!{", "@{", TOML_LITERAL_FENCE):
        if token in text:  # shell/file injection syntax, or would end the literal string
            raise ValueError(f"{name}: prompt contains {token!r}, which Gemini CLI would interpret")
    desc = description.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'description = "{desc}"\n'
        f"prompt = {TOML_LITERAL_FENCE}\n{text.rstrip()}\n{TOML_LITERAL_FENCE}\n"
    )


def port_codex(name: str, body: str) -> str:
    """Codex skill (SKILL.md). Skills take no placeholders: the text after
    ``$name`` reaches the model as context, so say so where the Claude Code
    version reads ``$ARGUMENTS``."""
    description, text = _split_frontmatter(body)
    text = text.replace('"$ARGUMENTS"', "the text after the skill mention").replace(
        "$ARGUMENTS", "the text after the skill mention"
    )
    desc = description.replace('"', "'").replace("usage: /", "usage: $")  # skills are $-invoked
    return f'---\nname: {name}\ndescription: "{desc}"\n---\n{text.rstrip()}\n'


def _is_our_skill(text: str, name: str) -> bool:
    """True for a SKILL.md this updater generated (any version) for ``name``."""
    head = text[:400]
    return head.startswith(f"---\nname: {name}\n") and "(usage: $" in head


def _install(target: Path, content: str, dry_run: bool) -> str:
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return "unchanged"
    state = "updated" if target.exists() else "installed"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return state


def detect_agents() -> list[str]:
    """Agents present on this machine. Claude Code is assumed (this script
    ships with its commands); the others only if their config dir exists."""
    found = ["claude"]
    if GEMINI_DIR.is_dir():
        found.append("gemini")
    if CODEX_DIR.is_dir() or AGENTS_SKILLS_DIR.is_dir():
        found.append("codex")
    return found


def refresh_commands(dry_run: bool = False, agents: Optional[list[str]] = None) -> list[str]:
    """Re-download docs/claude-commands/*.md and install them for every agent
    on this machine: Claude Code as-is (mirroring any ~/.claude/skills copy),
    Gemini CLI as TOML custom commands, Codex as skills. Returns report lines."""
    agents = agents or detect_agents()
    report: list[str] = [f"agents: {', '.join(agents)}"]
    for name in COMMANDS:
        url = f"{REPO_RAW}/docs/claude-commands/{name}.md"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — fixed https URL
                body = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            report.append(f"{name}: FETCH FAILED ({exc})")
            continue
        states: list[str] = []
        if "claude" in agents:
            state = _install(CLAUDE_DIR / "commands" / f"{name}.md", body, dry_run)
            skill = CLAUDE_DIR / "skills" / name / "SKILL.md"
            if skill.exists():  # same body, with the `name:` line skills require
                mirrored = body.replace("---\n", f"---\nname: {name}\n", 1)
                if _install(skill, mirrored, dry_run) != "unchanged":
                    state += " (+skill)"
            states.append(f"claude {state}")
        if "gemini" in agents:
            try:
                toml = port_gemini(name, body)
            except ValueError as exc:
                states.append(f"gemini SKIPPED ({exc})")
            else:
                target = GEMINI_DIR / "commands" / f"{name}.toml"
                states.append(f"gemini {_install(target, toml, dry_run)}")
        if "codex" in agents:
            skill_md = port_codex(name, body)
            state = _install(AGENTS_SKILLS_DIR / name / "SKILL.md", skill_md, dry_run)
            # Current Codex reads ~/.codex/skills as well, so a copy there
            # lists every skill twice. Remove OUR copy only (content-checked);
            # a user-authored skill with the same name is left alone.
            legacy = CODEX_LEGACY_SKILLS_DIR / name / "SKILL.md"
            if legacy.exists() and _is_our_skill(legacy.read_text(encoding="utf-8"), name):
                state += " (legacy copy removed)"
                if not dry_run:
                    legacy.unlink()
                    with contextlib.suppress(OSError):
                        legacy.parent.rmdir()
            states.append(f"codex {state}")
        report.append(f"{name}: " + " · ".join(states))
    return report


# --------------------------------------------------------------------------
# Unattended runs: a per-machine schedule that runs this script daily
# --------------------------------------------------------------------------

SCHEDULE_LABEL = "com.roadmodel.update-projects"  # launchd label / cron marker
TASK_NAME = "roadmodel-update-projects"  # Windows Task Scheduler name
LOG_FILE = CONFIG_DIR / "update.log"
LOG_MAX_BYTES = 1_000_000


def _parse_time(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
        raise SystemExit(f"--install-schedule: time must be HH:MM (24h), got {value!r}")
    return int(m.group(1)), int(m.group(2))


def launchd_plist(python: Path, script: Path, hour: int, minute: int, log: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{SCHEDULE_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
    <string>--log</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
"""


def schtasks_create_argv(python: Path, script: Path, hour: int, minute: int) -> list[str]:
    # /TR takes one command string; inner quotes protect paths with spaces.
    return [
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/SC", "DAILY",
        "/ST", f"{hour:02d}:{minute:02d}",
        "/TR", f'"{python}" "{script}" --log',
    ]  # fmt: skip


def cron_line(python: Path, script: Path, hour: int, minute: int) -> str:
    return f"{minute} {hour} * * * {python} {script} --log  # {SCHEDULE_LABEL}"


def _sys(argv: list[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    """Run a fixed-argv system tool (launchctl / schtasks / crontab); never a shell."""
    return subprocess.run(  # noqa: S603 — argv is a literal list built here, not user input
        argv, input=stdin, capture_output=True, text=True
    )


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SCHEDULE_LABEL}.plist"


def _crontab_without_ours() -> list[str]:
    current = _sys(["crontab", "-l"])
    text = current.stdout if current.returncode == 0 else ""
    return [ln for ln in text.splitlines() if SCHEDULE_LABEL not in ln]


def install_schedule(when: str, dry_run: bool = False) -> str:
    """Register a daily run of this script for the current user. Returns a
    one-line description of what was (or would be) installed."""
    hour, minute = _parse_time(when)
    python = Path(sys.executable).resolve()
    script = Path(__file__).resolve()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"daily at {hour:02d}:{minute:02d} via {python} {script} (log: {LOG_FILE})"

    if sys.platform == "darwin":
        plist = _launchd_plist_path()
        if dry_run:
            return f"launchd agent {plist} — {stamp}"
        plist.parent.mkdir(parents=True, exist_ok=True)
        domain = f"gui/{os.getuid()}"
        _sys(["launchctl", "bootout", f"{domain}/{SCHEDULE_LABEL}"])  # ok if not loaded
        plist.write_text(launchd_plist(python, script, hour, minute, LOG_FILE), encoding="utf-8")
        cp = _sys(["launchctl", "bootstrap", domain, str(plist)])
        if cp.returncode != 0:
            raise SystemExit(
                f"launchctl bootstrap failed: {cp.stderr.strip() or cp.stdout.strip()}"
            )
        return f"launchd agent {plist} — {stamp}"

    if WINDOWS:
        argv = schtasks_create_argv(python, script, hour, minute)
        if dry_run:
            return f"Task Scheduler task {TASK_NAME} — {stamp}\n  {subprocess.list2cmdline(argv)}"
        cp = _sys(argv)
        if cp.returncode != 0:
            raise SystemExit(f"schtasks failed: {cp.stderr.strip() or cp.stdout.strip()}")
        return f"Task Scheduler task {TASK_NAME} — {stamp}"

    line = cron_line(python, script, hour, minute)
    if dry_run:
        return f"crontab entry — {stamp}\n  {line}"
    cp = _sys(["crontab", "-"], stdin="\n".join(_crontab_without_ours() + [line]) + "\n")
    if cp.returncode != 0:
        raise SystemExit(f"crontab failed: {cp.stderr.strip()}")
    return f"crontab entry — {stamp}"


def uninstall_schedule(dry_run: bool = False) -> str:
    if sys.platform == "darwin":
        plist = _launchd_plist_path()
        if not dry_run:
            _sys(["launchctl", "bootout", f"gui/{os.getuid()}/{SCHEDULE_LABEL}"])
            plist.unlink(missing_ok=True)
        return f"removed launchd agent {plist}"
    if WINDOWS:
        if not dry_run:
            _sys(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
        return f"removed Task Scheduler task {TASK_NAME}"
    if not dry_run:
        _sys(["crontab", "-"], stdin="\n".join(_crontab_without_ours()) + "\n")
    return "removed crontab entry"


class _Tee:
    """Write to the console and append to the log (scheduled runs)."""

    def __init__(self, *streams: object) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for s in self._streams:
            s.write(data)  # type: ignore[attr-defined]
        return len(data)

    def flush(self) -> None:
        for s in self._streams:
            s.flush()  # type: ignore[attr-defined]


def _open_log() -> object:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
        tail = LOG_FILE.read_bytes()[-LOG_MAX_BYTES // 5 :]
        LOG_FILE.write_bytes(tail)
    fh = LOG_FILE.open("a", encoding="utf-8")
    import datetime as _dt

    fh.write(f"\n===== {_dt.datetime.now().isoformat(timespec='seconds')} =====\n")
    return fh


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _table(results: list[Result]) -> str:
    rows = [("project", "env", "before", "after", "kit", "status")]
    for r in results:
        env = f"{r.env.kind}:{r.env.label}" if r.env else "?"
        status = "ok" if r.ok else "FAILED"
        rows.append((r.entry.name, env, r.before, r.after, r.kit, status))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for n, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], prog="update_projects.py")
    ap.add_argument(
        "projects", nargs="*", help="project dirs for this run only (default: the registry)"
    )
    ap.add_argument(
        "--projects-file",
        type=Path,
        default=DEFAULT_PROJECTS_FILE,
        help="registry (default: %(default)s)",
    )
    ap.add_argument("--add", nargs="+", metavar="DIR", help="register these project dirs, then run")
    ap.add_argument(
        "--jobs", type=int, default=6, help="concurrent projects (default: %(default)s)"
    )
    ap.add_argument("--no-kit", action="store_true", help="do not re-export planning/ kits")
    ap.add_argument(
        "--init-kit", action="store_true", help="export a planning/ kit even where none exists"
    )
    ap.add_argument(
        "--no-commands", action="store_true", help="do not refresh the agents' command files"
    )
    ap.add_argument(
        "--commands-only",
        action="store_true",
        help="refresh the agents' command files (Claude Code / Gemini CLI / Codex) and exit",
    )
    ap.add_argument(
        "--agents",
        metavar="LIST",
        help="comma-separated subset of claude,gemini,codex to install commands for (default: detect)",
    )
    ap.add_argument("--dry-run", action="store_true", help="show the plan; change nothing")
    ap.add_argument(
        "--install-schedule",
        nargs="?",
        const="09:00",
        metavar="HH:MM",
        help="also register a daily unattended run at HH:MM (default 09:00) for this user",
    )
    ap.add_argument("--uninstall-schedule", action="store_true", help="remove the daily run")
    ap.add_argument("--log", action="store_true", help=f"also append output to {LOG_FILE}")
    args = ap.parse_args(argv)

    if args.log:
        log_fh = _open_log()
        sys.stdout = _Tee(sys.__stdout__, log_fh)
        sys.stderr = _Tee(sys.__stderr__, log_fh)

    agents: Optional[list[str]] = None
    if args.agents:
        agents = [a.strip() for a in args.agents.split(",") if a.strip()]
        unknown = [a for a in agents if a not in AGENTS]
        if unknown:
            raise SystemExit(f"--agents: unknown {unknown}; choose from {', '.join(AGENTS)}")

    if args.commands_only:
        print("Agent command files:")
        for line in refresh_commands(dry_run=args.dry_run, agents=agents):
            print(f"  {line}")
        return 0

    if args.uninstall_schedule:
        print("Schedule:", uninstall_schedule(dry_run=args.dry_run))
        if not args.projects and not args.add:
            return 0

    if args.add:
        added = add_to_registry(args.projects_file, args.add)
        for p in added:
            print(f"registered {p}")

    entries = [Entry(Path(p).expanduser()) for p in args.projects] or read_registry(
        args.projects_file
    )
    if not entries:
        print(
            f"No projects registered. Add some:\n  python {Path(sys.argv[0]).name} --add <project dir> ...\n"
            f"or list them in {args.projects_file}",
            file=sys.stderr,
        )
        return 2

    verb = "Plan" if args.dry_run else "Updating"
    print(f"{verb}: {len(entries)} project(s), {args.jobs} at a time\n")
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {
            pool.submit(
                update_project, e, kit=not args.no_kit, init_kit=args.init_kit, dry_run=args.dry_run
            ): e
            for e in entries
        }
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if r.env is None:
                print(f"[{r.entry.name}] {r.note}")
            elif args.dry_run:
                print(f"[{r.entry.name}] {r.env.kind}:{r.env.label} ({r.note}) -> {r.env.python}")
            elif r.ok:
                print(f"[{r.entry.name}] {r.before} -> {r.after} | kit {r.kit}")
            else:
                print(f"[{r.entry.name}] FAILED: {r.error}")
    results.sort(key=lambda r: r.entry.name.lower())

    print("\n" + _table(results))

    if not args.no_commands:
        print("\nAgent command files:")
        for line in refresh_commands(dry_run=args.dry_run, agents=agents):
            print(f"  {line}")

    if args.install_schedule:
        print("\nSchedule:", install_schedule(args.install_schedule, dry_run=args.dry_run))

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)} project(s) need attention:")
        for r in failed:
            print(f"  {r.entry.path}: {r.error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
