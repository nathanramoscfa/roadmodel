"""Unit tests for the Claude Code CHANGELOG refresh validator.

Exercises ``update/validate_claude_code_diff.py`` against synthetic
CHANGELOG fixtures so the coverage check + citation check behave as
documented. Covers:

- Happy path: every pending version is consumed and every trigger
  bullet's tokens appear in the diff → PASS.
- Missing version in consumed_versions → FAIL.
- Trigger bullet with no diff citation → FAIL.
- Non-trigger bullets are exempt from the citation check.
- No-op release (all bullets non-trigger) → PASS with consumed_versions
  present.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "update" / "validate_claude_code_diff.py"


def _write_pending(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "pending-bullets.json"
    path.write_text(json.dumps(entries))
    return path


def _write_consumed(tmp_path: Path, versions: list[str]) -> Path:
    path = tmp_path / "consumed.json"
    path.write_text(json.dumps({"consumed_versions": versions}))
    return path


def _run_validator(
    pending: Path,
    consumed: Path,
    before: Path,
    after: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--pending",
            str(pending),
            "--consumed-versions",
            str(consumed),
            "--before",
            str(before),
            "--after",
            str(after),
        ],
        capture_output=True,
        text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    """Every version consumed; trigger bullet's token lands in the diff."""
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.158",
                "bullets": ["Added /effort ultracode slash command"],
            }
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.158"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("- Effort levels: low / medium / high\n")
    after.write_text("- Effort levels: low / medium / high / ultracode\n")

    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_missing_consumed_version_fails(tmp_path: Path) -> None:
    """Coverage check: pending version not in consumed_versions → FAIL."""
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.158",
                "bullets": ["Cosmetic UI tweak"],
            },
            {
                "version": "2.1.157",
                "bullets": ["Internal refactor"],
            },
        ],
    )
    # Only 2.1.158 consumed; 2.1.157 silently skipped.
    consumed = _write_consumed(tmp_path, ["2.1.158"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("x\n")
    after.write_text("x\n")

    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 1
    assert "2.1.157" in result.stderr
    assert "coverage check" in result.stderr


def test_trigger_bullet_without_citation_fails(tmp_path: Path) -> None:
    """Citation check: trigger bullet with no diff token → FAIL."""
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.158",
                "bullets": ["Added /effort ultracode slash command for deeper reasoning"],
            }
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.158"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    # Diff contains nothing matching ultracode / effort / slash.
    before.write_text("- Anthropic exposes thinking on/off\n")
    after.write_text("- Anthropic exposes thinking on/off; refreshed wording\n")

    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 1
    assert "citation check" in result.stderr
    assert "2.1.158" in result.stderr


def test_non_trigger_bullets_are_exempt(tmp_path: Path) -> None:
    """A version with only cosmetic bullets passes without any diff edit."""
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.156",
                "bullets": [
                    "Improved error messages",
                    "Bumped minor dependency",
                ],
            }
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.156"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("unchanged\n")
    after.write_text("unchanged\n")

    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_generic_feature_bullets_do_not_trigger(tmp_path: Path) -> None:
    """Regression (2026-06): real CHANGELOG bullets about generic Claude Code
    features — NOT reasoning/effort dials — must not trip the citation check.

    These four bullets matched the old over-broad keywords ("slash command",
    "settings.json", "claude_code_") and blocked the cron for ~2 weeks even
    though none touches the selector's documented surface parameters. With no
    effort/thinking edit in the diff the validator must still PASS.
    """
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.191",
                "bullets": [
                    "Improved vim mode prompt-history search (NORMAL `/`) to "
                    "hint how to reach slash commands",
                ],
            },
            {
                "version": "2.1.187",
                "bullets": [
                    "Fixed remote MCP tool calls that hang with no response for 5 "
                    "minutes (override with `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`)",
                ],
            },
            {
                "version": "2.1.186",
                "bullets": [
                    "`!` bash commands now trigger Claude to respond to the output "
                    'automatically; set `"respondToBashCommands": false` in '
                    "settings.json to keep the previous behavior",
                    "Changed `CLAUDE_CODE_MAX_RETRIES` to cap at 15; use "
                    "`CLAUDE_CODE_RETRY_WATCHDOG` for unattended sessions",
                ],
            },
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.191", "2.1.187", "2.1.186"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    # No reasoning-surface edit at all — yet must PASS, because none of these
    # bullets is an effort/thinking-dial change.
    before.write_text("- Effort levels: low / medium / high / xhigh\n")
    after.write_text("- Effort levels: low / medium / high / xhigh\n")

    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_pending_file_missing_errors_cleanly(tmp_path: Path) -> None:
    """Validator exits 2 (config error) when pending-bullets.json is missing."""
    consumed = _write_consumed(tmp_path, [])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("a\n")
    after.write_text("a\n")

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--pending",
            str(tmp_path / "does-not-exist.json"),
            "--consumed-versions",
            str(consumed),
            "--before",
            str(before),
            "--after",
            str(after),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_parse_versions_via_update_module(tmp_path: Path) -> None:
    """Smoke-test the changelog parser used pre-Opus."""
    sys.path.insert(0, str(REPO_ROOT / "update"))
    try:
        import importlib

        mod = importlib.import_module("update_claude_code")
        importlib.reload(mod)
    finally:
        sys.path.pop(0)

    changelog = (
        "# Changelog\n\n"
        "## 2.1.158\n\n"
        "- Added /effort ultracode\n"
        "- Internal cleanup\n\n"
        "## 2.1.157\n\n"
        "- Renamed slider labels to Faster / Smarter\n\n"
        "## 2.1.156\n\n"
        "- Minor fixes\n"
    )
    parsed = mod.parse_versions(changelog)
    assert [v for v, _ in parsed] == ["2.1.158", "2.1.157", "2.1.156"]
    assert parsed[0][1] == ["Added /effort ultracode", "Internal cleanup"]

    # new_versions slicing.
    new = mod.new_versions(parsed, "2.1.157")
    assert [v for v, _ in new] == ["2.1.158"]

    # Cache miss → bounded backstop of up to 5 most-recent.
    new_miss = mod.new_versions(parsed, "9.9.9")
    assert [v for v, _ in new_miss] == ["2.1.158", "2.1.157", "2.1.156"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
