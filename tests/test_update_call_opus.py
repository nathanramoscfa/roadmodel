# tests/test_update_call_opus.py
"""Tests for update/update_models.py::call_opus turn completion.

The catalog cron failed every day from 2026-08-21 to 2026-09-04 with
"Model did not return valid JSON", because `call_opus` returned the text of
an UNFINISHED turn and left the parser to report the symptom. With the
web_search server tool enabled the API runs its own sampling loop and hands
back `stop_reason: "pause_turn"` — a partial answer, no exception — when that
loop hits its iteration limit. The selector pass ended mid-output, at
"```json\\n{".

These tests pin the three terminal cases:
- `pause_turn` is resumed (conversation re-sent with the paused assistant turn
  appended, no synthetic "Continue." user message) and the text concatenated;
- `max_tokens` raises instead of returning a truncated answer;
- a turn that never converges raises rather than looping forever.

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

import update_models  # noqa: E402

# Reach through the module for every symbol rather than binding it at import
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
    monkeypatch.setattr(update_models, "Anthropic", lambda api_key: client)
    # The real filter is `isinstance(block, TextBlock)`; point it at the fake.
    monkeypatch.setattr(update_models, "TextBlock", _FakeTextBlock)
    return client


def test_resumes_a_paused_turn_and_concatenates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(
        monkeypatch,
        [('```json\n{"roadmodel_txt": "a', "pause_turn"), ('bc"}\n```', "end_turn")],
    )

    raw = update_models.call_opus("sys", "user", "key")

    assert raw == '```json\n{"roadmodel_txt": "abc"}\n```'
    assert len(client.messages.calls) == 2, "paused turn was not resumed"

    # The resume re-sends the conversation with the paused assistant turn
    # appended — and no synthetic "Continue." user message, which would stop
    # the server from picking up its own tool loop.
    resumed = client.messages.calls[1]["messages"]
    assert [m["role"] for m in resumed] == ["user", "assistant"]
    assert resumed[0]["content"] == "user"


def test_truncated_output_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [('{"roadmodel_txt": "half a fi', "max_tokens")])

    with pytest.raises(update_models.OpusTurnIncomplete, match="max_tokens"):
        update_models.call_opus("sys", "user", "key")


def test_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [("", "refusal")])

    with pytest.raises(update_models.OpusTurnIncomplete, match="refused"):
        update_models.call_opus("sys", "user", "key")


def test_never_converging_pause_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(
        monkeypatch,
        [("chunk", "pause_turn")] * (update_models.MAX_TURN_CONTINUATIONS + 1),
    )

    with pytest.raises(update_models.OpusTurnIncomplete, match="still paused"):
        update_models.call_opus("sys", "user", "key")

    assert len(client.messages.calls) == update_models.MAX_TURN_CONTINUATIONS + 1


def test_max_tokens_within_the_model_ceiling() -> None:
    # Opus 4.7 accepts up to 128K output tokens, and the selector payload alone
    # is ~41k. A ceiling below the payload is the truncation bug by another
    # route, so pin the floor as well as the model's hard cap.
    assert 64000 < update_models.MAX_TOKENS <= 128000


def test_fake_client_matches_the_real_sdk() -> None:
    """Contract check: the fake must mirror the SDK surface call_opus uses."""
    import inspect

    from anthropic import Anthropic
    from anthropic.types import Message, TextBlock

    # call_opus constructs with a keyword api_key and calls .messages.stream.
    assert "api_key" in inspect.signature(Anthropic.__init__).parameters
    assert callable(getattr(Anthropic(api_key="x").messages, "stream", None))

    # Every attribute the resume loop reads must exist on the real Message.
    for field in ("content", "stop_reason", "usage"):
        assert field in Message.model_fields, f"SDK Message lost .{field}"
    assert "output_tokens" in Message.model_fields["usage"].annotation.model_fields
    assert "text" in TextBlock.model_fields
