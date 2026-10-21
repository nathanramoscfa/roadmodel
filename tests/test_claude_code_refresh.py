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


def test_permission_auto_mode_bullets_do_not_trigger(tmp_path: Path) -> None:
    """Regression (2026-09, #801): "auto mode" is Claude Code's permission
    mode, no reasoning dial. 2.1.281–2.1.285 mention it in a dozen bullets,
    and as a trigger keyword it failed the cron every day from 2026-09-26."""
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.285",
                "bullets": [
                    "Fixed background subagents in auto mode prompting a second, "
                    "redundant reply after each report",
                ],
            },
            {
                "version": "2.1.281",
                "bullets": [
                    "Added an auto mode recommendation to `/insights` that estimates "
                    "how many permission prompts auto mode could have handled",
                ],
            },
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.285", "2.1.281"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("- Effort levels: low / medium / high / xhigh\n")
    after.write_text("- Effort levels: low / medium / high / xhigh\n")
    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_bug_fix_bullets_do_not_trigger(tmp_path: Path) -> None:
    """Regression (2026-10-01): a bug fix restores documented behaviour, so a
    "Fixed ..." bullet that names a dial needs no selector edit. A bullet that
    CHANGES the dial still triggers."""
    pending = _write_pending(
        tmp_path,
        [
            {
                "version": "2.1.282",
                "bullets": [
                    "Fixed continued or resumed conversations losing earlier extended "
                    "thinking when relaunched with a `--tools` list that leaves out a "
                    "built-in tool offered earlier in the conversation",
                    "[VSCode] Fixed `/effort` showing the wrong level after a reload",
                ],
            },
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.282"])
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("- Effort levels: low / medium / high / xhigh\n")
    after.write_text("- Effort levels: low / medium / high / xhigh\n")
    result = _run_validator(pending, consumed, before, after)
    assert result.returncode == 0, result.stderr
    pending.write_text(
        '[{"version": "2.1.290", "bullets": ["Changed the default extended thinking budget"]}]'
    )
    _write_consumed(tmp_path, ["2.1.290"])
    assert _run_validator(pending, consumed, before, after).returncode != 0


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


# --------------------------------------------------------------------------- #
# Thinking-toggle keywords, control-removing "Fixed" bullets, and the review
# route that replaced the citation hard-fail under the typed boundary (#1149).
# --------------------------------------------------------------------------- #

# The two real CHANGELOG bullets that took the THINKING switch away on the
# always-thinking models. Both start "Fixed", both went unflagged.
THINKING_2_1_300 = (
    "[VSCode] Fixed the Thinking toggle switching to Off on models that always "
    "think; the toggle is no longer shown for those models"
)
THINKING_2_1_281 = (
    "Fixed Alt+T and `/config` offering to turn thinking off on models that "
    "can\u2019t; thinking now stays on there, with a one-line reason in place of the switch"
)


def _diff_module():
    sys.path.insert(0, str(REPO_ROOT / "update"))
    try:
        import importlib

        mod = importlib.import_module("validate_claude_code_diff")
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def test_thinking_toggle_keywords_are_triggers() -> None:
    mod = _diff_module()
    for kw in (
        "thinking toggle",
        "alt+t",
        "option+t",
        "alwaysthinkingenabled",
        "max_thinking_tokens",
        "turn thinking off",
        "thinking can't be turned off",
        "adaptive thinking",
        "ultracode",
    ):
        assert kw in mod.TRIGGER_KEYWORDS, kw
    assert mod.bullet_is_trigger("Added `alwaysThinkingEnabled` per model")
    assert mod.bullet_is_trigger("Option+T now shows Thinking can\u2019t be turned off")


def test_fixed_bullets_that_remove_a_control_still_trigger() -> None:
    """2.1.300 and 2.1.281 read as bug fixes but removed the THINKING dial on
    five models: the "Fixed" exemption must not swallow them."""
    mod = _diff_module()
    assert mod.bullet_is_trigger(THINKING_2_1_300)
    assert mod.bullet_is_trigger(THINKING_2_1_281)
    for phrase in ("removed", "instead of offering", "replacing", "hidden", "no longer offer"):
        assert mod.bullet_is_trigger(f"Fixed the effort level control, {phrase} on Haiku"), phrase
    # A fix that only restores behaviour stays exempt, new keyword or not.
    assert not mod.bullet_is_trigger(
        "Fixed token counts for Haiku 5.5 and other models that take only adaptive "
        "thinking, which failed behind some gateways"
    )
    assert not mod.bullet_is_trigger("[VSCode] Fixed `/effort` showing the wrong level")


def _run_routed(tmp_path: Path, pending: Path, consumed: Path, queue: Path):
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text('<model id="x" input-price-per-1m="$1.00"/>\n')
    after.write_text('<model id="x" input-price-per-1m="$1.10"/>\n')
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
            "--review-queue",
            str(queue),
        ],
        capture_output=True,
        text=True,
    )


def test_uncited_trigger_bullets_route_to_review_under_the_boundary(tmp_path: Path) -> None:
    """#1149: the cron may not edit selector prose, so a trigger bullet it
    cannot cite is queued for a review issue and the run passes — the exact
    2.1.299 bullets that failed every run from 2026-10-14."""
    bullets = [
        "Added /effort and /fast in agent view",
        "Added /usage warnings for max effort sessions",
        THINKING_2_1_300,
    ]
    pending = _write_pending(tmp_path, [{"version": "2.1.299", "bullets": bullets}])
    consumed = _write_consumed(tmp_path, ["2.1.299"])
    queue = tmp_path / "review.json"

    result = _run_routed(tmp_path, pending, consumed, queue)
    assert result.returncode == 0, result.stderr
    assert "ROUTED" in result.stdout
    items = json.loads(queue.read_text())
    assert len(items) == 3
    assert all(
        item["title"].startswith("chore(claude-code): review Claude Code 2.1.299") for item in items
    )
    assert any("no longer shown" in item["body"] for item in items)

    # A rerun of the same run queues nothing new (titles dedup).
    assert _run_routed(tmp_path, pending, consumed, queue).returncode == 0
    assert len(json.loads(queue.read_text())) == 3

    # Without the flag (a reviewed, hand-run refresh) the miss still fails.
    before, after = tmp_path / "before.txt", tmp_path / "after.txt"
    assert _run_validator(pending, consumed, before, after).returncode == 1


def test_review_route_keeps_the_coverage_check_fatal(tmp_path: Path) -> None:
    pending = _write_pending(
        tmp_path,
        [
            {"version": "2.1.300", "bullets": [THINKING_2_1_300]},
            {"version": "2.1.299", "bullets": []},
        ],
    )
    consumed = _write_consumed(tmp_path, ["2.1.300"])
    result = _run_routed(tmp_path, pending, consumed, tmp_path / "review.json")
    assert result.returncode == 1
    assert "coverage check" in result.stderr


def test_opus_needs_review_and_validator_share_one_issue(tmp_path: Path) -> None:
    """The prompt makes the pass report a removed control in needs_review; the
    validator routes the same bullet. Same title, so one issue."""
    sys.path.insert(0, str(REPO_ROOT / "update"))
    try:
        import importlib

        updater = importlib.reload(importlib.import_module("update_claude_code"))
        queue_mod = importlib.reload(importlib.import_module("review_queue"))
    finally:
        sys.path.pop(0)
    diff = _diff_module()

    result = {
        "needs_review": [
            {
                "version": "2.1.300",
                "bullet": THINKING_2_1_300,
                "reason": "THINKING is no setting on always-thinking models",
            },
            {"version": "2.1.300", "bullet": ""},
        ]
    }
    from_opus = updater.needs_review_items(result)
    assert len(from_opus) == 1
    from_validator = diff.review_items([("2.1.300", THINKING_2_1_300)])
    assert from_opus[0][0] == from_validator[0][0]

    queue = tmp_path / "review.json"
    queue_mod.add(from_opus, queue)
    queue_mod.add(from_validator, queue)
    items = queue_mod.load(queue)
    assert len(items) == 1
    assert "always-thinking" in items[0]["body"] and "contract change" in items[0]["body"]
    assert updater.needs_review_items({"needs_review": "nope"}) == []


def test_review_queue_emits_title_and_body_files(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "update"))
    try:
        import importlib

        queue_mod = importlib.reload(importlib.import_module("review_queue"))
    finally:
        sys.path.pop(0)
    queue = tmp_path / "review.json"
    assert queue_mod.emit(tmp_path / "none", queue) == 0
    title = "chore(x): " + "word " * 80
    assert queue_mod.add([(title, "body $(rm -rf /) `x`")], queue) == 1
    assert queue_mod.emit(tmp_path / "out", queue) == 1
    written = (tmp_path / "out" / "001.title").read_text().strip()
    assert "\n" not in written and len(written) <= queue_mod.TITLE_LIMIT
    body = (tmp_path / "out" / "001.body").read_text()
    assert "body $(rm -rf /) `x`" in body and "update-claude-code.yml" in body


def test_workflow_routes_review_items_instead_of_failing() -> None:
    """The cron wiring for #1149 and the shrink / always-thinks warnings."""
    text = (REPO_ROOT / ".github" / "workflows" / "update-claude-code.yml").read_text()
    queue = "update/.cache/claude-code-review.json"
    assert "--baseline update/claude-code-effort.json" in text
    assert text.count(f"--review-queue {queue}") == 3  # extractor, diff, conformance
    assert f"python update/review_queue.py --queue {queue}" in text
    route = text.split("- name: Route review items to issues", 1)[1].split("- name:", 1)[0]
    assert "--body-file" in route and "grep -Fqx" in route and "!cancelled()" in route


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
