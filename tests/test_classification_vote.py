"""The ladder's classification: pinned, voted, or declared.

The picks come from the ladder table; the engine's one judgement is the task's
classification, which picks the row, and at its reasoning floor it varies
between identical calls (Phase 4.5 soak, 2026-10-08). Maintainer decision
2026-10-08: a pinned row (from an earlier answer to the same task) holds; a new
task gets two classification votes on the same cached prompt, run in parallel
with the ladder call, and the majority row wins. The votes' tokens are folded
into the request's usage so the cost ledger stays whole.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path
from typing import Any

import pytest

from roadmodel import recommend as recommend_module
from roadmodel import usage
from roadmodel.config import Config
from roadmodel.providers import ProviderAdapter
from roadmodel.recommend import recommend_ladder

LADDER = """\
CLASSIFICATION: planning / {complexity} / routine
TIER: QUALITY
MODEL: Opus
BACKUP: Luna
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Planning. PICK: Opus fits. EFFORT: XHigh suits it.

TIER: BALANCED
MODEL: Sonnet
BACKUP: Luna
PLATFORM: Claude Code
EFFORT: High
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Planning. PICK: Sonnet fits. EFFORT: High suits it.

TIER: COST
MODEL: Luna
BACKUP: Sonnet
PLATFORM: Codex
EFFORT: Medium
CONVERSATION: New
RATIONALE: TASK: Planning. PICK: Luna fits. EFFORT: Medium suits it.
"""


class FakeAdapter:
    """Answers the ladder call with ``main`` and each vote with the next of
    ``votes`` (an Exception raises), recording 100 input / 10 output tokens a call."""

    def __init__(self, main: str, votes: list[str | Exception]) -> None:
        self.main = main
        self.votes = list(votes)
        self.calls: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def recommend(
        self,
        prompt: str,
        system: str,
        *,
        model: str | None = None,
        api_key: str,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> str:
        is_vote = "return ONLY the `CLASSIFICATION:` line" in prompt
        with self.lock:
            self.calls.append({"prompt": prompt, "cap": max_output_tokens, "vote": is_vote})
            answer: str | Exception = self.votes.pop(0) if is_vote else self.main
        usage.record("fake", "m", input_tokens=100, output_tokens=10, cached_input_tokens=90)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _line(complexity: str) -> str:
    return f"CLASSIFICATION: planning / {complexity} / routine"


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    adapter: FakeAdapter,
    **kw: Any,
) -> dict[str, dict[str, str]]:
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    ctx = tmp_path / "uc.md"
    ctx.write_text("# User Context\n", encoding="utf-8")
    cfg = Config(provider="anthropic", model=None, api_key="k", user_context_path=ctx)
    usage.reset()
    return recommend_ladder("plan a release", cfg, ladder_table="<ladder-table>", **kw)


def test_the_fake_adapter_matches_the_protocol() -> None:
    real = inspect.signature(ProviderAdapter.recommend)
    fake = inspect.signature(FakeAdapter.recommend)
    assert list(real.parameters) == list(fake.parameters)


def test_two_agreeing_votes_outvote_the_ladder_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = FakeAdapter(LADDER.format(complexity="low"), [_line("medium"), _line("medium")])
    parsed = _run(monkeypatch, tmp_path, adapter, classification_votes=2)
    base = parsed["quality"]
    assert base["classification"] == "planning/medium"
    assert base["classification_source"] == "vote"
    assert base["classification_votes"] == "planning/medium,planning/medium"
    votes = [c for c in adapter.calls if c["vote"]]
    assert len(votes) == 2 and all(c["cap"] == 1024 for c in votes)
    # Three calls metered as one request.
    last = usage.last()
    assert last is not None
    assert (last.input_tokens, last.cached_input_tokens, last.output_tokens) == (300, 270, 30)


def test_without_a_majority_the_ladder_calls_own_row_stands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = FakeAdapter(LADDER.format(complexity="low"), [_line("medium"), _line("high")])
    base = _run(monkeypatch, tmp_path, adapter, classification_votes=2)["cost"]
    assert base["classification"] == "planning/low"
    assert base["classification_source"] == "declared"


def test_a_vote_agreeing_with_the_ladder_call_keeps_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = FakeAdapter(LADDER.format(complexity="medium"), [_line("medium"), _line("low")])
    base = _run(monkeypatch, tmp_path, adapter, classification_votes=2)["cost"]
    assert base["classification"] == "planning/medium"
    assert base["classification_source"] == "declared"


def test_a_failed_vote_is_no_vote(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = FakeAdapter(
        LADDER.format(complexity="low"), [RuntimeError("timeout"), _line("medium")]
    )
    base = _run(monkeypatch, tmp_path, adapter, classification_votes=2)["quality"]
    assert base["classification"] == "planning/low"
    assert base["classification_votes"] == "-,planning/medium"


def test_a_pinned_row_holds_and_skips_the_votes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = FakeAdapter(LADDER.format(complexity="low"), [])
    base = _run(
        monkeypatch,
        tmp_path,
        adapter,
        pinned_classification="planning/high",
        classification_votes=2,
    )["balanced"]
    assert base["classification"] == "planning/high"
    assert base["classification_source"] == "pinned"
    assert len(adapter.calls) == 1
    assert "`CLASSIFICATION: planning / high / routine`" in adapter.calls[0]["prompt"]


def test_no_table_means_no_votes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = FakeAdapter(LADDER.format(complexity="low"), [])
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    ctx = tmp_path / "uc.md"
    ctx.write_text("# User Context\n", encoding="utf-8")
    cfg = Config(provider="anthropic", model=None, api_key="k", user_context_path=ctx)
    parsed = recommend_ladder("plan", cfg, classification_votes=2)
    assert len(adapter.calls) == 1
    assert "classification_source" not in parsed["quality"]


def test_usage_add_sums_every_count() -> None:
    usage.reset()
    usage.add([None])
    assert usage.last() is None
    usage.record("p", "m", input_tokens=10, output_tokens=2, reasoning_tokens=1)
    usage.add(
        [usage.CallUsage("p", "m", 5, 4, 0, 1, None), usage.CallUsage("p", "m", 5, 0, 0, 1, 2)]
    )
    last = usage.last()
    assert last is not None
    assert (last.input_tokens, last.cached_input_tokens, last.output_tokens) == (20, 4, 4)
    assert last.reasoning_tokens == 3
