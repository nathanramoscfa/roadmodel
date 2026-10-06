# tests/test_update_projects.py
"""Guards on scripts/update_projects.py — the one-run "upgrade roadmodel in
every project" updater behind /roadmodel-upgrade.

The script is stdlib-only and fetched from the repo at run time, so these
tests import it from its path. Environment detection must never guess:
a project with no detectable env is reported, not updated into `base`.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "update_projects.py"
COMMAND = ROOT / "docs" / "claude-commands" / "roadmodel-upgrade.md"


@pytest.fixture(scope="module")
def up() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_projects", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["update_projects"] = mod  # dataclasses + postponed annotations need this
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _no_real_vscode(up: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent detection must not depend on whether the DEVELOPER has VS Code
    installed; tests that care about the vscode lane patch this themselves."""
    monkeypatch.setattr(up, "_vscode_user_dirs", lambda: [])


@pytest.fixture(autouse=True)
def _no_real_retirement(up: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """refresh_commands removes retired commands from the agents' dirs; a test
    that leaves one of those dirs pointing at the DEVELOPER's home must not
    delete their installed copies. The retirement test opts back in."""
    monkeypatch.setattr(up, "RETIRED_COMMANDS", ())


def _fake_venv(project: Path, name: str) -> Path:
    """A venv-shaped directory with a python launcher where the script looks."""
    prefix = project / name
    launcher = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    launcher.parent.mkdir(parents=True)
    launcher.write_text("")
    return prefix


# --------------------------------------------------------------------------
# Registry parsing
# --------------------------------------------------------------------------


def test_registry_line_forms(up: ModuleType) -> None:
    assert up.parse_registry_line("") is None
    assert up.parse_registry_line("   # just a comment") is None
    plain = up.parse_registry_line("/srv/app  # trailing comment")
    assert plain.path == Path("/srv/app") and plain.override is None
    conda = up.parse_registry_line("/srv/app | conda:app-env")
    assert conda.override == "conda:app-env"
    venv = up.parse_registry_line("C:\\dev\\app | venv:.venv")
    assert venv.override == "venv:.venv"
    with pytest.raises(ValueError):
        up.parse_registry_line("/srv/app | pipenv:whatever")


def test_add_to_registry_dedupes_and_requires_dirs(up: ModuleType, tmp_path: Path) -> None:
    reg = tmp_path / "cfg" / "projects.txt"
    a = tmp_path / "a"
    a.mkdir()
    assert up.add_to_registry(reg, [str(a)]) == [a.resolve()]
    assert up.add_to_registry(reg, [str(a)]) == []  # already registered
    assert [e.path for e in up.read_registry(reg)] == [a.resolve()]
    with pytest.raises(SystemExit):
        up.add_to_registry(reg, [str(tmp_path / "missing")])


# --------------------------------------------------------------------------
# Environment detection — never guess
# --------------------------------------------------------------------------


def test_detects_venv_dir(up: ModuleType, tmp_path: Path) -> None:
    prefix = _fake_venv(tmp_path, ".venv")
    env, note = up.resolve_env(up.Entry(tmp_path))
    assert env.kind == "venv" and env.prefix == prefix and "venv dir" in note


def test_venv_override_wins_and_must_exist(up: ModuleType, tmp_path: Path) -> None:
    _fake_venv(tmp_path, ".venv")
    other = _fake_venv(tmp_path, "tools-env")
    env, note = up.resolve_env(up.Entry(tmp_path, override="venv:tools-env"))
    assert env.prefix == other and note == "override"
    env, note = up.resolve_env(up.Entry(tmp_path, override="venv:nope"))
    assert env is None and "has no python" in note


def test_conda_by_environment_yml_and_folder_name(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envs_root = tmp_path / "conda-envs"
    named = _fake_venv(envs_root, "proj-env")
    folder_named = _fake_venv(envs_root, "myproj")
    monkeypatch.setattr(up, "_CONDA_ENVS", {"proj-env": named, "myproj": folder_named})

    project = tmp_path / "myproj"
    project.mkdir()
    env, note = up.resolve_env(up.Entry(project))
    assert env.kind == "conda" and env.label == "myproj" and "named like the folder" in note

    (project / "environment.yml").write_text("name: proj-env\ndependencies:\n  - python\n")
    env, note = up.resolve_env(up.Entry(project))
    assert env.label == "proj-env" and "environment.yml" in note

    (project / "environment.yml").write_text("name: not-created\n")
    env, note = up.resolve_env(up.Entry(project))
    assert env is None and "not created" in note


def test_no_env_is_reported_not_guessed(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _fake_venv(tmp_path / "conda", "base")
    monkeypatch.setattr(up, "_CONDA_ENVS", {"base": base})
    project = tmp_path / "bare"
    project.mkdir()
    env, note = up.resolve_env(up.Entry(project))
    assert env is None and "no env found" in note
    env, note = up.resolve_env(up.Entry(tmp_path / "does-not-exist"))
    assert env is None and "does not exist" in note


# --------------------------------------------------------------------------
# CLI — dry run end to end
# --------------------------------------------------------------------------


def test_dry_run_cli_plans_without_touching_anything(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _fake_venv(alpha, ".venv")
    delta = tmp_path / "delta"
    delta.mkdir()
    reg = tmp_path / "projects.txt"
    reg.write_text(f"{alpha}\n{delta}\n")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-file", str(reg), "--dry-run", "--no-commands"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "CONDA_EXE": str(tmp_path / "no-conda")},  # no conda lookups
    )
    assert result.returncode == 1, result.stdout + result.stderr  # delta has no env
    assert "[alpha] venv:.venv" in result.stdout
    assert "[delta] no env found" in result.stdout
    assert "alpha" in result.stdout and "FAILED" in result.stdout
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after  # dry run wrote nothing


def test_empty_registry_explains_how_to_add(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--projects-file",
            str(tmp_path / "none.txt"),
            "--no-commands",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "--add" in result.stderr


# --------------------------------------------------------------------------
# The command that drives it
# --------------------------------------------------------------------------


def test_roadmodel_update_command_points_at_the_script(up: ModuleType) -> None:
    text = COMMAND.read_text()
    assert f"{up.REPO_RAW}/scripts/update_projects.py" in text
    assert "projects.txt" in text
    assert "--add" in text and "--dry-run" in text
    assert "no env found" in text
    # The updater refreshes itself and its siblings; the tuple must name them all.
    for name in up.COMMANDS:
        assert (ROOT / "docs" / "claude-commands" / f"{name}.md").exists(), name


# --------------------------------------------------------------------------
# Windows conda layout — python.exe at the env root, not under Scripts\
# --------------------------------------------------------------------------


def test_windows_conda_env_root_python(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the first PC run marked every conda project FAILED because
    only Scripts\\python.exe (the venv layout) was probed."""
    monkeypatch.setattr(up, "WINDOWS", True)
    conda_prefix = tmp_path / "envs" / "proj"
    (conda_prefix / "python.exe").parent.mkdir(parents=True)
    (conda_prefix / "python.exe").write_text("")
    venv_prefix = tmp_path / "v"
    (venv_prefix / "Scripts").mkdir(parents=True)
    (venv_prefix / "Scripts" / "python.exe").write_text("")

    assert up._python_path(conda_prefix) == conda_prefix / "python.exe"
    assert up._python_path(venv_prefix) == venv_prefix / "Scripts" / "python.exe"
    assert up._python_path(tmp_path / "empty") is None
    assert up.Env("conda", "proj", conda_prefix).python == conda_prefix / "python.exe"


# --------------------------------------------------------------------------
# Unattended schedule — plans per platform, without installing anything
# --------------------------------------------------------------------------


def test_parse_time(up: ModuleType) -> None:
    assert up._parse_time("09:00") == (9, 0)
    assert up._parse_time("23:59") == (23, 59)
    for bad in ("9", "24:00", "09:60", "nine"):
        with pytest.raises(SystemExit):
            up._parse_time(bad)


def test_schedule_artifacts(up: ModuleType, tmp_path: Path) -> None:
    py, script, log = Path("/usr/bin/python3"), Path("/x/update_projects.py"), Path("/x/u.log")
    plist = up.launchd_plist(py, script, 7, 30, log)
    assert f"<string>{up.SCHEDULE_LABEL}</string>" in plist
    assert "<string>--log</string>" in plist
    assert "<key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer>" in plist
    assert "<key>RunAtLoad</key><false/>" in plist
    # --log writes the run; launchd capturing stdout too recorded it twice.
    assert "<key>StandardOutPath</key><string>/dev/null</string>" in plist
    assert f"<key>StandardErrorPath</key><string>{log}</string>" in plist

    wpy, wscript = Path("C:/py/python.exe"), Path("C:/u/update_projects.py")
    argv = up.schtasks_create_argv(wpy, wscript, 9, 5)
    assert argv[:2] == ["schtasks", "/Create"] and "/F" in argv
    assert argv[argv.index("/TN") + 1] == up.TASK_NAME
    assert argv[argv.index("/ST") + 1] == "09:05"
    assert argv[argv.index("/TR") + 1] == f'"{wpy}" "{wscript}" --log'  # quoted for spaces

    line = up.cron_line(py, script, 9, 0)
    assert line.startswith("0 9 * * * /usr/bin/python3 /x/update_projects.py --log")
    assert line.endswith(f"# {up.SCHEDULE_LABEL}")


def test_the_windows_task_catches_up_after_a_missed_start(up: ModuleType) -> None:
    """A PC that is off at 09:00 must run the job when it is back, not skip
    the day — which only a task definition can say (schtasks /SC cannot)."""
    import datetime as dt
    import xml.etree.ElementTree as ET

    py, script = Path("C:/Program Files/Py & Co/python.exe"), Path("C:/u/update_projects.py")
    xml = up.schtasks_xml(py, script, 9, 5, dt.date(2026, 9, 24))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml.encode("utf-16"))  # noqa: S314 — XML this module just generated
    assert root.findtext("t:Settings/t:StartWhenAvailable", namespaces=ns) == "true"
    assert root.findtext("t:Settings/t:DisallowStartIfOnBatteries", namespaces=ns) == "false"
    assert root.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=ns) == (
        "2026-09-24T09:05:00"
    )
    assert root.findtext(".//t:ScheduleByDay/t:DaysInterval", namespaces=ns) == "1"
    assert root.findtext(".//t:Exec/t:Command", namespaces=ns) == str(py)  # & survives escaping
    assert root.findtext(".//t:Exec/t:Arguments", namespaces=ns) == f'"{script}" --log'

    # A boundary already behind us today would read as a run to make up at once.
    assert up._next_start(9, 0, dt.datetime(2026, 9, 23, 8, 59)) == dt.date(2026, 9, 23)
    assert up._next_start(9, 0, dt.datetime(2026, 9, 23, 9, 0)) == dt.date(2026, 9, 24)


def test_a_refused_task_definition_falls_back_to_the_plain_daily_task(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(up, "CONFIG_DIR", tmp_path)
    calls: list[list[str]] = []
    definitions: list[str] = []

    def fake_sys(argv: list[str], stdin: object = None) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "/XML" in argv:
            definitions.append(Path(argv[argv.index("/XML") + 1]).read_text(encoding="utf-16"))
            return subprocess.CompletedProcess(argv, 1, "", "ERROR: task XML is malformed")
        return subprocess.CompletedProcess(argv, 0, "SUCCESS", "")

    monkeypatch.setattr(up, "_sys", fake_sys)
    py, script = Path("C:/py/python.exe"), Path("C:/u/update_projects.py")
    desc = up._install_windows_task(py, script, 9, 0, "daily at 09:00", dry_run=False)
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in definitions[0]
    assert calls[1] == up.schtasks_create_argv(py, script, 9, 0)
    assert "no catch-up" in desc and "malformed" in desc
    assert list(tmp_path.iterdir()) == []  # the definition file is not left behind

    calls.clear()
    monkeypatch.setattr(
        up,
        "_sys",
        lambda argv, stdin=None: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    desc = up._install_windows_task(py, script, 9, 0, "daily at 09:00", dry_run=False)
    assert len(calls) == 1 and "/XML" in calls[0] and "missed start runs" in desc


def test_install_schedule_dry_run_touches_nothing(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(up, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(up, "LOG_FILE", tmp_path / "cfg" / "update.log")
    monkeypatch.setattr(up, "LAUNCHER", tmp_path / "cfg" / "update_projects.py")
    calls: list[list[str]] = []
    monkeypatch.setattr(up, "_sys", lambda argv, stdin=None: calls.append(argv))
    desc = up.install_schedule("09:00", dry_run=True)
    assert "daily at 09:00" in desc and "update_projects.py" in desc
    assert calls == []  # dry run never calls launchctl / schtasks / crontab
    assert not (tmp_path / "cfg" / "update.log").exists()
    assert not (tmp_path / "cfg" / "update_projects.py").exists()  # nor installs the launcher


# --------------------------------------------------------------------------
# Gemini CLI / Codex ports — generated from the Claude Code sources
# --------------------------------------------------------------------------

COMMANDS_DIR = ROOT / "docs" / "claude-commands"


@pytest.mark.parametrize(
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-upgrade"]
)
def test_gemini_port_is_valid_toml_with_args(up: ModuleType, name: str) -> None:
    import tomllib

    body = (COMMANDS_DIR / f"{name}.md").read_text()
    parsed = tomllib.loads(up.port_gemini(name, body))
    assert set(parsed) == {"description", "prompt"}
    assert parsed["description"]  # the frontmatter description carried over
    assert "$ARGUMENTS" not in parsed["prompt"]
    assert "{{args}}" in parsed["prompt"]  # every command takes arguments
    assert "!{" not in parsed["prompt"] and "@{" not in parsed["prompt"]
    # Literal string: backslashes in Windows paths survive verbatim.
    if "\\" in body:
        assert "\\" in parsed["prompt"]


@pytest.mark.parametrize(
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-upgrade"]
)
def test_codex_port_is_a_skill(up: ModuleType, name: str) -> None:
    body = (COMMANDS_DIR / f"{name}.md").read_text()
    skill = up.port_codex(name, body)
    head, _, text = skill[4:].partition("\n---\n")
    assert f"name: {name}" in head and "description:" in head
    assert "usage: $" in head and "usage: /" not in head  # skills are $-invoked
    assert "$ARGUMENTS" not in text and "the text after the skill mention" in text


def test_gemini_port_refuses_injection_syntax(up: ModuleType) -> None:
    with pytest.raises(ValueError):
        up.port_gemini("x", "---\ndescription: d\n---\nrun !{rm -rf /}")


def test_refresh_installs_per_detected_agent(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr(up, "GEMINI_DIR", home / ".gemini")
    monkeypatch.setattr(up, "CODEX_DIR", home / ".codex")
    monkeypatch.setattr(up, "AGENTS_SKILLS_DIR", home / ".agents" / "skills")
    monkeypatch.setattr(up, "CODEX_LEGACY_SKILLS_DIR", home / ".codex" / "skills")
    monkeypatch.setattr(up, "CURSOR_DIR", home / ".cursor")
    monkeypatch.setattr(up, "OPENCODE_DIR", home / ".config" / "opencode")
    monkeypatch.setattr(up, "ANTIGRAVITY_STATE_DIR", home / ".gemini" / "antigravity-cli")
    monkeypatch.setattr(up, "ANTIGRAVITY_SKILLS_DIR", home / ".gemini" / "config" / "skills")
    monkeypatch.setattr(up, "COMMANDS", ("roadmap-step",))
    monkeypatch.setattr(up.shutil, "which", lambda _cmd: None)
    body = (COMMANDS_DIR / "roadmap-step.md").read_text()

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *a: object) -> None:
            pass

        def read(self) -> bytes:
            return body.encode()

    monkeypatch.setattr(up.urllib.request, "urlopen", lambda url, timeout=30: _Resp())

    # Only Claude Code assumed when no other agent dir exists.
    assert up.detect_agents() == ["claude"]
    report = up.refresh_commands()
    assert report[0] == "agents: claude" and "claude installed" in report[1]
    assert (home / ".claude" / "commands" / "roadmap-step.md").read_text() == body
    assert not (home / ".gemini").exists() and not (home / ".agents").exists()

    # A bare ~/.gemini is NOT the legacy CLI — Antigravity creates that too.
    (home / ".gemini").mkdir()
    assert up.detect_agents() == ["claude"]

    # Gemini + Codex present -> their ports land in their own dirs; Claude unchanged.
    (home / ".gemini" / "commands").mkdir()
    (home / ".codex").mkdir()
    assert up.detect_agents() == ["claude", "gemini", "codex"]
    report = up.refresh_commands()
    assert "claude unchanged" in report[1] and "gemini installed" in report[1]
    assert "codex installed" in report[1]
    assert (home / ".gemini" / "commands" / "roadmap-step.toml").exists()
    assert (home / ".agents" / "skills" / "roadmap-step" / "SKILL.md").exists()
    # Current Codex reads ~/.codex/skills too: a copy there would list the
    # skill twice, so our copy is removed — a user's own skill is not.
    ours = home / ".codex" / "skills" / "roadmap-step" / "SKILL.md"
    ours.parent.mkdir(parents=True)
    ours.write_text(up.port_codex("roadmap-step", body))
    theirs = home / ".codex" / "skills" / "roadmap-phase" / "SKILL.md"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("---\nname: roadmap-phase\ndescription: mine\n---\nhand-written\n")
    assert "legacy copy removed" in up.refresh_commands()[1]
    assert not ours.exists() and not ours.parent.exists()
    assert theirs.read_text().endswith("hand-written\n")
    # Second run: everything unchanged; dry-run never writes.
    assert all(
        s in up.refresh_commands()[1]
        for s in ("claude unchanged", "gemini unchanged", "codex unchanged")
    )


def test_refresh_retires_the_renamed_update_command(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/roadmodel-update became /roadmodel-upgrade (0.2.45). Every run removes
    the updater's own copies of the old name for every agent, and leaves a
    user's own command of that name alone."""
    home = tmp_path / "home"
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr(up, "GEMINI_DIR", home / ".gemini")
    monkeypatch.setattr(up, "CODEX_DIR", home / ".codex")
    monkeypatch.setattr(up, "AGENTS_SKILLS_DIR", home / ".agents" / "skills")
    monkeypatch.setattr(up, "CODEX_LEGACY_SKILLS_DIR", home / ".codex" / "skills")
    monkeypatch.setattr(up, "OPENCODE_DIR", home / ".config" / "opencode")
    monkeypatch.setattr(up, "ANTIGRAVITY_SKILLS_DIR", home / ".gemini" / "config" / "skills")
    monkeypatch.setattr(up, "ANTIGRAVITY_STATE_DIR", home / ".gemini" / "antigravity-cli")
    monkeypatch.setattr(up, "RETIRED_COMMANDS", ("roadmodel-update",))
    assert "roadmodel-upgrade" in up.COMMANDS and "roadmodel-update" not in up.COMMANDS
    old = (COMMANDS_DIR / "roadmodel-upgrade.md").read_text()
    ours = [
        home / ".claude" / "commands" / "roadmodel-update.md",
        home / ".gemini" / "commands" / "roadmodel-update.toml",
        home / ".codex" / "prompts" / "roadmodel-update.md",
        home / ".agents" / "skills" / "roadmodel-update" / "SKILL.md",
        home / ".config" / "opencode" / "commands" / "roadmodel-update.md",
        home / ".gemini" / "antigravity-cli" / "skills" / "roadmodel-update" / "SKILL.md",
    ]
    for path in ours:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(old)
    theirs = home / ".gemini" / "config" / "skills" / "roadmodel-update" / "SKILL.md"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("---\nname: roadmodel-update\n---\nmy own\n")

    assert up.retire_commands(dry_run=True) == ["roadmodel-update: retired — removed 6 old copies"]
    assert all(p.exists() for p in ours)  # dry run removes nothing
    assert up.retire_commands() == ["roadmodel-update: retired — removed 6 old copies"]
    assert not any(p.exists() for p in ours)
    assert not (home / ".agents" / "skills" / "roadmodel-update").exists()
    assert theirs.read_text().endswith("my own\n")
    assert up.retire_commands() == []  # nothing left of ours


def test_commands_only_cli_needs_no_registry(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--projects-file",
            str(tmp_path / "none.txt"),
            "--commands-only",
            "--dry-run",
            "--agents",
            "claude",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "agents: claude" in result.stdout


# --------------------------------------------------------------------------
# OpenCode port + Cursor as a consumer of ~/.agents/skills
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-upgrade"]
)
def test_opencode_port_keeps_arguments_and_refuses_injection(up: ModuleType, name: str) -> None:
    body = (COMMANDS_DIR / f"{name}.md").read_text()
    cmd = up.port_opencode(name, body)
    head, _, text = cmd[4:].partition("\n---\n")
    assert head.startswith("description: ")
    assert "$ARGUMENTS" in text  # OpenCode substitutes it natively
    assert "!`" not in text and "@" not in text
    with pytest.raises(ValueError):
        up.port_opencode("x", "---\ndescription: d\n---\nsee @README.md")


def test_cursor_and_opencode_detection_and_install(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr(up, "GEMINI_DIR", home / ".gemini")
    monkeypatch.setattr(up, "CODEX_DIR", home / ".codex")
    monkeypatch.setattr(up, "CODEX_LEGACY_SKILLS_DIR", home / ".codex" / "skills")
    monkeypatch.setattr(up, "AGENTS_SKILLS_DIR", home / ".agents" / "skills")
    monkeypatch.setattr(up, "CURSOR_DIR", home / ".cursor")
    monkeypatch.setattr(up, "OPENCODE_DIR", home / ".config" / "opencode")
    monkeypatch.setattr(up, "ANTIGRAVITY_STATE_DIR", home / ".gemini" / "antigravity-cli")
    monkeypatch.setattr(up, "ANTIGRAVITY_SKILLS_DIR", home / ".gemini" / "config" / "skills")
    monkeypatch.setattr(up, "COMMANDS", ("roadmap-step",))
    monkeypatch.setattr(up.shutil, "which", lambda _cmd: None)
    body = (COMMANDS_DIR / "roadmap-step.md").read_text()

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *a: object) -> None:
            pass

        def read(self) -> bytes:
            return body.encode()

    monkeypatch.setattr(up.urllib.request, "urlopen", lambda url, timeout=30: _Resp())

    # Cursor alone (no Codex): the shared skill lands once, labelled for Cursor.
    (home / ".cursor").mkdir(parents=True)
    assert up.detect_agents() == ["claude", "cursor"]
    line = up.refresh_commands()[1]
    assert "cursor installed" in line and "codex" not in line
    assert (home / ".agents" / "skills" / "roadmap-step" / "SKILL.md").exists()

    # Codex + Cursor: still one file, labelled for both; OpenCode gets its own.
    (home / ".codex").mkdir()
    (home / ".config" / "opencode").mkdir(parents=True)
    assert up.detect_agents() == ["claude", "codex", "cursor", "opencode"]
    line = up.refresh_commands()[1]
    assert "codex/cursor unchanged" in line and "opencode installed" in line
    assert (home / ".config" / "opencode" / "commands" / "roadmap-step.md").exists()


# --------------------------------------------------------------------------
# One command convention on every agent (Codex prompts, VS Code prompt files)
# --------------------------------------------------------------------------

_SOURCE_COMMAND = """---
description: Write the phase N roadmap (usage: /roadmap-phase 6 [output-path])
---

Write the Phase "$ARGUMENTS" roadmap for this project.
"""


def test_codex_prompt_keeps_the_placeholder_codex_expands(up: ModuleType) -> None:
    """Codex expands $ARGUMENTS / $1..$9 in a prompt file, so the same typed
    arguments reach the same place as in Claude Code — unlike a skill, where
    the text merely arrives as context."""
    out = up.port_codex_prompt("roadmap-phase", _SOURCE_COMMAND)
    assert out.startswith("---\n")
    assert 'description: "Write the phase N roadmap' in out
    assert "argument-hint:" in out  # the source takes arguments
    assert "$ARGUMENTS" in out
    # No `name:` key: Codex keys a prompt by its filename.
    assert "\nname:" not in out


def test_codex_prompt_omits_the_hint_when_there_are_no_arguments(up: ModuleType) -> None:
    out = up.port_codex_prompt("roadmap-project", "---\ndescription: Write it\n---\n\nGo.\n")
    assert "argument-hint:" not in out


def test_vscode_prompt_file_shape(up: ModuleType) -> None:
    """VS Code prompt files have no placeholder — what the user types after
    /name is appended — so the port says that in words instead of leaving a
    token that would render literally."""
    out = up.port_vscode("roadmap-phase", _SOURCE_COMMAND)
    assert out.startswith("---\nname: roadmap-phase\n")
    assert "agent: agent" in out
    assert "$ARGUMENTS" not in out
    # VS Code's own variable keeps the sentence grammatical; the note lets the
    # operator type `/roadmap-phase 1` instead of answering the input box.
    assert 'Write the Phase "${input:arguments}" roadmap' in out or "${input:arguments}" in out
    assert "already carries the arguments" in out
    assert "`/roadmap-phase 1`" in out


def test_vscode_prompt_without_arguments_gets_no_note(up: ModuleType) -> None:
    out = up.port_vscode("roadmap-project", "---\ndescription: Write it\n---\n\nGo.\n")
    assert "already carries the arguments" not in out
    assert "${input:" not in out


def test_detect_agents_reports_vscode_only_when_a_user_dir_exists(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(up, "_vscode_user_dirs", lambda: [])
    assert "vscode" not in up.detect_agents()
    monkeypatch.setattr(up, "_vscode_user_dirs", lambda: [tmp_path / "User"])
    assert "vscode" in up.detect_agents()


# --------------------------------------------------------------------------
# Runtime parity: same MCP tools, a calibrated effort, on every agent
# --------------------------------------------------------------------------

_ARGV = ["/Users/x/.config/roadmodel/mcp-launch.sh"]


def test_codex_sync_adds_mcp_and_removes_pinned_defaults(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchoring = no pin. Codex documents NO default model or effort as a
    value — the client resolves them from the catalog it fetches from OpenAI —
    so the only way to land on the provider's default is to name none."""
    import json as _json

    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        'model = "gpt-6-astra"\nmodel_reasoning_effort = "xhigh"\n\n'
        '[mcp_servers.railway]\ncommand = "railway"\nargs = ["mcp"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(up, "CODEX_DIR", codex)
    lines = up._sync_codex(_ARGV, anchor=True, dry_run=False)
    text = (codex / "config.toml").read_text(encoding="utf-8")

    assert "[mcp_servers.roadmodel]" in text
    assert _json.dumps(_ARGV[0]) in text
    assert "model_reasoning_effort" not in text
    assert 'model = "gpt-6-astra"' not in text
    assert "[mcp_servers.railway]" in text  # untouched
    assert "codex model: gpt-6-astra (pinned) -> provider default" in lines
    assert "codex effort: xhigh (pinned) -> provider default" in lines

    # Idempotent: a second run changes nothing and says so.
    again = up._sync_codex(_ARGV, anchor=True, dry_run=False)
    assert (codex / "config.toml").read_text(encoding="utf-8") == text
    assert "codex mcp: present" in again
    assert "codex effort: provider default" in again


def test_codex_unpin_never_touches_a_model_key_inside_a_table(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`model` under [profiles.x] or [models.new_thread] is a DIFFERENT
    setting. Only a top-level key — above the first table header — is a pin."""
    codex = tmp_path / ".codex"
    codex.mkdir()
    body = (
        'model = "gpt-6-astra"\n\n'
        '[profiles.deep]\nmodel = "gpt-6-sol"\nmodel_reasoning_effort = "high"\n\n'
        '[models.new_thread]\nmodel = "gpt-6-luna"\n'
    )
    (codex / "config.toml").write_text(body, encoding="utf-8")
    monkeypatch.setattr(up, "CODEX_DIR", codex)
    up._sync_codex(None, anchor=True, dry_run=False)
    text = (codex / "config.toml").read_text(encoding="utf-8")
    assert not text.startswith('model = "gpt-6-astra"')
    assert '[profiles.deep]\nmodel = "gpt-6-sol"\nmodel_reasoning_effort = "high"' in text
    assert '[models.new_thread]\nmodel = "gpt-6-luna"' in text


def test_keep_pins_leaves_a_deliberate_codex_pin_alone(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    body = 'model = "gpt-6-sol"\nmodel_reasoning_effort = "low"\n'
    (codex / "config.toml").write_text(body, encoding="utf-8")
    monkeypatch.setattr(up, "CODEX_DIR", codex)
    up._sync_codex(None, anchor=False, dry_run=False)
    text = (codex / "config.toml").read_text(encoding="utf-8")
    # Both pins survive; the sync may still add unrelated lines (the
    # instructions fallback), which is why this is not an equality check.
    assert 'model = "gpt-6-sol"' in text and 'model_reasoning_effort = "low"' in text


def test_json_mcp_sync_preserves_the_rest_of_the_file(up: ModuleType, tmp_path: Path) -> None:
    import json as _json

    settings = tmp_path / "settings.json"
    settings.write_text(
        _json.dumps({"theme": "dark", "mcpServers": {"other": {}}}), encoding="utf-8"
    )
    up._sync_json_mcp(settings, _ARGV, "gemini", dry_run=False)
    data = _json.loads(settings.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert set(data["mcpServers"]) == {"other", "roadmodel"}
    assert data["mcpServers"]["roadmodel"]["command"] == _ARGV[0]
    assert up._sync_json_mcp(settings, _ARGV, "gemini", dry_run=False) == ["gemini mcp: present"]


def test_claude_defaults_unpin_both_places_and_keep_every_ceiling(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default is pinned in TWO places: top-level `effortLevel`/`model`, and a
    per-model `modelSettings.<m>.effortLevel` that `/effort` writes and that
    outlives the session that chose it. Both go. A ceiling bounds escalation,
    it does not choose a starting point, so every `maxEffortLevel` stays."""
    import json as _json

    claude = tmp_path / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text(
        _json.dumps(
            {
                "effortLevel": "high",
                "model": "opus[1m]",
                "maxEffortLevel": "xhigh",
                "theme": "dark",
                "modelSettings": {
                    "claude-opus-5": {"effortLevel": "xhigh"},
                    "claude-fable-5-1": {"effortLevel": "max", "maxEffortLevel": "xhigh"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(up, "CLAUDE_DIR", claude)
    lines = up._sync_claude_defaults(anchor=True, dry_run=False)
    data = _json.loads(settings.read_text(encoding="utf-8"))

    assert "effortLevel" not in data and "model" not in data
    assert data["maxEffortLevel"] == "xhigh"  # top-level ceiling kept
    assert data["theme"] == "dark"  # unrelated keys kept
    # Emptied per-model entry dropped; a per-model CEILING survives on its own.
    assert data["modelSettings"] == {"claude-fable-5-1": {"maxEffortLevel": "xhigh"}}
    assert "provider default" in lines[0] and "claude-opus-5.effortLevel=xhigh" in lines[0]
    assert lines[1] == "claude ceiling: maxEffortLevel=xhigh (kept)"

    # Idempotent.
    assert up._sync_claude_defaults(anchor=True, dry_run=False)[0] == (
        "claude defaults: provider default"
    )


def test_claude_keep_pins_is_a_no_op(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(_json.dumps({"effortLevel": "max"}), encoding="utf-8")
    monkeypatch.setattr(up, "CLAUDE_DIR", claude)
    assert up._sync_claude_defaults(anchor=False, dry_run=False) == []
    assert _json.loads((claude / "settings.json").read_text())["effortLevel"] == "max"


def test_runtime_sync_is_a_no_op_under_dry_run(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(_json.dumps({"effortLevel": "max"}), encoding="utf-8")
    monkeypatch.setattr(up, "CLAUDE_DIR", claude)
    monkeypatch.setattr(up, "_roadmodel_mcp_command", lambda: None)
    lines = up.sync_agent_runtime(dry_run=True, agents=["claude"], anchor=True)
    assert lines[0] == "claude defaults: effortLevel=max (pinned) -> provider default"
    assert (
        _json.loads((claude / "settings.json").read_text(encoding="utf-8"))["effortLevel"] == "max"
    )


def test_antigravity_default_model_pin_is_removed(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rung is part of the model id, so `defaultAgentModelId` pins model
    AND effort. Trust in the same file is untouched."""
    import json as _json

    settings = tmp_path / "settings.json"
    settings.write_text(
        _json.dumps(
            {"defaultAgentModelId": "gemini-3.8-flash-medium", "trustedWorkspaces": ["/p"]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(up, "ANTIGRAVITY_SETTINGS", settings)
    assert up._sync_antigravity_defaults(anchor=True, dry_run=False) == [
        "antigravity defaults: gemini-3.8-flash-medium (pinned) -> provider default"
    ]
    assert _json.loads(settings.read_text()) == {"trustedWorkspaces": ["/p"]}
    assert up._sync_antigravity_defaults(anchor=True, dry_run=False) == [
        "antigravity defaults: provider default"
    ]


# --------------------------------------------------------------------------
# Project parity: the same instructions + memory for every agent
# --------------------------------------------------------------------------


def _memory_dir(up: ModuleType, project: Path, home: Path) -> Path:
    slug = str(project.resolve()).replace("/", "-").replace("\\", "-").replace(":", "")
    d = home / ".claude" / "projects" / slug / "memory"
    d.mkdir(parents=True)
    return d


def test_parity_writes_a_pointer_and_exports_memory_git_excluded(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "proj"
    (project / ".git" / "info").mkdir(parents=True)
    (project / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    mem = _memory_dir(up, project, home)
    (mem / "MEMORY.md").write_text("- [A fact](a.md) — hook\n", encoding="utf-8")
    (mem / "a.md").write_text("---\nname: a\n---\n\nThe fact body.\n", encoding="utf-8")

    lines = up.sync_project_parity(project, dry_run=False)

    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "CLAUDE.md" in agents, "a repo with CLAUDE.md must be pointed at it, not have it copied"
    assert "The fact body." not in agents, "AGENTS.md is tracked — no personal memory in it"
    exported = (project / up.AGENTS_MEMORY_REL).read_text(encoding="utf-8")
    assert exported.startswith(up._MEMORY_HEADER)
    assert "A fact" in exported and "The fact body." in exported
    # Personal: excluded LOCALLY so it cannot be committed, without a .gitignore diff.
    assert ".agents/" in (project / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert not (project / ".gitignore").exists()
    assert any("memory:" in ln for ln in lines)

    # Idempotent, and an existing AGENTS.md is never overwritten.
    (project / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
    again = up.sync_project_parity(project, dry_run=False)
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "# mine\n"
    assert any("present (left alone)" in ln for ln in again)


def test_memory_export_keeps_the_index_and_caps_the_bodies(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole memory dir can be 400 KB. The index always ships; bodies ship
    newest-first to a budget, and the rest are named so nothing vanishes."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr(up, "MEMORY_EXPORT_BUDGET_BYTES", 2_000)
    mem = _memory_dir(up, project, home)
    (mem / "MEMORY.md").write_text("- index line\n", encoding="utf-8")
    for i in range(6):
        f = mem / f"entry{i}.md"
        f.write_text("x" * 900 + f"\nunique-{i}\n", encoding="utf-8")
        os.utime(f, (1_000 + i, 1_000 + i))  # entry5 newest

    out = up.export_claude_memory(project)
    assert out is not None
    assert "- index line" in out
    assert "unique-5" in out, "newest entry must survive the cap"
    assert "unique-0" not in out, "oldest entry should be cut first"
    assert "Older entries (index only)" in out
    assert "`entry0`" in out
    assert len(out) < 6_000


def test_parity_does_not_clobber_a_hand_written_memory_file(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    mem = _memory_dir(up, project, home)
    (mem / "MEMORY.md").write_text("- x\n", encoding="utf-8")
    target = project / up.AGENTS_MEMORY_REL
    target.parent.mkdir(parents=True)
    target.write_text("# my own notes\n", encoding="utf-8")

    lines = up.sync_project_parity(project, dry_run=False)
    assert target.read_text(encoding="utf-8") == "# my own notes\n"
    assert any("hand-written" in ln for ln in lines)


def test_parity_dry_run_writes_nothing(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(up, "CLAUDE_DIR", home / ".claude")
    mem = _memory_dir(up, project, home)
    (mem / "MEMORY.md").write_text("- x\n", encoding="utf-8")
    up.sync_project_parity(project, dry_run=True)
    assert not (project / "AGENTS.md").exists()
    assert not (project / up.AGENTS_MEMORY_REL).exists()


def test_an_unrunnable_codex_pin_goes_even_under_keep_pins(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex on a ChatGPT sign-in answers 400 for the `*-codex` variants. That
    pin is dead, not a preference, so --keep-pins does not protect it; an
    API-key setup, where the variants still run, keeps it."""
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "auth.json").write_text("{}", encoding="utf-8")
    (codex / "config.toml").write_text(
        'model = "gpt-5.3-codex"\nmodel_reasoning_effort = "medium"\n', encoding="utf-8"
    )
    monkeypatch.setattr(up, "CODEX_DIR", codex)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    lines = up._sync_codex(None, anchor=False, dry_run=False)
    text = (codex / "config.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-5.3-codex"' not in text
    assert 'model_reasoning_effort = "medium"' in text  # a live pin, kept
    assert any("unrunnable on ChatGPT sign-in" in ln for ln in lines)

    (codex / "config.toml").write_text('model = "gpt-5.3-codex"\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    up._sync_codex(None, anchor=False, dry_run=False)
    assert 'model = "gpt-5.3-codex"' in (codex / "config.toml").read_text(encoding="utf-8")


def test_gemini_reads_the_same_instructions_files_as_the_others(
    up: ModuleType, tmp_path: Path
) -> None:
    """A project should need ONE instructions file, not one per agent: the
    Gemini CLI defaults to GEMINI.md, so point it at AGENTS.md / CLAUDE.md too."""
    import json as _json

    settings = tmp_path / "settings.json"
    settings.write_text(_json.dumps({"mcpServers": {"roadmodel": {}}}), encoding="utf-8")
    lines = up._sync_gemini_settings(settings, dry_run=False)
    data = _json.loads(settings.read_text(encoding="utf-8"))
    assert data["contextFileName"] == ["AGENTS.md", "CLAUDE.md", "GEMINI.md"]
    assert data["mcpServers"] == {"roadmodel": {}}  # untouched
    assert any("reads AGENTS.md" in ln for ln in lines)
    # An operator's own list is never overwritten.
    settings.write_text(_json.dumps({"contextFileName": "MINE.md"}), encoding="utf-8")
    assert up._sync_gemini_settings(settings, dry_run=False) == ["gemini instructions: present"]
    assert _json.loads(settings.read_text(encoding="utf-8"))["contextFileName"] == "MINE.md"


def test_gemini_trusts_every_registered_project(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Untrusted is the state that silently disables BOTH project context and
    MCP servers in the Gemini CLI — `gemini mcp list` just says "Disabled"."""
    import json as _json

    trusted = tmp_path / "trustedFolders.json"
    monkeypatch.setattr(up, "GEMINI_TRUSTED_FOLDERS", trusted)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    trusted.write_text(_json.dumps({str(a.resolve()): "TRUST_FOLDER"}), encoding="utf-8")

    lines = up._sync_gemini_trust([a, b], dry_run=False)
    data = _json.loads(trusted.read_text(encoding="utf-8"))
    assert data[str(a.resolve())] == "TRUST_FOLDER"  # preserved
    assert data[str(b.resolve())] == "TRUST_FOLDER"  # added
    assert any("trusted 1 project" in ln for ln in lines)
    assert any("all 2 project(s) trusted" in ln for ln in up._sync_gemini_trust([a, b], False))
    # Dry run writes nothing.
    c = tmp_path / "c"
    c.mkdir()
    up._sync_gemini_trust([c], dry_run=True)
    assert str(c.resolve()) not in _json.loads(trusted.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Antigravity: the Gemini CLI's successor shares ~/.gemini but nothing else.
# Its customization root is ~/.gemini/config, where a skill is ALSO a
# first-class /<name> slash command — so the operator types the same thing
# here as in Claude Code, and the legacy commands/*.toml are invisible to it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-upgrade"]
)
def test_antigravity_port_is_a_slash_invocable_skill(up: ModuleType, name: str) -> None:
    body = (COMMANDS_DIR / f"{name}.md").read_text()
    out = up.port_antigravity(name, body)
    head, _, text = out[4:].partition("\n---\n")
    assert f"name: {name}" in head and head.count("description: ") == 1
    # Slash commands are typed with a leading /, so the usage line stays as-is
    # (unlike the Codex skill port, which rewrites it to $).
    assert "usage: $" not in head
    # Skills take no placeholder: the arguments arrive as message text.
    assert "$ARGUMENTS" not in text


def test_antigravity_port_tells_the_model_to_use_inline_arguments(up: ModuleType) -> None:
    out = up.port_antigravity("roadmap-phase", "---\ndescription: d\n---\n\nWrite $ARGUMENTS.\n")
    # A mid-sentence placeholder stays a visible slot, not prose.
    assert "Write <arguments>." in out
    assert "`/roadmap-phase 1`" in out
    # A command with no arguments gets no note.
    assert "already carries the arguments" not in up.port_antigravity(
        "roadmap-project", "---\ndescription: d\n---\n\nGo.\n"
    )


def test_antigravity_refresh_mirrors_cli_and_ide_skills(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    home = tmp_path / "home"
    monkeypatch.setattr(up, "ANTIGRAVITY_SKILLS_DIR", home / ".gemini/config/skills")
    monkeypatch.setattr(up, "ANTIGRAVITY_STATE_DIR", home / ".gemini/antigravity-cli")
    monkeypatch.setattr(up, "COMMANDS", ("roadmodel-upgrade",))
    body = COMMAND.read_bytes()
    monkeypatch.setattr(up.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(body))
    up.refresh_commands(dry_run=True, agents=["antigravity"])
    assert not home.exists()
    lines = up.refresh_commands(agents=["antigravity"])
    ide = home / ".gemini/config/skills/roadmodel-upgrade/SKILL.md"
    cli = home / ".gemini/antigravity-cli/skills/roadmodel-upgrade/SKILL.md"
    assert ide.read_bytes() == cli.read_bytes()
    assert "name: roadmodel-upgrade" in cli.read_text()
    assert "--sync-only" in cli.read_text()
    assert "antigravity installed" in lines[1]
    assert "antigravity-cli installed" in lines[1]
    mtimes = (ide.stat().st_mtime_ns, cli.stat().st_mtime_ns)
    lines = up.refresh_commands(agents=["antigravity"])
    assert "antigravity unchanged" in lines[1]
    assert "antigravity-cli unchanged" in lines[1]
    assert (ide.stat().st_mtime_ns, cli.stat().st_mtime_ns) == mtimes


def test_antigravity_detected_by_its_own_state_dir_not_a_bare_gemini_dir(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(up, "GEMINI_DIR", home / ".gemini")
    monkeypatch.setattr(up, "ANTIGRAVITY_STATE_DIR", home / ".gemini" / "antigravity-cli")
    monkeypatch.setattr(up, "CODEX_DIR", home / ".codex")
    monkeypatch.setattr(up, "AGENTS_SKILLS_DIR", home / ".agents" / "skills")
    monkeypatch.setattr(up, "CURSOR_DIR", home / ".cursor")
    monkeypatch.setattr(up, "OPENCODE_DIR", home / ".config" / "opencode")
    monkeypatch.setattr(up, "_vscode_user_dirs", lambda: [])
    monkeypatch.setattr(up.shutil, "which", lambda _cmd: None)

    (home / ".gemini").mkdir(parents=True)
    assert up.detect_agents() == ["claude"]  # Antigravity has not run here yet

    (home / ".gemini" / "antigravity-cli").mkdir()
    assert up.detect_agents() == ["claude", "antigravity"]  # and still not "gemini"


def test_antigravity_mcp_accepts_the_zero_byte_file_it_ships(
    up: ModuleType, tmp_path: Path
) -> None:
    """Antigravity creates mcp_config.json empty. An empty file means "no
    servers"; treating it as corrupt would silently skip the sync."""
    import json as _json

    path = tmp_path / "mcp_config.json"
    path.write_text("")
    assert up._sync_json_mcp(path, _ARGV, "antigravity", dry_run=False) == [
        "antigravity mcp: added roadmodel"
    ]
    assert _json.loads(path.read_text())["mcpServers"]["roadmodel"]["command"] == _ARGV[0]


def test_antigravity_trust_uses_its_own_settings_not_the_legacy_file(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antigravity records trust as `trustedWorkspaces` in its OWN settings
    file. The legacy CLI's trustedFolders.json is a different file that
    Antigravity never reads, so trusting there leaves it untrusted here."""
    import json as _json

    settings = tmp_path / "antigravity-cli" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(_json.dumps({"trustedWorkspaces": [str(tmp_path / "already")]}))
    monkeypatch.setattr(up, "ANTIGRAVITY_SETTINGS", settings)

    a, b = tmp_path / "already", tmp_path / "fresh"
    a.mkdir()
    b.mkdir()
    assert up._sync_antigravity_trust([a, b], dry_run=False) == [
        "antigravity trust: trusted 1 project(s)"
    ]
    trusted = _json.loads(settings.read_text())["trustedWorkspaces"]
    assert str(b.resolve()) in trusted
    assert trusted.count(str(a.resolve())) == 1, "an already-trusted path must not duplicate"

    # Idempotent: a second run adds nothing.
    assert up._sync_antigravity_trust([a, b], dry_run=False) == [
        "antigravity trust: all 2 project(s) trusted"
    ]


def test_antigravity_trust_preserves_other_settings_keys(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same file carries defaultAgentModelId; trusting must not drop it."""
    import json as _json

    settings = tmp_path / "settings.json"
    settings.write_text(_json.dumps({"defaultAgentModelId": "gemini-3.8-flash-medium"}))
    monkeypatch.setattr(up, "ANTIGRAVITY_SETTINGS", settings)
    project = tmp_path / "proj"
    project.mkdir()

    up._sync_antigravity_trust([project], dry_run=False)
    data = _json.loads(settings.read_text())
    assert data["defaultAgentModelId"] == "gemini-3.8-flash-medium"
    assert data["trustedWorkspaces"] == [str(project.resolve())]


def test_antigravity_trust_dry_run_writes_nothing(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(up, "ANTIGRAVITY_SETTINGS", settings)
    project = tmp_path / "proj"
    project.mkdir()
    assert up._sync_antigravity_trust([project], dry_run=True) == [
        "antigravity trust: trusted 1 project(s)"
    ]
    assert not settings.exists()


# --------------------------------------------------------------------------
# Self-update: the machine's copy is a launcher that upgrades roadmodel in its
# own venv and hands the run to the updater inside that release. Every
# subprocess is faked here; nothing reaches PyPI.
# --------------------------------------------------------------------------


class _Machine:
    """Fakes the launcher's subprocess calls (venv, pip, probes, self-checks)
    against a tmp CONFIG_DIR, and records what ran."""

    def __init__(self, up: ModuleType, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.cfg = tmp / "cfg"
        self.cfg.mkdir()
        self.venv = self.cfg / "venv"
        self.launcher = self.cfg / "update_projects.py"
        self.launcher.write_bytes(b"# the launcher as last fetched\n")
        self.packaged = tmp / "site-packages" / "roadmodel" / "update_projects.py"
        self.packaged.parent.mkdir(parents=True)
        self.packaged.write_bytes(b"# the updater in the release\n")
        self.versions = ["0.2.38", "0.2.39"]  # before / after the pip upgrade
        self.ships_module = True
        self.pip_rc = 0
        self.venv_rc = 0
        self.module_check_rc = 0
        self.script_check_rc = 0
        self.calls: list[list[str]] = []
        self.handed: list[tuple[list[str], dict[str, str]]] = []
        for name, value in (
            ("CONFIG_DIR", self.cfg),
            ("UPDATER_VENV", self.venv),
            ("LAUNCHER", self.launcher),
        ):
            monkeypatch.setattr(up, name, value)
        monkeypatch.setattr(up, "_run", self._run)
        monkeypatch.setattr(up, "_handover", self._handover)
        monkeypatch.delenv(up.DELEGATED_ENV, raising=False)

    def python(self) -> Path:
        return self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _run(
        self, argv: list[str], timeout: int, cwd: object = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)

        def done(rc: int = 0, out: str = "") -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, rc, out, "boom" if rc else "")

        if argv[1:3] == ["-m", "venv"]:
            if self.venv_rc == 0:
                (self.venv / "pyvenv.cfg").parent.mkdir(parents=True, exist_ok=True)
                (self.venv / "pyvenv.cfg").write_text("home = x\n")
                self.python().parent.mkdir(parents=True, exist_ok=True)
                self.python().write_text("")
            return done(self.venv_rc)
        if "pip" in argv:
            if self.pip_rc == 0 and len(self.versions) > 1:
                self.versions.pop(0)
            return done(self.pip_rc)
        if argv[-1] == "--self-check":
            module = "-m" in argv
            return done(self.module_check_rc if module else self.script_check_rc)
        code = argv[-1]
        if "find_spec" in code:
            return done(0, str(self.packaged) if self.ships_module else "")
        if "__version__" in code:
            return done(0, self.versions[0])
        return done(0)  # the "new enough Python" probe

    def _handover(self, argv: list[str], env: dict[str, str]) -> int:
        self.handed.append((argv, env))
        return 0


def test_the_launcher_upgrades_refreshes_itself_and_hands_over(
    up: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    m = _Machine(up, tmp_path, monkeypatch)
    code = up.self_update(["--log", "--brand-new-flag"], tmp_path / "projects.txt")

    assert code == 0
    assert [c for c in m.calls if c[1:3] == ["-m", "venv"]], "a missing venv is built"
    pip = next(c for c in m.calls if "pip" in c)
    assert pip[0] == str(m.python()) and "--no-cache-dir" in pip and pip[-1] == "roadmodel"
    # The launcher becomes the release's copy of itself: no more re-fetching.
    assert m.launcher.read_bytes() == m.packaged.read_bytes()
    ((argv, env),) = m.handed
    assert argv == [str(m.python()), "-m", "roadmodel.update_projects", "--log", "--brand-new-flag"]
    assert env[up.DELEGATED_ENV] == sys.executable  # the handed-over run never hands over again
    out = capsys.readouterr().out
    assert "roadmodel 0.2.39 (was 0.2.38)" in out and "launcher refreshed" in out


def test_a_release_without_the_packaged_updater_keeps_the_local_copy(
    up: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Until the first release that ships it, the launcher runs itself —
    so a machine can switch over before that release exists."""
    m = _Machine(up, tmp_path, monkeypatch)
    m.ships_module = False
    before = m.launcher.read_bytes()
    assert up.self_update([], tmp_path / "projects.txt") is None
    assert m.handed == [] and m.launcher.read_bytes() == before
    assert "no packaged updater yet" in capsys.readouterr().out


def test_a_release_whose_updater_does_not_start_is_never_run_or_installed(
    up: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    m = _Machine(up, tmp_path, monkeypatch)
    m.module_check_rc = 1
    before = m.launcher.read_bytes()
    assert up.self_update([], tmp_path / "projects.txt") is None
    assert m.handed == [] and m.launcher.read_bytes() == before
    assert "does not start" in capsys.readouterr().out


def test_the_launcher_is_replaced_only_by_a_copy_that_starts_on_its_interpreter(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The schedule's interpreter may be older than the venv's. A release that
    runs in the venv but not there still takes the run, and the launcher that
    can still start stays."""
    m = _Machine(up, tmp_path, monkeypatch)
    m.script_check_rc = 1
    before = m.launcher.read_bytes()
    assert up.self_update([], tmp_path / "projects.txt") == 0
    assert m.launcher.read_bytes() == before
    assert len(m.handed) == 1


def test_an_offline_morning_still_hands_over_to_the_installed_release(
    up: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    m = _Machine(up, tmp_path, monkeypatch)
    m.pip_rc = 1
    assert up.self_update([], tmp_path / "projects.txt") == 0
    assert len(m.handed) == 1
    assert "upgrade failed" in capsys.readouterr().out


def test_a_venv_that_cannot_be_built_falls_back_loudly(
    up: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    m = _Machine(up, tmp_path, monkeypatch)
    m.venv_rc = 1
    assert up.self_update([], tmp_path / "projects.txt") is None
    assert m.handed == []
    assert "*** self-update FAILED" in capsys.readouterr().out


def test_a_foreign_directory_at_the_venv_path_is_never_cleared(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = _Machine(up, tmp_path, monkeypatch)
    m.venv.mkdir()
    (m.venv / "precious.txt").write_text("not a venv")
    assert up.self_update([], tmp_path / "projects.txt") is None
    assert not [c for c in m.calls if c[1:3] == ["-m", "venv"]]
    assert (m.venv / "precious.txt").read_text() == "not a venv"


def test_only_the_installed_copy_hands_over(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo checkout runs its own code (development, these tests); the
    installed copy hands over; a run it handed over to never does."""
    launcher = tmp_path / "update_projects.py"
    launcher.write_text("x")
    monkeypatch.setattr(up, "LAUNCHER", launcher)
    monkeypatch.delenv(up.DELEGATED_ENV, raising=False)
    assert up.should_self_update(SCRIPT) is False
    assert up.should_self_update(launcher) is True
    monkeypatch.setenv(up.DELEGATED_ENV, sys.executable)
    assert up.should_self_update(launcher) is False


def test_main_hands_over_before_parsing_flags_it_does_not_know(
    up: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A launcher one release behind must not reject a flag the release added."""
    seen: list[list[str]] = []
    monkeypatch.setattr(up, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(up, "should_self_update", lambda self_path=None: True)
    monkeypatch.setattr(up, "self_update", lambda raw, pf: seen.append(raw) or 7)
    assert up.main(["--brand-new-flag"]) == 7
    assert seen == [["--brand-new-flag"]]


def test_a_dry_run_never_self_updates(
    up: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(up, "should_self_update", lambda self_path=None: True)
    monkeypatch.setattr(up, "self_update", lambda raw, pf: pytest.fail("self_update ran"))
    empty = tmp_path / "projects.txt"
    empty.write_text("")
    assert up.main(["--dry-run", "--projects-file", str(empty)]) == 2
    assert "self-update: skipped (dry run)" in capsys.readouterr().out


def test_self_check_loads_and_builds_the_cli_without_side_effects(
    up: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(up, "self_update", lambda raw, pf: pytest.fail("self_update ran"))
    assert up.main(["--self-check"]) == 0
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--self-check"], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0 and done.stdout == ""


def test_a_handed_over_run_continues_its_launchers_log_section(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "update.log"
    monkeypatch.setattr(up, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(up, "LOG_FILE", log)
    monkeypatch.setattr(up, "LOG_MAX_BYTES", 10)
    log.write_text("x" * 100)
    monkeypatch.setenv(up.DELEGATED_ENV, sys.executable)
    up._open_log().close()
    assert log.read_text() == "x" * 100  # no second header, no rotation mid-run
    monkeypatch.delenv(up.DELEGATED_ENV)
    up._open_log().close()
    assert "=====" in log.read_text() and len(log.read_text()) < 100


def test_a_schedule_runs_the_launcher_on_the_interpreter_that_started_it(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed from inside the venv (a handed-over run), the schedule must
    still name the launcher's interpreter, or rebuilding the venv would take
    the schedule down with it."""
    launcher = tmp_path / "cfg" / "update_projects.py"
    monkeypatch.setattr(up, "LAUNCHER", launcher)
    monkeypatch.setenv(up.DELEGATED_ENV, sys.executable)
    assert up._launcher_python() == Path(sys.executable).resolve()
    assert up._install_launcher(dry_run=False) == launcher
    assert not launcher.exists()  # the launcher that started the run is left alone

    monkeypatch.delenv(up.DELEGATED_ENV)
    assert up._install_launcher(dry_run=True) == launcher and not launcher.exists()
    assert up._install_launcher(dry_run=False) == launcher
    assert launcher.read_bytes() == SCRIPT.read_bytes()  # installed from a checkout


def test_the_launcher_stays_python_3_9_compatible() -> None:
    """The launcher runs on whatever interpreter the schedule names, which can
    be older than roadmodel's own floor."""
    import ast

    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 9))


# --------------------------------------------------------------------------
# User-context sync: one source, published through a private repo, pulled by
# every other machine. A local bare repo stands in for GitHub so these run
# offline and exercise the real git paths.
# --------------------------------------------------------------------------


@pytest.fixture
def ctx(up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Two machines' config dirs and a bare 'remote', with a deterministic git
    identity and default branch so the test does not depend on the host's."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Test\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    return {"remote": remote, "mac": tmp_path / "mac", "pc": tmp_path / "pc"}


def _as_machine(up: ModuleType, monkeypatch: pytest.MonkeyPatch, cfg_dir: Path) -> None:
    monkeypatch.setattr(up, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(up, "CONTEXT_SYNC_CONFIG", cfg_dir / "context-sync.json")
    monkeypatch.setattr(up, "CONTEXT_CLONE", cfg_dir / "context-repo")
    monkeypatch.setattr(up, "USER_CONTEXT", cfg_dir / "user-context.md")


def test_an_unconfigured_machine_sees_nothing(
    up: ModuleType, ctx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator with one machine must not get a new line of noise."""
    _as_machine(up, monkeypatch, ctx["mac"])
    assert up.sync_user_context() == []


def test_the_source_publishes_and_a_replica_pulls_the_same_bytes(
    up: ModuleType, ctx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ctx["mac"] / "project" / "user-context.md"
    source.parent.mkdir(parents=True)
    source.write_text("# User Context\n\nClaude Max · ChatGPT Pro · Google AI Pro\n")

    _as_machine(up, monkeypatch, ctx["mac"])
    up.configure_context_sync(str(ctx["remote"]), str(source))
    published = up.sync_user_context()
    assert published[-1].startswith("user-context sync: published")
    assert up.sync_user_context()[-1].startswith("user-context sync: source unchanged")

    _as_machine(up, monkeypatch, ctx["pc"])
    up.configure_context_sync(str(ctx["remote"]), None)
    assert up.sync_user_context()[0].startswith("user-context sync: pulled")
    assert (ctx["pc"] / "user-context.md").read_bytes() == source.read_bytes()
    assert up.sync_user_context()[0].startswith("user-context sync: current")


def test_an_edit_at_the_source_reaches_the_replica_next_run(
    up: ModuleType, ctx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a pool binds, the operator edits ONE file, and the
    other machine plans against it the next morning — no paste."""
    source = ctx["mac"] / "uc.md"
    source.parent.mkdir(parents=True)
    source.write_text("pool: headroom\n")
    _as_machine(up, monkeypatch, ctx["mac"])
    up.configure_context_sync(str(ctx["remote"]), str(source))
    up.sync_user_context()
    _as_machine(up, monkeypatch, ctx["pc"])
    up.configure_context_sync(str(ctx["remote"]), None)
    up.sync_user_context()

    source.write_text("pool: exhausted\n")
    _as_machine(up, monkeypatch, ctx["mac"])
    assert up.sync_user_context()[-1].startswith("user-context sync: published")
    _as_machine(up, monkeypatch, ctx["pc"])
    assert up.sync_user_context()[0].startswith("user-context sync: pulled")
    assert (ctx["pc"] / "user-context.md").read_text() == "pool: exhausted\n"
    # What a replica overwrote is kept, not silently lost.
    assert (ctx["pc"] / "user-context.md.prev").read_text() == "pool: headroom\n"


def test_a_replica_before_anything_is_published_says_so(
    up: ModuleType, ctx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_machine(up, monkeypatch, ctx["pc"])
    up.configure_context_sync(str(ctx["remote"]), None)
    assert up.sync_user_context() == [
        "user-context sync: nothing published yet (run the source machine first)"
    ]
    assert not (ctx["pc"] / "user-context.md").exists()


def test_the_source_warns_about_a_separate_copy_that_would_never_publish(
    up: ModuleType, ctx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the source machine the default path should POINT AT the source. A
    separate file there is a trap: edits to it go nowhere."""
    source = ctx["mac"] / "project" / "uc.md"
    source.parent.mkdir(parents=True)
    source.write_text("the source\n")
    _as_machine(up, monkeypatch, ctx["mac"])
    (ctx["mac"] / "user-context.md").write_text("a stale separate copy\n")
    up.configure_context_sync(str(ctx["remote"]), str(source))
    lines = up.sync_user_context()
    assert any("WARNING" in ln and "NOT published" in ln for ln in lines)


def test_configure_rejects_a_bad_repo_or_a_missing_source(
    up: ModuleType, ctx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_machine(up, monkeypatch, ctx["mac"])
    with pytest.raises(SystemExit):
        up.configure_context_sync("not a repo", None)
    with pytest.raises(SystemExit):
        up.configure_context_sync("owner/repo", str(ctx["mac"] / "absent.md"))
    assert "REPLICA" in up.configure_context_sync("owner/repo", None, dry_run=True)


def test_the_personal_user_context_can_never_be_committed_to_this_public_repo() -> None:
    """docs/user-context.md is the operator's real context — subscriptions and
    account names — and the SOURCE the private sync publishes. This repo is
    public. If the .gitignore line that keeps it out is ever removed, fail."""
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "docs/user-context.md"], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0, "docs/user-context.md must stay gitignored"


# --------------------------------------------------------------------------
# Roadmap refresh across every project (--refresh-roadmaps, automatic runs)
#
# 2026-09-28 the operator asked for /roadmap-refresh in every project at once,
# on demand and automatically, after eight refreshes were run by hand. These
# pin the three things that make an unattended run safe: a project with work
# in flight is skipped, the session is told it is unattended and runs in
# Claude Code's auto permission mode, and it only runs automatically when the
# roadmap rules changed.
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _refresh_in_tmp(up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may read or write this machine's refresh state, cache or logs."""
    monkeypatch.setattr(up, "REFRESH_STATE", tmp_path / "cfg" / "refresh-state.json")
    monkeypatch.setattr(up, "REFRESH_CACHE", tmp_path / "cache" / "refresh")
    monkeypatch.setattr(up, "REFRESH_LOGS", tmp_path / "cfg" / "refresh-logs")


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _g(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    ).stdout


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    """A checkout of a bare origin, on main, holding ``files``."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _g(seed, "init", "-q", "-b", "main")
    for rel, text in files.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text)
    _g(seed, "add", "-A")
    _g(seed, "commit", "-q", "-m", "init")
    origin = tmp_path / "origin.git"
    _g(tmp_path, "init", "-q", "--bare", str(origin))
    _g(seed, "push", "-q", str(origin), "main:main")
    _g(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    project = tmp_path / "project"
    _g(tmp_path, "clone", "-q", str(origin), str(project))
    return project


_ROADMAPS = {
    "docs/roadmap/ROADMAP.md": "# P\n",
    "docs/roadmap/phase01-roadmap.md": (
        "## Step 1 — x\n\n**Status:** Not started\n\n**Branch:** `feature/phase01-step1-x`\n"
    ),
    "README.md": "hi\n",
}


def test_roadmap_paths_are_recognised(up: ModuleType) -> None:
    for path in (
        "ROADMAP.md",
        "docs/ROADMAP.md",
        "phase01-roadmap.md",
        "docs/phase31.5-roadmap.md",
        "docs/phase04.6-catalog-federation-roadmap.md",
        "docs/phase31j-roadmap.md",
        "docs/roadmap/agentic-bot-farm-v1.md",
        "docs\\roadmap\\phase02-roadmap.md",
    ):
        assert up._is_roadmap_path(path), path
    for path in ("docs/phase01-qa-findings.md", "README.md", "docs/test-automation.md"):
        assert not up._is_roadmap_path(path), path


def test_plan_refresh_clones_a_clean_project(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, _ROADMAPS)
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: {"dependabot/x": 3})
    plan = up.plan_refresh(up.Entry(project))
    assert (plan.mode, plan.default) == ("clone", "main"), plan.reason
    assert plan.remote.endswith("origin.git")


def test_plan_refresh_skips_work_in_flight(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, _ROADMAPS)
    entry = up.Entry(project)

    # A step PR from a branch the roadmaps name.
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: {"feature/phase01-step1-x": 7})
    plan = up.plan_refresh(entry)
    assert plan.mode == "skip" and "step PR #7" in plan.reason
    # An earlier refresh's PR still open.
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: {"chore/roadmap-refresh-2026-09-28": 9})
    assert "earlier refresh's PR #9" in up.plan_refresh(entry).reason
    # gh cannot answer: skip rather than guess.
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: None)
    assert "gh could not list PRs" in up.plan_refresh(entry).reason
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: {})

    # Edits under planning/ are the daily kit export, not work in flight.
    (project / "planning").mkdir()
    (project / "planning" / "x.md").write_text("kit\n")
    _g(project, "add", "planning/x.md")
    _g(project, "commit", "-q", "-m", "kit")
    (project / "planning" / "x.md").write_text("kit, re-exported\n")
    assert up.plan_refresh(entry).mode == "clone"
    # Any other uncommitted edit is.
    (project / "README.md").write_text("edited\n")
    assert "uncommitted edits (README.md)" in up.plan_refresh(entry).reason
    _g(project, "checkout", "-q", "--", "README.md")
    # A roadmap written but not yet committed.
    (project / "docs" / "roadmap" / "phase02-roadmap.md").write_text("# 2\n")
    assert "roadmap not yet committed" in up.plan_refresh(entry).reason
    (project / "docs" / "roadmap" / "phase02-roadmap.md").unlink()
    # Checked out on another branch.
    _g(project, "checkout", "-q", "-b", "feature/phase01-step1-x")
    assert up.plan_refresh(entry).reason == "on branch feature/phase01-step1-x, not main"


def test_plan_refresh_edits_git_excluded_roadmaps_in_place(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, {".gitignore": "private/\n", "README.md": "hi\n"})
    (project / "private").mkdir()
    (project / "private" / "ROADMAP.md").write_text("# private\n")
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: pytest.fail("no PR lookup in place"))
    plan = up.plan_refresh(up.Entry(project))
    assert plan.mode == "in-place"
    # Without roadmaps anywhere there is nothing to do.
    other = tmp_path / "other"
    other.mkdir()
    bare = _project(other, {"README.md": "hi\n"})
    assert up.plan_refresh(up.Entry(bare)).reason == "no tracked roadmaps"
    assert up.plan_refresh(up.Entry(tmp_path)).reason == "not a git checkout"


def test_refresh_prompt_is_unattended_and_carries_the_procedure(up: ModuleType) -> None:
    body = (COMMANDS_DIR / "roadmap-refresh.md").read_text()
    entry = up.Entry(Path("/p/demo"))
    clone = up.refresh_prompt(body, up.RefreshPlan(entry, "clone", default="main"), Path("/c"))
    assert clone.startswith("UNATTENDED RUN.")
    assert "Ask nothing; nobody will answer" in clone
    assert "handed the call back" in clone
    assert "Never commit planning/user-context.md" in clone
    assert "Never run `--post`" in clone
    assert "Leave every pull request you did not open alone" in clone
    assert "do not look for a way around it" in clone
    assert "REFRESH-RESULT: merged <PR URL>" in clone
    assert "fresh clone of the project (/c)" in clone and "`main` checked out" in clone
    # The procedure follows, without its frontmatter or the $ARGUMENTS token.
    assert "## 1. Locate, and move into `docs/roadmap/`" in clone
    assert "description:" not in clone and "$ARGUMENTS" not in clone
    in_place = up.refresh_prompt(
        body, up.RefreshPlan(entry, "in-place"), Path("/p/demo"), Path("/k/planning")
    )
    assert "operator's own checkout (/p/demo)" in in_place
    assert "No branch, no commit, no PR" in in_place
    assert "exported to /k/planning" in in_place


def test_claude_runs_headless_in_auto_mode_with_the_prompt_on_stdin(up: ModuleType) -> None:
    argv = up.claude_refresh_argv("claude")
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--permission-mode") + 1] == "auto"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--dangerously-skip-permissions" not in argv
    assert not any("UNATTENDED" in a for a in argv)  # the prompt travels on stdin


@pytest.mark.parametrize(
    ("result", "status", "detail"),
    [
        ("done\nREFRESH-RESULT: merged https://x/pull/5", "ok", "merged https://x/pull/5"),
        ("REFRESH-RESULT: no changes", "ok", "no changes"),
        ("REFRESH-RESULT: in place", "ok", "in place"),
        (
            "REFRESH-RESULT: open https://x/pull/6 — CI red",
            "attention",
            "open https://x/pull/6 — CI red",
        ),
        ("REFRESH-RESULT: stopped — refused", "attention", "stopped — refused"),
        ("all good, trust me", "attention", "no REFRESH-RESULT line; read the log"),
    ],
)
def test_parse_refresh_output(up: ModuleType, result: str, status: str, detail: str) -> None:
    import json

    out = json.dumps({"type": "result", "is_error": False, "result": result, "total_cost_usd": 2.5})
    assert up.parse_refresh_output(out) == (status, detail, 2.5)


def test_parse_refresh_output_failures(up: ModuleType) -> None:
    import json

    err = json.dumps({"is_error": True, "result": "Error: usage limit reached"})
    assert up.parse_refresh_output(err) == ("FAILED", "Error: usage limit reached", None)
    status, detail, _ = up.parse_refresh_output("not json")
    assert status == "FAILED" and detail.startswith("no JSON from claude")


def _fake_claude(tmp_path: Path, verdict: str) -> Path:
    script = tmp_path / "fake-claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "prompt = sys.stdin.read()\n"
        "assert prompt.startswith('UNATTENDED RUN.'), prompt[:80]\n"
        "assert sys.argv[1:3] == ['-p', '--permission-mode'], sys.argv\n"
        "open('cwd.txt', 'w').write(os.getcwd())\n"
        "print(json.dumps({'is_error': False, 'total_cost_usd': 1.25,\n"
        f"                  'result': 'worked\\nREFRESH-RESULT: {verdict}'}}))\n"
    )
    script.chmod(0o755)
    return script


@pytest.mark.skipif(os.name == "nt", reason="the fake claude is a POSIX script")
def test_run_refresh_clones_runs_claude_and_cleans_up(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, _ROADMAPS)
    monkeypatch.setattr(up, "_open_pr_heads", lambda _p: {})
    monkeypatch.setattr(up, "_export_kit", lambda _e, _t: "kit exported")
    plan = up.plan_refresh(up.Entry(project))
    body = (COMMANDS_DIR / "roadmap-refresh.md").read_text()

    ok = up.run_refresh(plan, str(_fake_claude(tmp_path, "no changes")), body, "20260929-0900")
    assert (ok.status, ok.detail, ok.cost) == ("ok", "no changes", 1.25)
    workdir = up.REFRESH_CACHE / "project-20260929-0900"
    assert not workdir.exists()  # a finished clone is removed
    assert ok.log is not None and "REFRESH-RESULT: no changes" in ok.log.read_text()
    assert (project / "cwd.txt").exists() is False  # the session never ran in the checkout

    stuck = up.run_refresh(
        plan, str(_fake_claude(tmp_path, "stopped — refused")), body, "20260929-0910"
    )
    assert stuck.status == "attention"
    kept = up.REFRESH_CACHE / "project-20260929-0910"
    assert (kept / "cwd.txt").read_text() == str(kept)  # it ran in the clone, kept for a look
    assert (kept / "docs" / "roadmap" / "phase01-roadmap.md").exists()


def test_rules_fingerprint_follows_commands_and_kit(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = tmp_path / "claude"
    (claude / "commands").mkdir(parents=True)
    kit = tmp_path / "kit"
    kit.mkdir()
    for name in up.RULE_KIT_FILES:
        (kit / name).write_text(f"{name}\n")
    (claude / "commands" / "roadmap-refresh.md").write_text("refresh v1\n")
    monkeypatch.setattr(up, "CLAUDE_DIR", claude)
    monkeypatch.setattr(up, "_rule_kit_dir", lambda: kit)
    first = up.rules_fingerprint()
    (claude / "commands" / "roadmap-refresh.md").write_text("refresh v1\r\n")
    assert up.rules_fingerprint() == first  # line endings are not a rule change
    (claude / "commands" / "roadmap-refresh.md").write_text("refresh v2\n")
    second = up.rules_fingerprint()
    assert second != first
    (kit / "phase-roadmap-template.md").write_text("new layout\n")
    assert up.rules_fingerprint() != second
    # The updater finds its own templates, packaged or in this checkout.
    monkeypatch.undo()
    assert up._rule_kit_dir() == ROOT / "docs" / "templates"


def test_refresh_runs_automatically_only_when_the_rules_change(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = up.Entry(tmp_path / "a"), up.Entry(tmp_path / "b")
    fingerprint = {"value": "rules-1"}
    ran: list[str] = []
    monkeypatch.setattr(up, "rules_fingerprint", lambda: fingerprint["value"])
    monkeypatch.setattr(up, "claude_executable", lambda: "claude")
    monkeypatch.setattr(up, "_refresh_command_body", lambda: "---\ndescription: d\n---\nbody")
    monkeypatch.setattr(up, "plan_refresh", lambda e: up.RefreshPlan(e, "clone", default="main"))

    def fake_run(plan, claude, body, stamp):
        ran.append(plan.entry.name)
        status = "ok" if plan.entry.name == "a" else "skipped"
        return up.RefreshResult(plan.entry, status, "merged https://x/pull/1")

    monkeypatch.setattr(up, "run_refresh", fake_run)

    # First sight: recorded as current, nothing runs.
    lines, attention = up.refresh_roadmaps(
        [a, b], on_demand=False, unattended=True, jobs=2, dry_run=False
    )
    assert ran == [] and not attention and "nothing to refresh" in lines[0]
    state = up.load_refresh_state()
    assert state["auto"] is True and set(state["projects"]) == {str(a.path), str(b.path)}

    # Same rules: nothing runs.
    up.refresh_roadmaps([a, b], on_demand=False, unattended=True, jobs=2, dry_run=False)
    assert ran == []

    # New rules, but a manual run: reported, not run.
    fingerprint["value"] = "rules-2"
    lines, _ = up.refresh_roadmaps([a, b], on_demand=False, unattended=False, jobs=2, dry_run=False)
    assert ran == [] and "due for a refresh: a, b" in lines[0] and "--refresh-roadmaps" in lines[1]

    # The daily run refreshes both; only the one that finished is recorded.
    up.refresh_roadmaps([a, b], on_demand=False, unattended=True, jobs=2, dry_run=False)
    assert sorted(ran) == ["a", "b"]
    state = up.load_refresh_state()
    assert state["projects"][str(a.path)]["fingerprint"] == "rules-2"
    assert state["projects"][str(b.path)]["fingerprint"] == "rules-1"  # retried next run

    # Next day: only the skipped one is still due.
    ran.clear()
    up.refresh_roadmaps([a, b], on_demand=False, unattended=True, jobs=2, dry_run=False)
    assert ran == ["b"]

    # Switched off: reported, never run.
    ran.clear()
    state = up.load_refresh_state()
    state["auto"] = False
    up.save_refresh_state(state)
    lines, _ = up.refresh_roadmaps([a, b], on_demand=False, unattended=True, jobs=2, dry_run=False)
    assert ran == [] and "automatic refresh is off" in lines[1]

    # On demand runs every project regardless.
    up.refresh_roadmaps([a, b], on_demand=True, unattended=False, jobs=2, dry_run=False)
    assert sorted(ran) == ["a", "b"]


def test_refresh_dry_run_plans_and_writes_nothing(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = up.Entry(tmp_path / "a")
    monkeypatch.setattr(up, "rules_fingerprint", lambda: "rules-1")
    monkeypatch.setattr(
        up, "plan_refresh", lambda e: up.RefreshPlan(e, "skip", "on branch x, not main")
    )
    monkeypatch.setattr(up, "run_refresh", lambda *a, **k: pytest.fail("a dry run ran a refresh"))
    lines, _ = up.refresh_roadmaps([a], on_demand=True, unattended=False, jobs=1, dry_run=True)
    assert lines == ["a: skip — on branch x, not main"]
    assert not up.REFRESH_STATE.exists()


def test_refresh_flags_are_on_the_cli(up: ModuleType) -> None:
    args = up._parser().parse_args(
        ["--refresh-roadmaps", "--auto-refresh", "off", "--refresh-jobs", "2"]
    )
    assert (args.refresh_roadmaps, args.auto_refresh, args.refresh_jobs) == (True, "off", 2)
    assert up._parser().parse_args([]).refresh_jobs == 3


def test_upgrade_command_documents_the_fleet_refresh() -> None:
    flat = " ".join(COMMAND.read_text().split())
    assert "[--refresh-roadmaps]" in flat
    assert "`--refresh-roadmaps` runs `/roadmap-refresh` in every registered project" in flat
    assert "in a fresh clone of the project, so the operator's checkout is never touched" in flat
    assert "`auto` permission mode" in flat
    assert "A project where work may be in flight is skipped and named" in flat
    assert "when the roadmap rules change" in flat and "`--auto-refresh off`" in flat


def test_output_survives_a_cp1252_console(up: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-09-29, the PC over SSH: printing a result line with ✅ to a cp1252
    pipe raised UnicodeEncodeError. A refresh detail is model-written, so the
    updater's own output must degrade to "?" instead of ending the run."""
    import io

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", console)
    with pytest.raises(UnicodeEncodeError):
        print("REFRESH-RESULT: no changes ✅ → done")
    up.tolerate_unencodable_output()
    print("REFRESH-RESULT: no changes ✅ → done")
    console.flush()
    assert raw.getvalue().endswith(b"REFRESH-RESULT: no changes ? ? done\n")


# --------------------------------------------------------------------------
# The MCP server's own env — upgraded with the projects (2026-10-02: the
# Mac's sat on 0.2.36 for 28 releases because nothing touched it)
# --------------------------------------------------------------------------

_BIN = "Scripts" if os.name == "nt" else "bin"
_MCP_EXE = "roadmodel-mcp.exe" if os.name == "nt" else "roadmodel-mcp"


def _mcp_venv(root: Path) -> tuple[Path, Path]:
    """A venv with a python and the roadmodel-mcp console script; returns both."""
    prefix = _fake_venv(root, "mcp-venv")
    script = prefix / _BIN / _MCP_EXE
    script.write_text("")
    python = prefix / _BIN / ("python.exe" if os.name == "nt" else "python")
    return python, script


def test_mcp_python_from_the_console_script(up: ModuleType, tmp_path: Path) -> None:
    python, script = _mcp_venv(tmp_path)
    assert up.mcp_server_python([str(script)]) == python


def test_mcp_python_through_a_launcher_script(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python, _ = _mcp_venv(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    launcher = tmp_path / "mcp-launch.sh"
    launcher.write_text(
        "#!/bin/sh\n"
        "# Launches roadmodel-mcp (stdio) for Claude Code.\n"
        'export GOOGLE_API_KEY="$(security find-generic-password -w)"\n'
        f'exec "$HOME/mcp-venv/{_BIN}/{_MCP_EXE}"\n'
    )
    assert up.mcp_server_python([str(launcher)]) == python


def test_mcp_python_when_an_interpreter_runs_the_module(up: ModuleType, tmp_path: Path) -> None:
    python, _ = _mcp_venv(tmp_path)
    assert up.mcp_server_python([str(python), "-m", "roadmodel.mcp_server"]) == python


def test_an_unplaceable_mcp_registration_needs_attention(up: ModuleType, tmp_path: Path) -> None:
    launcher = tmp_path / "launch.sh"
    launcher.write_text("#!/bin/sh\nexec roadmodel-mcp\n")  # bare name: nothing to place
    assert up.mcp_server_python([str(launcher)]) is None
    assert up.mcp_server_python([str(tmp_path / "missing")]) is None
    line, ok = up.update_mcp_env([str(launcher)], dry_run=False)
    assert not ok and "could not find the interpreter" in line


def test_no_mcp_registration_is_fine(up: ModuleType) -> None:
    line, ok = up.update_mcp_env(None, dry_run=False)
    assert ok and "no roadmodel MCP registration" in line


def test_mcp_env_upgrades_with_the_mcp_extra(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python, script = _mcp_venv(tmp_path)
    calls: list[list[str]] = []
    versions = iter(["0.2.36", "0.2.64"])
    monkeypatch.setattr(up, "installed_version", lambda _python: next(versions))

    def fake_run(argv: list[str], timeout: int, cwd: object = None) -> object:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(up, "_run", fake_run)
    line, ok = up.update_mcp_env([str(script)], dry_run=False)
    assert ok
    assert calls == [up._pip_upgrade(python, "roadmodel[mcp]")]
    assert calls[0][-1] == "roadmodel[mcp]" and "--no-cache-dir" in calls[0]
    assert line.startswith("0.2.36 -> 0.2.64") and "restart agent sessions" in line


def test_mcp_env_dry_run_and_pip_failure(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python, script = _mcp_venv(tmp_path)
    monkeypatch.setattr(up, "_run", lambda *a, **k: pytest.fail("dry run must not run pip"))
    line, ok = up.update_mcp_env([str(script)], dry_run=True)
    assert ok and line == f"plan: upgrade roadmodel[mcp] with {python}"

    monkeypatch.setattr(up, "installed_version", lambda _python: "0.2.36")
    monkeypatch.setattr(
        up,
        "_run",
        lambda argv, timeout, cwd=None: subprocess.CompletedProcess(argv, 1, "", "no network"),
    )
    line, ok = up.update_mcp_env([str(script)], dry_run=False)
    assert not ok and "pip install failed" in line and "no network" in line
