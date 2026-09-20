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


@dataclass
class Env:
    kind: str  # "venv" | "conda"
    label: str  # dir name or conda env name
    prefix: Path

    @property
    def python(self) -> Path:
        return self.prefix / ("Scripts/python.exe" if WINDOWS else "bin/python")


def _python_in(prefix: Path) -> bool:
    return (prefix / ("Scripts/python.exe" if WINDOWS else "bin/python")).exists()


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


def refresh_commands(dry_run: bool = False) -> list[str]:
    """Re-download docs/claude-commands/*.md into ~/.claude/commands and mirror
    any existing ~/.claude/skills/<name>/SKILL.md copies. Returns report lines."""
    report: list[str] = []
    commands_dir = CLAUDE_DIR / "commands"
    for name in COMMANDS:
        url = f"{REPO_RAW}/docs/claude-commands/{name}.md"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — fixed https URL
                body = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            report.append(f"{name}: FETCH FAILED ({exc})")
            continue
        target = commands_dir / f"{name}.md"
        state = "unchanged"
        if not target.exists() or target.read_text(encoding="utf-8") != body:
            state = "updated" if target.exists() else "installed"
            if not dry_run:
                commands_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
        skill = CLAUDE_DIR / "skills" / name / "SKILL.md"
        if skill.exists():
            # Same body, with the `name:` frontmatter line skills require.
            skill_body = body.replace("---\n", f"---\nname: {name}\n", 1)
            if skill.read_text(encoding="utf-8") != skill_body:
                state += " (+skill)"
                if not dry_run:
                    skill.write_text(skill_body, encoding="utf-8")
        report.append(f"{name}: {state}")
    return report


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
    ap.add_argument("--no-commands", action="store_true", help="do not refresh ~/.claude/commands")
    ap.add_argument("--dry-run", action="store_true", help="show the plan; change nothing")
    args = ap.parse_args(argv)

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
        print("\nClaude Code commands (~/.claude/commands):")
        for line in refresh_commands(dry_run=args.dry_run):
            print(f"  {line}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)} project(s) need attention:")
        for r in failed:
            print(f"  {r.entry.path}: {r.error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
