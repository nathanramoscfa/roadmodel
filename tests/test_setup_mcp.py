"""Tests for `roadmodel setup-mcp` — the one-command MCP registration.

The command exists to collapse the old multi-step, per-project setup into a
single call, so the behaviour that matters is: it registers THIS environment's
launcher by ABSOLUTE path (the bare name is not on PATH inside a conda env /
venv, which is what made registrations resolve to nothing), and every failure
mode tells the user exactly what to run instead.
"""

from __future__ import annotations

import os
import subprocess

import pytest
from click.testing import CliRunner

from roadmodel import cli as cli_module

_EXE = "roadmodel-mcp.exe" if os.name == "nt" else "roadmodel-mcp"


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A launcher in this interpreter's scripts dir, as a real install has."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    exe = scripts / _EXE
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        cli_module.sysconfig, "get_path", lambda key: str(scripts) if key == "scripts" else ""
    )
    return exe


def test_dry_run_prints_command_and_changes_nothing(server, monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli_module.subprocess, "run", lambda *a, **k: calls.append(a))
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "mcp add" in result.output
    assert "--scope user" in result.output
    assert str(server) in result.output
    assert not calls, "dry-run must not shell out"


def test_missing_mcp_extra_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr(cli_module.importlib.util, "find_spec", lambda name: None)
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp"])
    assert result.exit_code != 0
    assert "roadmodel[mcp]" in result.output


def test_missing_claude_cli_prints_the_manual_command(server, monkeypatch) -> None:
    monkeypatch.setattr(cli_module.shutil, "which", lambda name: None)
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp"])
    assert result.exit_code != 0
    assert "mcp add" in result.output
    assert str(server) in result.output  # still tells them the absolute path


def test_registers_this_environments_launcher_by_absolute_path(server, monkeypatch) -> None:
    monkeypatch.setattr(cli_module.shutil, "which", lambda name: "/usr/bin/claude")
    seen: dict[str, list[str]] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        return _completed()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp"])
    assert result.exit_code == 0, result.output
    assert seen["argv"] == [
        "/usr/bin/claude",
        "mcp",
        "add",
        "--scope",
        "user",
        "roadmodel",
        "--",
        str(server),
    ]
    assert "Registered MCP server 'roadmodel'" in result.output


def test_already_registered_hints_force(server, monkeypatch) -> None:
    monkeypatch.setattr(cli_module.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr="MCP server roadmodel already exists"),
    )
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp"])
    assert result.exit_code != 0
    assert "--force" in result.output


def test_force_removes_then_adds(server, monkeypatch) -> None:
    monkeypatch.setattr(cli_module.shutil, "which", lambda name: "/usr/bin/claude")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return _completed()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp", "--force"])
    assert result.exit_code == 0, result.output
    assert calls[0][1:4] == ["mcp", "remove", "--scope"]
    assert calls[1][1:3] == ["mcp", "add"]


def test_scope_is_configurable(server, monkeypatch) -> None:
    monkeypatch.setattr(cli_module.shutil, "which", lambda name: "/usr/bin/claude")
    seen: dict[str, list[str]] = {}
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda argv, **k: (seen.update(argv=list(argv)), _completed())[1],
    )
    result = CliRunner().invoke(cli_module.cli, ["setup-mcp", "--scope", "project"])
    assert result.exit_code == 0, result.output
    assert "--scope" in seen["argv"] and "project" in seen["argv"]
