# tests/test_update_projects.py
"""Guards on scripts/update_projects.py — the one-run "upgrade roadmodel in
every project" updater behind /roadmodel-update.

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
COMMAND = ROOT / "docs" / "claude-commands" / "roadmodel-update.md"


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


def test_empty_registry_explains_how_to_add(tmp_path: Path) -> None:
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

    wpy, wscript = Path("C:/py/python.exe"), Path("C:/u/update_projects.py")
    argv = up.schtasks_create_argv(wpy, wscript, 9, 5)
    assert argv[:2] == ["schtasks", "/Create"] and "/F" in argv
    assert argv[argv.index("/TN") + 1] == up.TASK_NAME
    assert argv[argv.index("/ST") + 1] == "09:05"
    assert argv[argv.index("/TR") + 1] == f'"{wpy}" "{wscript}" --log'  # quoted for spaces

    line = up.cron_line(py, script, 9, 0)
    assert line.startswith("0 9 * * * /usr/bin/python3 /x/update_projects.py --log")
    assert line.endswith(f"# {up.SCHEDULE_LABEL}")


def test_install_schedule_dry_run_touches_nothing(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(up, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(up, "LOG_FILE", tmp_path / "cfg" / "update.log")
    calls: list[list[str]] = []
    monkeypatch.setattr(up, "_sys", lambda argv, stdin=None: calls.append(argv))
    desc = up.install_schedule("09:00", dry_run=True)
    assert "daily at 09:00" in desc and "update_projects.py" in desc
    assert calls == []  # dry run never calls launchctl / schtasks / crontab
    assert not (tmp_path / "cfg" / "update.log").exists()


# --------------------------------------------------------------------------
# Gemini CLI / Codex ports — generated from the Claude Code sources
# --------------------------------------------------------------------------

COMMANDS_DIR = ROOT / "docs" / "claude-commands"


@pytest.mark.parametrize(
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-update"]
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
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-update"]
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
    monkeypatch.setattr(up, "COMMANDS", ("roadmap-step",))
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

    # Gemini + Codex present -> their ports land in their own dirs; Claude unchanged.
    (home / ".gemini").mkdir()
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
    "name", ["roadmap-project", "roadmap-phase", "roadmap-step", "roadmodel-update"]
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
    monkeypatch.setattr(up, "COMMANDS", ("roadmap-step",))
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


def test_codex_sync_adds_mcp_and_calibrates_a_pinned_top_rung(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        'model = "gpt-5.3-codex"\nmodel_reasoning_effort = "xhigh"\n\n'
        '[mcp_servers.railway]\ncommand = "railway"\nargs = ["mcp"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(up, "CODEX_DIR", codex)
    lines = up._sync_codex(_ARGV, calibrate=True, dry_run=False)
    text = (codex / "config.toml").read_text(encoding="utf-8")

    assert "[mcp_servers.roadmodel]" in text
    assert _json.dumps(_ARGV[0]) in text
    assert 'model_reasoning_effort = "medium"' in text
    assert 'model = "gpt-5.3-codex"' in text  # untouched
    assert "[mcp_servers.railway]" in text  # untouched
    assert any("effort: xhigh -> medium" in ln for ln in lines)

    # Idempotent: a second run changes nothing and says so.
    again = up._sync_codex(_ARGV, calibrate=True, dry_run=False)
    assert (codex / "config.toml").read_text(encoding="utf-8") == text
    assert any("mcp: present" in ln for ln in again)
    assert any("medium (left alone)" in ln for ln in again)


def test_codex_sync_leaves_a_deliberate_lower_effort_alone(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text('model_reasoning_effort = "low"\n', encoding="utf-8")
    monkeypatch.setattr(up, "CODEX_DIR", codex)
    up._sync_codex(None, calibrate=True, dry_run=False)
    assert 'model_reasoning_effort = "low"' in (codex / "config.toml").read_text(encoding="utf-8")


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


def test_claude_effort_calibration_touches_only_a_pinned_default(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    claude = tmp_path / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text(
        _json.dumps({"effortLevel": "max", "maxEffortLevel": "xhigh", "model": "opus[1m]"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(up, "CLAUDE_DIR", claude)
    lines = up._sync_claude_effort(calibrate=True, dry_run=False)
    data = _json.loads(settings.read_text(encoding="utf-8"))
    assert data["effortLevel"] == "high"
    assert data["maxEffortLevel"] == "xhigh"  # a CEILING is not a pinned default
    assert data["model"] == "opus[1m]"
    assert lines == ["claude effort: max -> high"]
    assert up._sync_claude_effort(calibrate=True, dry_run=False) == [
        "claude effort: high (left alone)"
    ]


def test_runtime_sync_is_a_no_op_under_dry_run(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(_json.dumps({"effortLevel": "max"}), encoding="utf-8")
    monkeypatch.setattr(up, "CLAUDE_DIR", claude)
    monkeypatch.setattr(up, "_roadmodel_mcp_command", lambda: None)
    lines = up.sync_agent_runtime(dry_run=True, agents=["claude"], calibrate=True)
    assert lines == ["claude effort: max -> high"]
    assert (
        _json.loads((claude / "settings.json").read_text(encoding="utf-8"))["effortLevel"] == "max"
    )
