"""Pool liveness: session-start refresh, stale-meter flags, the hook installer."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import configure_claude_pool as ccp
import ensure_pool_fresh as epf
import roll_pool_status as rps

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT

TABLE = """## Usage-pool status

| Pool | Window | State | Resets (local time) | Notes |
| ---- | ------ | ----- | ------------------- | ----- |
| claude.ai Max weekly | 7 days | `tight` | Tue 2026-10-27 20:00 EDT | n. [auto: claude 64% at 2026-10-13 10:02 EDT] |
| claude.ai Max 5h | 5 hours | `headroom` | Fri 2026-10-23 09:00 EDT | n. [auto: claude 17% at 2026-10-23 06:30 EDT] |
| Codex | 7 days | `headroom` | Tue 2026-10-27 00:58 EDT | n. [auto: codex 17% at 2026-10-23 05:00 EDT] |
| Manual | 7 days | `headroom` | rolling | never measured. |
"""


def row(text: str, name: str) -> str:
    return next(line for line in text.splitlines() if name in line)


def test_stale_rows_are_flagged_and_states_untouched() -> None:
    out = rps.mark_stale(TABLE, NOW)
    weekly = row(out, "claude.ai Max weekly")
    assert "[stale: no fresh meter since 2026-10-13 10:02 EDT; state unverified]" in weekly
    assert "`tight`" in weekly  # the flag annotates; it never rewrites a state
    assert "[stale" in row(out, "claude.ai Max 5h")  # five-hour windows go stale after one hour
    assert "[stale" not in row(out, "Codex")  # 3h old, weekly window: still fresh
    assert "[stale" not in row(out, "Manual")  # no measurement, nothing to age


def test_flag_is_idempotent_and_clears_when_fresh() -> None:
    once = rps.mark_stale(TABLE, NOW)
    assert rps.mark_stale(once, NOW) == once
    later = rps.mark_stale(once, datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc))
    assert "[stale" not in row(later, "claude.ai Max weekly")


def test_fresh_snapshot_replaces_the_stale_flag() -> None:
    flagged = rps.mark_stale(TABLE, NOW)
    snap = {
        "claude": dict(
            source="claude",
            observed_at=NOW.timestamp() - 60,
            windows=[
                dict(
                    name="weekly",
                    used_percent=40.0,
                    resets_at=NOW.timestamp() + 4 * 86400,
                    window_minutes=10080.0,
                )
            ],
            extra={},
        )
    }
    out, _ = rps.roll(flagged, NOW, snap)
    assert "[stale" not in row(out, "claude.ai Max weekly") and "[auto: claude 40%" in row(
        out, "claude.ai Max weekly"
    )


def test_ensure_is_silent_when_fresh_and_refreshes_when_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spawned: list[Path] = []
    monkeypatch.setattr(epf, "start_refresh", lambda cache, now: spawned.append(cache) or True)
    monkeypatch.setattr(epf, "launchd_problem", lambda: None)
    (tmp_path / "claude.json").write_text(json.dumps({"observed_at": 1e12}))
    now = 1e12 + 60
    monkeypatch.setattr(epf.time, "time", lambda: now)
    assert epf.main(["--cache", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "" and not spawned
    (tmp_path / "claude.json").write_text(json.dumps({"observed_at": now - 13 * 86400}))
    epf.main(["--cache", str(tmp_path)])
    out = capsys.readouterr().out
    assert spawned and "last measured 13d ago" in out and "background refresh" in out


def test_missing_snapshot_counts_as_stale_and_launchd_problem_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(epf, "start_refresh", lambda cache, now: False)
    monkeypatch.setattr(epf, "launchd_problem", lambda: "disabled in launchd")
    epf.main(["--cache", str(tmp_path)])
    out = capsys.readouterr().out
    assert "never measured" in out and "started moments ago" in out
    assert "hourly pool agent is disabled in launchd" in out


def test_refresh_is_throttled_across_concurrent_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    popen: list[list[str]] = []
    monkeypatch.setattr(epf.subprocess, "Popen", lambda argv, **kw: popen.append(argv))
    assert epf.start_refresh(tmp_path, 1000.0) is True
    assert epf.start_refresh(tmp_path, 1000.0 + epf.THROTTLE - 1) is False
    assert epf.start_refresh(tmp_path, 1000.0 + epf.THROTTLE + 1) is True
    assert len(popen) == 2 and popen[0][-2:] == [
        str(Path(epf.__file__).with_name("private_job.py")),
        "pools",
    ]
    assert (os.stat(tmp_path / ".ensure-refresh").st_mode & 0o777) == 0o600


def test_hook_install_adds_one_entry_keeps_others_and_is_idempotent() -> None:
    other = {"hooks": [{"type": "command", "command": "echo hi"}]}
    settings = {"model": "x", "hooks": {"SessionStart": [other], "Stop": [other]}}
    once = ccp.hook_configuration(settings)
    entries = once["hooks"]["SessionStart"]
    assert entries[0] == other and len(entries) == 2 and once["hooks"]["Stop"] == [other]
    assert "ensure_pool_fresh.py" in entries[1]["hooks"][0]["command"] and once["model"] == "x"
    assert ccp.hook_configuration(once) == once
    assert "hooks" not in settings or settings["hooks"]["SessionStart"] == [
        other
    ]  # input untouched


def test_overlapping_refresh_is_skipped_cleanly(tmp_path: Path) -> None:
    first = rps.single_run(tmp_path)
    assert first is not None
    assert rps.single_run(tmp_path) is None  # a second run sees the first
    first.close()
    again = rps.single_run(tmp_path)
    assert again is not None
    again.close()


def test_main_exits_zero_when_another_run_holds_the_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = tmp_path / "user-context.md"
    context.write_text("# Ctx\n")
    held = rps.single_run(tmp_path)
    try:
        code = rps.main(["--file", str(context), "--cache", str(tmp_path), "--no-collect"])
    finally:
        held.close()
    assert code == 0 and "another refresh is running" in capsys.readouterr().out
