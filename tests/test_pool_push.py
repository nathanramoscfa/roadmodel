"""Only fresh allowlisted observations can replace a saved user's pool state."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import push_pool_status as push
from app import pools

NOW = 1_800_000_000


def row(pool="claude:weekly", state="exhausted", age=0, **extra):
    minutes = pools.POOLS[pool][2]
    return dict(
        pool=pool,
        state=state,
        observed_at=NOW - age,
        used_percent=98,
        window_minutes=minutes,
        resets_at=None if minutes == 0 else NOW + 600,
        **extra,
    )


@pytest.mark.parametrize("bad", [None, {}, [None], [{"pool": []}], [row(state=[])]])
def test_invalid_container_preserves_saved_exhaustion(bad):
    old = pools.normalize([row()], NOW)
    assert pools.merge(old, bad, NOW) == old


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": NOW + 1},
        {"used_percent": float("nan")},
        {"used_percent": True},
        {"pool": "fable:sub-cap"},
        {"resets_at": "2026"},
        {"window_minutes": 5},
    ],
)
def test_invalid_values_cannot_clear_state(changes):
    old = pools.normalize([row()], NOW)
    candidate = {**row(state="headroom"), **changes}
    assert pools.merge(old, [candidate], NOW) == old


def test_old_missing_and_replayed_data_does_not_clear_a_live_pool():
    old = pools.normalize([row(age=100)], NOW)
    for incoming in (
        [],
        [row(state="headroom", age=100)],
        [row(state="headroom", age=101)],
        [row(state="headroom", age=21601)],
    ):
        assert pools.merge(old, incoming, NOW) == old
    assert pools.merge(old, [row(state="headroom")], NOW)[0]["state"] == "headroom"


def test_short_window_ttl_and_fixed_credits():
    old = pools.normalize([row("codex:5h", age=4000)], NOW)
    assert pools.merge(old, [row("codex:5h", "headroom", age=3601)], NOW) == old
    credits = pools.normalize([row("openrouter:credits", age=100000)], NOW)
    assert pools.states(credits, NOW)["openrouter"] == "exhausted"
    assert pools.states([{**row(), "resets_at": NOW - 1}], NOW) == {}  # malformed at observation
    expired = row(age=1000)
    expired["resets_at"] = NOW - 1
    assert pools.states([expired], NOW)["claude-code"] == "headroom"


def test_no_raw_fields_or_account_identity_reach_the_profile():
    raw = row(api_key="not-a-key", account="example@example.invalid", transcript="private")
    clean = json.dumps(pools.normalize([raw], NOW))
    assert all(secret not in clean for secret in ("not-a-key", "example@", "private"))


def test_collectors_export_only_fresh_complete_observations():
    snapshot = dict(
        source="claude",
        observed_at=NOW,
        extra={},
        windows=[dict(name="weekly", used_percent=98, window_minutes=10080, resets_at=NOW + 600)],
    )
    exported = push.observations({"claude": snapshot}, NOW)
    assert exported[0]["state"] == "exhausted"
    assert push.observations({"claude": snapshot}, NOW + 21601) == []
    agy = {**snapshot, "source": "antigravity", "windows": snapshot["windows"] + [{}]}
    assert push.observations({"antigravity": agy}, NOW) == []


def test_push_patches_only_pools_and_retries_concurrent_settings_save(monkeypatch):
    calls = []
    reads = iter(["first", "second"])

    def fake(url, public_key, token=None, body=None, method=None):
        calls.append((url, body, method))
        if method is None:
            return [{"pool_states": [], "updated_at": next(reads)}]
        return [] if len(calls) == 2 else [{"pool_states": body["pool_states"]}]

    import inspect

    assert list(inspect.signature(fake).parameters) == list(
        inspect.signature(push.request).parameters
    )
    monkeypatch.setattr(push, "request", fake)
    assert (
        push.push([row()], ("https://example.supabase.co", "public", "user-session", "own-id"), NOW)
        == 1
    )
    assert "updated_at=eq.second" in calls[-1][0]
    assert set(calls[-1][1]) == {"pool_states"}
    assert "user_id=eq.own-id" in calls[-1][0]


def test_rejects_admin_key_before_any_refresh_request(monkeypatch):
    import base64

    admin = "header." + base64.urlsafe_b64encode(b'{"role":"service_role"}').decode() + ".signature"
    monkeypatch.setattr(
        push,
        "keychain",
        lambda service: "https://example.supabase.co" if service.endswith("URL") else admin,
    )
    monkeypatch.setattr(push, "request", lambda *a, **k: pytest.fail("must not send admin key"))
    with pytest.raises(ValueError, match="publishable"):
        push.credentials("user-refresh")
