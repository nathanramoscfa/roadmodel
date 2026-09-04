# tests/test_opus_turn.py
"""Tests for update/opus_turn.py — "the turn actually finished".

Two crons failed for weeks with "Model did not return valid JSON" while the
real problem was that Opus never got to finish: the catalog refresh from
2026-08-21 (its selector pass measured 66,690 output tokens against a 64,000
ceiling) and the Claude Code refresh, which carried the same ceiling and the
same missing `stop_reason` check.

These tests pin the terminal cases:
- a completed turn returns its text;
- `max_tokens` raises instead of returning a truncated answer;
- `refusal` raises;
- `pause_turn` (server-tool loops only) is resumed by re-sending the
  conversation with the paused turn appended, and never with a synthetic
  "Continue." user message;
- a turn that never converges is bounded rather than looping forever.

Per memory `feedback_monkeypatched_contract_validation`, the fake client is
checked against the real SDK's signature and response attributes so a future
SDK change fails loudly rather than letting the fake drift.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import opus_turn  # noqa: E402
import update_models  # noqa: E402

# Reach through the modules for every symbol rather than binding it at import
# time: tests/test_annual_carry_forward.py reloads update_models, which rebinds
# its classes, and a module-level `from ... import OpusTurnIncomplete` would
# then hold a stale class object that `pytest.raises` no longer matches.


class _FakeTextBlock:
    """Matches the SDK's TextBlock closely enough for the isinstance filter."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeUsage:
    def __init__(self, output_tokens: int) -> None:
        self.output_tokens = output_tokens


class _FakeMessage:
    def __init__(self, text: str, stop_reason: str) -> None:
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(len(text))


class _FakeStream:
    def __init__(self, message: _FakeMessage) -> None:
        self._message = message

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> _FakeMessage:
        return self._message


class _FakeMessages:
    def __init__(self, script: list[tuple[str, str]]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        text, stop_reason = self._script.pop(0)
        return _FakeStream(_FakeMessage(text, stop_reason))


class _FakeClient:
    def __init__(self, script: list[tuple[str, str]]) -> None:
        self.messages = _FakeMessages(script)


def _install(monkeypatch: pytest.MonkeyPatch, script: list[tuple[str, str]]) -> _FakeClient:
    client = _FakeClient(script)
    # The real filter is `isinstance(block, TextBlock)`; point it at the fake.
    monkeypatch.setattr(opus_turn, "TextBlock", _FakeTextBlock)
    return client


def _run(client: _FakeClient, **overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "model": "claude-opus-4-7",
        "max_tokens": 128000,
        "system": [{"type": "text", "text": "sys"}],
        "user_message": "user",
    }
    kwargs.update(overrides)
    return opus_turn.stream_until_complete(client, **kwargs)


def test_completed_turn_returns_its_text(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, [('{"roadmodel_txt": "abc"}', "end_turn")])

    assert _run(client) == '{"roadmodel_txt": "abc"}'
    assert len(client.messages.calls) == 1
    # No tools unless the caller asks for them — the trackers pass none.
    assert "tools" not in client.messages.calls[0]


def test_resumes_a_paused_turn_and_concatenates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(
        monkeypatch,
        [('```json\n{"roadmodel_txt": "a', "pause_turn"), ('bc"}\n```', "end_turn")],
    )

    raw = _run(client, tools=[{"type": "web_search_20250305", "name": "web_search"}])

    assert raw == '```json\n{"roadmodel_txt": "abc"}\n```'
    assert len(client.messages.calls) == 2, "paused turn was not resumed"

    # The resume re-sends the conversation with the paused assistant turn
    # appended — and no synthetic "Continue." user message, which would stop
    # the server from picking up its own tool loop.
    resumed = client.messages.calls[1]["messages"]
    assert [m["role"] for m in resumed] == ["user", "assistant"]
    assert resumed[0]["content"] == "user"


def test_truncated_output_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, [('{"roadmodel_txt": "half a fi', "max_tokens")])

    with pytest.raises(opus_turn.OpusTurnIncomplete, match="max_tokens"):
        _run(client)


def test_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, [("", "refusal")])

    with pytest.raises(opus_turn.OpusTurnIncomplete, match="refused"):
        _run(client)


def test_never_converging_pause_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(
        monkeypatch,
        [("chunk", "pause_turn")] * (opus_turn.MAX_TURN_CONTINUATIONS + 1),
    )

    with pytest.raises(opus_turn.OpusTurnIncomplete, match="still paused"):
        _run(client)

    assert len(client.messages.calls) == opus_turn.MAX_TURN_CONTINUATIONS + 1


def test_ceiling_clears_the_measured_payload() -> None:
    # The selector pass measured 66,690 output tokens on 2026-09-04 — the run
    # that proved the old 64,000 ceiling was the bug. Opus 4.7's hard cap is
    # 128,000, so pin the floor above what we have actually seen as well as
    # the model's limit.
    assert 66_690 < opus_turn.MAX_OUTPUT_TOKENS <= 128_000


def test_every_cron_uses_the_shared_ceiling() -> None:
    """No cron may quietly carry its own smaller ceiling.

    update_claude_code.py kept `MAX_TOKENS = 64000` after the catalog cron was
    fixed, and failed the same way on the next run.
    """
    import importlib

    for name in (
        "update_models",
        "update_claude_code",
        "update_codex",
        "update_gemini",
        "update_deepseek",
    ):
        mod = importlib.import_module(name)
        assert mod.MAX_TOKENS == opus_turn.MAX_OUTPUT_TOKENS, (
            f"{name}.MAX_TOKENS is {mod.MAX_TOKENS}, not the shared "
            f"{opus_turn.MAX_OUTPUT_TOKENS} — that is the truncation bug again"
        )


def test_catalog_caller_delegates_with_web_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """update_models.call_opus must go through the shared helper, with tools."""
    client = _FakeClient([('{"roadmodel_txt": "x"}', "end_turn")])
    monkeypatch.setattr(update_models, "Anthropic", lambda api_key: client)
    monkeypatch.setattr(opus_turn, "TextBlock", _FakeTextBlock)

    assert update_models.call_opus("sys", "user", "key") == '{"roadmodel_txt": "x"}'

    sent = client.messages.calls[0]
    assert sent["max_tokens"] == opus_turn.MAX_OUTPUT_TOKENS
    assert sent["tools"][0]["name"] == "web_search"
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_fake_client_matches_the_real_sdk() -> None:
    """Contract check: the fake must mirror the SDK surface the helper uses."""
    import inspect

    from anthropic import Anthropic
    from anthropic.types import Message, TextBlock

    # Callers construct with a keyword api_key and call .messages.stream.
    assert "api_key" in inspect.signature(Anthropic.__init__).parameters
    assert callable(getattr(Anthropic(api_key="x").messages, "stream", None))

    # Every attribute the resume loop reads must exist on the real Message.
    for field in ("content", "stop_reason", "usage"):
        assert field in Message.model_fields, f"SDK Message lost .{field}"
    assert "output_tokens" in Message.model_fields["usage"].annotation.model_fields
    assert "text" in TextBlock.model_fields
