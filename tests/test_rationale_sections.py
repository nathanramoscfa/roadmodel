"""Structured rationale (task / pick / run) for the /recommend redesign.

The selector emits its RATIONALE as three labelled segments — "TASK: ... PICK:
... RUN: ..." — so the web "Why this model?" panel can render sub-headings.
``_split_rationale_sections`` parses them BEST-EFFORT off the already-captured
rationale string; ``recommend_structured`` attaches them as ``rationale_sections``
only when all three are present, else omits the key so the web edge falls back to
the raw string.

The load-bearing property: a non-conforming rationale must NEVER fail a
recommendation — it just yields no sections. The single RATIONALE field stays
required and its regex/`_REQUIRED_KEYS` are unchanged, so this is purely additive
(the Gemini instruction-adherence safety net — see the #185-190 work).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel import recommend as recommend_module  # noqa: E402
from roadmodel.config import Config  # noqa: E402
from roadmodel.recommend import _split_rationale_sections  # noqa: E402

# --- _split_rationale_sections (pure) ---------------------------------------


def test_full_labelled_rationale_splits_into_three() -> None:
    raw = (
        "TASK: Multi-file refactor of a Python service. "
        "PICK: Opus 4.8 is S-tier for coding and leads SWE-bench Verified. "
        "RUN: Claude Code at Max effort, funded by Claude Max; conversation New."
    )
    assert _split_rationale_sections(raw) == {
        "task": "Multi-file refactor of a Python service.",
        "pick": "Opus 4.8 is S-tier for coding and leads SWE-bench Verified.",
        "run": "Claude Code at Max effort, funded by Claude Max; conversation New.",
    }


def test_labelled_rationale_split_across_newlines() -> None:
    # The model may put each segment on its own line; the capture is DOTALL.
    raw = "TASK: Plan a SQL agent.\nPICK: Fable 5 is S-tier.\nRUN: Ultracode on Claude Code."
    assert _split_rationale_sections(raw) == {
        "task": "Plan a SQL agent.",
        "pick": "Fable 5 is S-tier.",
        "run": "Ultracode on Claude Code.",
    }


def test_labels_are_case_insensitive() -> None:
    raw = "task: Coding. pick: Opus 4.8 is S-tier. run: Claude Code, Max effort."
    sections = _split_rationale_sections(raw)
    assert sections is not None
    assert sections["task"] == "Coding."


def test_markdown_emphasis_and_bullets_are_trimmed() -> None:
    raw = "TASK: **Coding task.** PICK: - Opus 4.8 S-tier. RUN: *Claude Code.*"
    assert _split_rationale_sections(raw) == {
        "task": "Coding task.",
        "pick": "Opus 4.8 S-tier.",
        "run": "Claude Code.",
    }


def test_unlabelled_prose_yields_no_sections() -> None:
    # A legacy / non-conforming single-string rationale degrades to None so the
    # web edge falls back to rendering it unsplit — never a hard failure.
    raw = "Opus 4.8 is S-tier for coding and leads SWE-bench Verified."
    assert _split_rationale_sections(raw) is None


def test_partial_labels_yield_no_sections() -> None:
    # Missing RUN -> treat the whole thing as unstructured (no empty sub-heading).
    assert _split_rationale_sections("TASK: Coding. PICK: Opus 4.8 S-tier.") is None


def test_empty_or_blank_yields_no_sections() -> None:
    assert _split_rationale_sections("") is None
    assert _split_rationale_sections("   \n  ") is None


# --- recommend_structured wiring --------------------------------------------


def _fake_base(rationale: str):
    """A fake ``recommend`` returning a minimal six-field base with ``rationale``."""

    def _fake(prompt: str, config: Config, **_kwargs: object) -> dict[str, str]:
        return {
            "model": "Opus 4.8",
            "platform": "Claude Code",
            "max_mode": "Off",
            "thinking": "Max",
            "conversation": "New",
            "rationale": rationale,
        }

    return _fake


def _config(tmp_path: Path) -> Config:
    ctx = tmp_path / "user-context.md"
    ctx.write_text("# ctx\n", encoding="utf-8")
    return Config(provider="anthropic", model=None, api_key="test-key", user_context_path=ctx)


def test_recommend_structured_attaches_sections_when_labelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        recommend_module,
        "recommend",
        _fake_base("TASK: Coding. PICK: Opus 4.8 is S-tier. RUN: Claude Code, Max effort."),
    )
    payload = recommend_module.recommend_structured("build a SQL agent", _config(tmp_path))
    assert payload["rationale_sections"] == {
        "task": "Coding.",
        "pick": "Opus 4.8 is S-tier.",
        "run": "Claude Code, Max effort.",
    }
    # The raw string is still carried for the fallback path.
    assert payload["rationale"].startswith("TASK:")


def test_recommend_structured_omits_sections_when_unlabelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recommend_module, "recommend", _fake_base("Opus 4.8 is S-tier for coding."))
    payload = recommend_module.recommend_structured("build a SQL agent", _config(tmp_path))
    # Key omitted entirely (not None) so the web edge cleanly falls back.
    assert "rationale_sections" not in payload
    assert payload["rationale"] == "Opus 4.8 is S-tier for coding."


def _fake_base_with(**fields: str):
    """A fake ``recommend`` returning a base merged with ``fields`` (e.g. an
    ``orchestration`` value), so tests can drive _structured_settings."""

    def _fake(prompt: str, config: Config, **_kwargs: object) -> dict[str, str]:
        base = {
            "model": "Opus 4.8",
            "platform": "Claude Code",
            "max_mode": "Off",
            "thinking": "XHigh",
            "conversation": "New",
            "rationale": "Opus 4.8 is S-tier.",
        }
        base.update(fields)
        return base

    return _fake


def test_recommend_structured_folds_ultracode_into_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Claude Code has NO separate orchestration dial — Ultracode is the TOP of its
    single /effort ladder (xhigh + Dynamic Workflows). So an ORCHESTRATION of
    Ultracode FOLDS into the effort value and there is NO separate orchestration
    settings row (0.2.16 reconciliation of the 0.2.15 orchestration row)."""
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with(orchestration="Ultracode"))
    payload = recommend_module.recommend_structured("plan a system", _config(tmp_path))
    assert payload["settings"]["effort"] == "Ultracode"
    assert payload["settings"]["thinking"] == "On"
    assert "orchestration" not in payload["settings"]


def test_recommend_structured_no_orchestration_leaves_effort_from_thinking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without an Ultracode orchestration, the Claude Code effort is just the
    THINKING level (here XHigh) and no orchestration row is emitted."""
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with())
    payload = recommend_module.recommend_structured("plan a system", _config(tmp_path))
    assert payload["settings"]["effort"] == "XHigh"
    assert "orchestration" not in payload["settings"]


def test_recommend_structured_cursor_thinking_on_max_mode_dial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Cursor pick must read Thinking=On + Max Mode (On/Off), never the raw
    THINKING=N/A the selector emits for Cursor (which has no thinking dial).
    Cursor's frontier models reason; the reframe happens at the display layer
    so the effort/thinking conformance cron can't revert it. There is NO effort
    key (Cursor has no effort dial — its dial is Max Mode)."""
    monkeypatch.setattr(
        recommend_module,
        "recommend",
        _fake_base_with(
            model="Composer 2.5",
            platform="Cursor",
            thinking="N/A",
            max_mode="On",
        ),
    )
    payload = recommend_module.recommend_structured("build a feature", _config(tmp_path))
    settings = payload["settings"]
    assert settings["thinking"] == "On"
    assert settings["max_mode"] == "ON"
    assert "effort" not in settings


def test_recommend_structured_cursor_max_mode_off_still_thinking_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even with Max Mode Off, a Cursor pick still reports Thinking=On — the
    reframe is unconditional for Cursor, not gated on Max Mode."""
    monkeypatch.setattr(
        recommend_module,
        "recommend",
        _fake_base_with(
            model="Composer 2.5",
            platform="Cursor",
            thinking="N/A",
            max_mode="Off",
        ),
    )
    payload = recommend_module.recommend_structured("fix a bug", _config(tmp_path))
    settings = payload["settings"]
    assert settings["thinking"] == "On"
    assert settings["max_mode"] == "OFF"
