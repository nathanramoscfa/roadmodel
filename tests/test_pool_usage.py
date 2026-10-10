"""Meter decisions and collectors: boundaries, freshness, schemas and privacy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_antigravity_pool import log_error, parse_panel
from collect_claude_pool import collect as claude
from collect_codex_pool import collect as codex
from collect_openrouter_pool import collect as openrouter
from pool_table import render
from pool_usage import WEEK, decide, load, save

NOW = 1791648000.0


def snap(used=20, elapsed=24 * 3600, minutes=WEEK, age=0, source="claude"):
    meter = dict(
        name="weekly" if minutes == WEEK else "5h",
        used_percent=used,
        resets_at=NOW - elapsed + minutes * 60,
        window_minutes=minutes,
    )
    return dict(source=source, observed_at=NOW - age, windows=[meter], extra={}), meter


@pytest.mark.parametrize(
    "used,elapsed,expected",
    [
        (97, 3600, "exhausted"),
        (100, 3600, "exhausted"),
        (96.9, 3600, "tight"),
        (7, 11 * 3600, "headroom"),
        (8, 12 * 3600, "tight"),
        (7, 12 * 3600, "headroom"),
        (85, 5 * 86400, "tight"),
        (84, 6 * 86400, "headroom"),
        (85, 6 * 86400, "headroom"),
        (0, 0, "headroom"),
    ],
)
def test_weekly_rules(used, elapsed, expected):
    snapshot, meter = snap(used, elapsed)
    assert decide(snapshot, meter, NOW) == expected


@pytest.mark.parametrize(
    "minutes,age,expected",
    [(WEEK, 21600, "tight"), (WEEK, 21601, None), (300, 3600, "tight"), (300, 3601, None)],
)
def test_freshness(minutes, age, expected):
    snapshot, meter = snap(20, 24 * 3600 if minutes == WEEK else 2 * 3600, minutes, age)
    assert decide(snapshot, meter, NOW) == expected


def test_pace_is_evaluated_at_observation():
    snapshot, meter = snap(10, 20 * 3600, age=4 * 3600)
    assert decide(snapshot, meter, NOW) == "tight"  # 10% at 16h, not at 20h.


@pytest.mark.parametrize(
    "field,value",
    [
        ("used_percent", -1),
        ("used_percent", float("nan")),
        ("used_percent", 101),
        ("used_percent", True),
        ("resets_at", None),
        ("window_minutes", 0),
    ],
)
def test_bad_meter_keeps_state(field, value):
    snapshot, meter = snap()
    meter[field] = value
    assert decide(snapshot, meter, NOW) is None


def test_future_missing_and_reset_data_keeps_state():
    snapshot, meter = snap(elapsed=WEEK * 60)
    assert decide(snapshot, meter, NOW) is None
    snapshot, meter = snap(age=-1)
    assert decide(snapshot, meter, NOW) is None
    assert decide({}, None, NOW) is None


def test_quota_error_and_short_window_pace():
    snapshot, meter = snap(10, 60, 300)
    assert decide(snapshot, meter, NOW) == "tight"
    snapshot["extra"]["rate_limit_reached"] = True
    assert decide(snapshot, meter, NOW) == "exhausted"
    snapshot["extra"] = {}
    meter["quota_error"] = True
    assert decide(snapshot, meter, NOW) == "exhausted"


@pytest.mark.parametrize(
    "remaining,expected",
    [
        (0, "exhausted"),
        (0.99, "exhausted"),
        (1, "tight"),
        (9.99, "tight"),
        (10, "headroom"),
        (50, "headroom"),
    ],
)
def test_openrouter_thresholds(remaining, expected):
    snapshot = dict(
        source="openrouter",
        observed_at=NOW,
        windows=[],
        extra={"limit": 50, "limit_remaining": remaining},
    )
    assert decide(snapshot, None, NOW) == expected
    snapshot["observed_at"] -= 21601
    assert decide(snapshot, None, NOW) is None


def test_atomic_snapshot_and_allowlisted_collectors(tmp_path):
    data = claude(
        {
            "rate_limits": {"seven_day": {"used_percentage": 42, "resets_at": NOW + 86400}},
            "secret": "private",
        },
        NOW,
    )
    assert data and len(data["windows"]) == 1
    save(data, tmp_path)
    assert load(tmp_path)["claude"] == data
    assert os.stat(tmp_path / "claude.json").st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [tmp_path / "claude.json"]
    assert claude({}, NOW) is None
    response = {
        "data": {
            "label": "private",
            "key": "private",
            "limit": 50,
            "limit_remaining": 40,
            "usage": 10,
        }
    }
    assert "private" not in json.dumps(openrouter(response, NOW))


def test_codex_newest_event_not_newest_file_and_slot_independence(tmp_path):
    def event(at, primary, secondary=None):
        return (
            json.dumps(
                dict(
                    timestamp=at,
                    payload=dict(rate_limits=dict(primary=primary, secondary=secondary)),
                )
            )
            + "\n"
        )

    week = dict(used_percent=42, resets_at=NOW + 86400, window_minutes=WEEK)
    short = dict(used_percent=5, resets_at=NOW + 3600, window_minutes=300)
    (tmp_path / "rollout-1.jsonl").write_text(
        event("2026-10-10T10:00:00Z", short, week) + "{partial"
    )
    (tmp_path / "rollout-2.jsonl").write_text(event("2026-10-09T10:00:00Z", week))
    data = codex(tmp_path)
    assert data and [w["name"] for w in data["windows"]] == ["5h", "weekly"]
    assert data["windows"][1]["used_percent"] == 42


PANEL = """GEMINI MODELS
Weekly Limit Remaining
[████] 75.00%
Refreshes in 120h 2m
CLAUDE AND GPT MODELS
Weekly Limit Remaining
[████] 100.00%
Quota available
"""


def test_supported_antigravity_groups_and_unknown_reset():
    data = parse_panel(PANEL, NOW)
    assert data and data["windows"][0]["used_percent"] == 25
    assert data["windows"][0]["window_minutes"] == WEEK
    assert data["windows"][0]["resets_at"] == NOW + (120 * 60 + 3) * 60
    assert decide(data, data["windows"][1], NOW) == "headroom"
    assert parse_panel(PANEL.split("CLAUDE")[0], NOW) is None


def test_quota_fallback_never_renews_error_timestamp_or_infers_headroom(tmp_path):
    (tmp_path / "one.log").write_text("2026-10-10T10:00:00Z INFO quota_manager doRefreshQuota\n")
    assert log_error(tmp_path) is None
    (tmp_path / "two.log").write_text("2026-10-10T10:00:00Z ERROR RESOURCE_EXHAUSTED\n")
    data = log_error(tmp_path)
    assert data and data["windows"][0]["resets_at"] == data["observed_at"] + 5 * 3600
    assert decide(data, data["windows"][0], data["observed_at"]) == "exhausted"
    assert decide(data, data["windows"][0], data["observed_at"] + 3601) is None
    (tmp_path / "quotes.jsonl").write_text(
        json.dumps({"timestamp": "2026-10-11T10:00:00Z", "content": "429 quota error"}) + "\n"
    )
    assert log_error(tmp_path) == data


def test_wrapper_preserves_input_output_and_caches_even_if_original_fails(tmp_path):
    original = tmp_path / "original.json"
    original.write_text(json.dumps({"type": "command", "command": "cat; exit 7", "padding": 3}))
    raw = b'{"rate_limits":{"five_hour":{"used_percentage":12,"resets_at":1792000000}},"message":"original"}'
    script = Path(__file__).resolve().parents[1] / "scripts/collect_claude_pool.py"
    result = subprocess.run(
        [sys.executable, str(script), "--original", str(original), "--cache", str(tmp_path)],
        input=raw,
        capture_output=True,
    )
    assert result.stdout == raw and result.returncode == 7
    assert (tmp_path / "claude.json").exists()


TABLE = """## Usage-pool status

| Pool | Window | State | Resets | Notes |
| ---- | ------ | ----- | ------ | ----- |
| claude.ai Max — weekly | 7 days | `exhausted` | rolling | overflow |
| claude.ai Max — Fable sub-cap | 7 days | `tight` | rolling | manual |
| ChatGPT Pro — Codex 5h / weekly | 5h / 7d | `headroom` | rolling | spare |
| Google AI Pro — Antigravity | 5h / 7d | `exhausted` | rolling | separate |

## Other
untouched
"""


def test_preview_stale_missing_and_manual_rows_unchanged():
    snapshot, _ = snap(age=21601)
    assert render(TABLE, {"claude": snapshot}, NOW) == TABLE
    assert render(TABLE, {}, NOW) == TABLE


def test_preview_fresh_downgrade_idempotence_and_split_codex():
    snapshot, _ = snap(7, 24 * 3600)
    cdx, meter = snap(15, 24 * 3600, source="codex")
    cdx["windows"].append(dict(name="5h", used_percent=5, resets_at=NOW + 3600, window_minutes=300))
    result = render(TABLE, {"claude": snapshot, "codex": cdx}, NOW)
    assert "| `headroom` |" in result.split("weekly |")[1]
    assert "Fable sub-cap | 7 days | `tight` | rolling | manual" in result
    assert "| Codex — 5h | 5 hours |" in result
    assert "[auto: claude 7% at " in result
    assert render(result, {"claude": snapshot, "codex": cdx}, NOW) == result
    assert result.endswith("## Other\nuntouched\n")


def test_grouped_pool_cannot_lower_with_one_stale_or_missing_window():
    data = parse_panel(PANEL, NOW)
    assert data
    data["windows"].append({"name": "missing"})
    result = render(TABLE, {"antigravity": data}, NOW)
    assert "| Google AI Pro — Antigravity | 5h / 7d | `exhausted` | rolling | separate |" in result
