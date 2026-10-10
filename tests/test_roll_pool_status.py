"""scripts/roll_pool_status.py: expired Usage-pool rows are tidied, live ones kept."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "roll_pool_status", REPO_ROOT / "scripts" / "roll_pool_status.py"
)
assert _spec is not None and _spec.loader is not None
rps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rps)

TABLE = """# Ctx

## Usage-pool status

| Pool | Window | State | Resets (local time) | Notes |
| ---- | ------ | ----- | ------------------- | ----- |
| Max weekly | 7 days | `tight` | Tue 2026-10-06 20:00 EDT | hit 95%. |
| Max 5h | 5 hours | `headroom` | rolling | fine. |
| Codex | 5h / 7d | `exhausted` | rolling | undated stays. |
| Odd zone | 7 days | `exhausted` | Tue 2026-10-06 20:00 XYZ | unknown zone stays. |

## Other

| Pool | Window | State | Resets | Notes |
| x | 7 days | `tight` | Tue 2026-10-06 20:00 EDT | outside the section. |
"""

AFTER = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)  # 21:00 EDT, past the reset
BEFORE = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)  # 19:00 EDT


def test_expired_row_flips_to_headroom_and_rolls_a_week() -> None:
    new, summary = rps.roll(TABLE, AFTER)
    row = next(line for line in new.split("\n") if line.startswith("| Max weekly"))
    assert "`headroom`" in row and "`tight`" not in row
    assert "Tue 2026-10-13 20:00 EDT" in row
    assert "[auto: reset to headroom 2026-10-06]" in row
    assert len(summary) == 1


def test_live_unknown_undated_and_out_of_section_rows_are_untouched() -> None:
    new, _ = rps.roll(TABLE, AFTER)
    for name in ("Max 5h", "Codex", "Odd zone", "x"):
        old = next(line for line in TABLE.split("\n") if line.startswith(f"| {name} "))
        assert old in new.split("\n")


def test_before_the_reset_nothing_changes() -> None:
    new, summary = rps.roll(TABLE, BEFORE)
    assert new == TABLE and summary == []


def test_idempotent_and_marker_not_stacked() -> None:
    once, _ = rps.roll(TABLE, AFTER)
    twice, summary = rps.roll(once, AFTER)
    assert twice == once and summary == []


def test_stale_headroom_row_gets_date_rolled_without_state_change() -> None:
    text = TABLE.replace("`tight` | Tue 2026-10-06", "`headroom` | Tue 2026-09-29", 1)
    new, _ = rps.roll(text, AFTER)
    row = next(line for line in new.split("\n") if line.startswith("| Max weekly"))
    assert "`headroom`" in row and "Tue 2026-10-13 20:00 EDT" in row
    assert "[auto:" not in row


def test_fresh_exhaustion_overrides_an_old_passed_reset() -> None:
    now = AFTER.timestamp()
    snapshot = dict(
        source="claude",
        observed_at=now,
        windows=[dict(name="weekly", used_percent=99, resets_at=now + 86400, window_minutes=10080)],
        extra={},
    )
    text = TABLE.replace("Max weekly", "claude.ai Max weekly")
    new, _ = rps.roll(text, AFTER, {"claude": snapshot})
    row = next(line for line in new.splitlines() if "claude.ai Max weekly" in line)
    assert "`exhausted`" in row and "[auto: claude 99%" in row


def test_atomic_write_preserves_permissions_and_detects_concurrent_edit(tmp_path) -> None:
    path = tmp_path / "context.md"
    path.write_text("before")
    path.chmod(0o600)
    rps.write_context(path, "before", "after")
    assert path.read_text() == "after"
    assert path.stat().st_mode & 0o777 == 0o600
    import pytest

    with pytest.raises(RuntimeError, match="context changed"):
        rps.write_context(path, "before", "lost edit")
    assert path.read_text() == "after"
    assert list(tmp_path.iterdir()) == [path]


def test_cli_dry_run_keeps_file_and_default_symlink_target(tmp_path) -> None:
    import json
    import subprocess
    import sys

    path = tmp_path / "context.md"
    text = TABLE.replace("Max weekly", "claude.ai Max weekly")
    path.write_text(text)
    path.chmod(0o600)
    link = tmp_path / "symlink.md"
    link.symlink_to(path)
    cache = tmp_path / "cache"
    cache.mkdir()
    from time import time

    now = time()
    (cache / "claude.json").write_text(
        json.dumps(
            dict(
                source="claude",
                observed_at=now,
                windows=[
                    dict(
                        name="weekly", used_percent=99, resets_at=now + 86400, window_minutes=10080
                    )
                ],
                extra={},
            )
        )
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/roll_pool_status.py"),
        "--file",
        str(link),
        "--cache",
        str(cache),
        "--no-collect",
    ]
    result = subprocess.run(command + ["--dry-run"], check=True, capture_output=True, text=True)
    assert "[auto: claude 99%" in result.stdout
    assert path.read_text() == text and link.is_symlink()
    subprocess.run(command, check=True, capture_output=True)
    assert "[auto: claude 99%" in path.read_text() and link.is_symlink()
    assert path.stat().st_mode & 0o777 == 0o600
