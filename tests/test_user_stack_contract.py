"""Contract regressions for a single-platform, flat-funded operator stack.

The motivating configuration (the one that surfaced defects D1-D6) is an
operator whose ENTIRE stack is Claude Code on a claude.ai Max 20x plan:

    - Platform: Claude Code, and only Claude Code. No Cursor subscription.
    - Model: Opus 4.8 as the floor; Fable 5 for the hardest prompts.
    - Effort: always ``Max``; ``Ultracode`` where it is optimal.
    - Thinking: On.  Conversation: New per step.

On that plan every one of those is $0 marginal and has never rate-limited, so
the recommendations must describe dials the operator can literally set:

    D1  no ``MAX MODE`` line at all (Claude Code has no such control)
    D2  ``EFFORT`` carries the level; ``THINKING`` is a two-position toggle
    D3  ``Ultracode`` is the top EFFORT rung, not a separate axis
    D4  a $0-marginal subscription must not trigger a cost tier-down
    D5  an excluded platform must never win, and must be disclosed

These tests pin the two halves CI can prove deterministically: (a) the fixture
user-context reaches the engine carrying the hard-filter and hold-tier
instructions, and (b) whatever the engine returns, the parse + display layer
can never manufacture a phantom dial or put an effort word in THINKING. The
engine's own judgement is exercised separately by a live probe
(``scripts/probe-user-stack-contract.py``), which needs an API key and so
cannot run in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel import recommend as recommend_module  # noqa: E402
from roadmodel.config import Config  # noqa: E402

# --------------------------------------------------------------------------- #
# The operator's declared stack, in the shape docs/user-context.example.md
# documents. Deliberately a SINGLE-platform allowlist: Cursor is absent from
# the subscriptions AND explicitly excluded, which is the D5 case.
# --------------------------------------------------------------------------- #

USER_CONTEXT = """# User Context

## Active subscriptions

| Subscription  | Monthly | Provider  | What it pays for |
| ------------- | ------- | --------- | ---------------- |
| claude.ai Max | $200    | Anthropic | Opus / Sonnet / Fable usage on claude.ai and Claude Code (CLI + IDE extension) under a shared Max usage budget. Funds 100% of token volume; the budget has never been exhausted. |

## Active API keys

| Provider  | Key present | Notes |
| --------- | ----------- | ----- |
| Anthropic | No          | No direct key; all Claude usage runs through the Max subscription. |
| OpenAI    | No          | Not subscribed, no key. |
| Google    | No          | Not subscribed, no key. |

## Inactive / not subscribed

- **Cursor.** No subscription and no intention to use the surface.

## Allowed / excluded platforms

**platforms.allowed:** `claude-code`

**platforms.excluded:** `cursor`

Hard filter, applied before any scoring (unlike the soft preference order
below). Only `claude-code` may be recommended as a PLATFORM.

## Platform preference order

1. **Claude Code (CLI / IDE extension)** for any Claude model.

## Budget priority and speed posture

**Budget priority:** `cheap`

**Consumption headroom:** `uncapped` — the Max plan's usage budget is not
exhausted and has never rate-limited this operator, so effort is free.

**Speed posture:** speed is NOT a valued dimension.
"""

# A representative spread of task difficulty, per the verification brief.
TASKS: dict[str, str] = {
    "trivial": "Rename the variable `usr` to `user` in a single Python file and update its three references.",
    "mid": "Refactor the payments module across eight files to replace the ad-hoc retry logic with a shared backoff helper.",
    "hard": (
        "Design the authentication and tenant-isolation architecture for a multi-tenant SaaS, "
        "covering token lifetime, key rotation, and cross-tenant data-leak prevention."
    ),
}

# Effort words that must NEVER appear as a THINKING value. This is the literal
# D2 bug: the operator's roadmaps inherited `THINKING: Max`, which no Claude
# Code thinking toggle can be set to.
EFFORT_WORDS = {"low", "medium", "high", "xhigh", "max", "ultracode"}


def _config(tmp_path: Path) -> Config:
    ctx = tmp_path / "user-context.md"
    ctx.write_text(USER_CONTEXT, encoding="utf-8")
    return Config(
        provider="anthropic",
        model=None,
        api_key="test-key",
        user_context_path=ctx,
    )


class _FakeAdapter:
    """Provider stub that records the prompts and replays a canned block."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def recommend(self, user_prompt: str, system_prompt: str, **kwargs: Any) -> str:
        self.calls.append({"user": user_prompt, "system": system_prompt, **kwargs})
        return self.response


def _install(monkeypatch: pytest.MonkeyPatch, response: str) -> _FakeAdapter:
    adapter = _FakeAdapter(response)
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    return adapter


# A v2 Claude Code block exactly as the rewritten <output-format> specifies:
# no MAX MODE line (Claude Code exposes none), EFFORT carrying the level, and
# THINKING as a bare toggle.
V2_CLAUDE_CODE = """MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: A multi-file refactor. PICK: Opus 4.8 is S-tier for coding and leads SWE-bench Verified. EFFORT: Max effort suits the cross-file reasoning, and the Max plan makes it free.
"""

V2_CLAUDE_CODE_ULTRACODE = V2_CLAUDE_CODE.replace("EFFORT: Max", "EFFORT: Ultracode")


# --------------------------------------------------------------------------- #
# The prompt the engine receives (D4 / D5)
# --------------------------------------------------------------------------- #


def test_flat_funding_gate_reaches_the_engine(tmp_path: Path) -> None:
    """D4: the prompt must tell the engine that tiering down saves nothing here."""
    system, _ = recommend_module.build_prompt(TASKS["trivial"], user_context_text=USER_CONTEXT)
    assert "FLAT-FUNDING GATE" in system
    # The gate's two obligations, both load-bearing for this operator.
    assert "HOLD the capability tier" in system
    assert "TOP USEFUL rung" in system
    # And the honest-convergence rule that replaces a manufactured spread.
    assert "NEVER manufacture an artificial" in system


def test_cheap_posture_no_longer_forbids_max_unconditionally(tmp_path: Path) -> None:
    """D4 regression: the `cheap` floor must be explicitly suspendable.

    Before the fix, `cheap` said "Never emit `Max`" flatly, which on a flat
    $0 plan traded real quality for zero saving.
    """
    system, _ = recommend_module.build_prompt(TASKS["trivial"], user_context_text=USER_CONTEXT)
    idx = system.find("Never emit `Max` effort")
    assert idx != -1, "the cheap-posture effort floor should still be stated"
    # ...but immediately qualified as suspended by the gate.
    assert "SUSPENDED by the FLAT-FUNDING GATE" in system[idx : idx + 400]


def test_platform_allowlist_is_a_hard_filter_in_the_prompt(tmp_path: Path) -> None:
    """D5: the allowlist must be described as a pre-scoring hard filter."""
    system, _ = recommend_module.build_prompt(TASKS["mid"], user_context_text=USER_CONTEXT)
    assert "Step A00" in system
    assert "platforms.allowed" in system and "platforms.excluded" in system
    # It must outrank the never-hard-exclude-an-unfunded-method guardrail.
    assert "OUTRANKS" in system
    # And an absent list must never be read as "allow nothing".
    assert 'NEVER "allow nothing"' in system or 'never "allow nothing"' in system.lower()
    # The operator's own declaration is carried through verbatim.
    assert "platforms.allowed:** `claude-code`" in system


def test_excluded_platform_requires_disclosure_not_silent_substitution() -> None:
    system, _ = recommend_module.build_prompt(TASKS["mid"], user_context_text=USER_CONTEXT)
    assert "DISCLOSURE" in system
    assert "do not substitute silently" in system


# --------------------------------------------------------------------------- #
# The block the operator actually receives (D1 / D2 / D3)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("task_key", sorted(TASKS))
def test_claude_code_pick_emits_no_max_mode_dial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_key: str
) -> None:
    """D1: across the whole task spread, no phantom Max Mode reaches the user."""
    _install(monkeypatch, V2_CLAUDE_CODE)
    result = recommend_module.recommend_structured(TASKS[task_key], _config(tmp_path))

    assert result["platform"] == "Claude Code"
    settings = result["settings"]
    assert "max_mode" not in settings, (
        "Claude Code has no Max Mode control; emitting one (even as Off) is the D1 bug"
    )


@pytest.mark.parametrize("task_key", sorted(TASKS))
def test_effort_present_and_thinking_is_a_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_key: str
) -> None:
    """D2: EFFORT carries the level; THINKING is On/Off and never an effort word."""
    _install(monkeypatch, V2_CLAUDE_CODE)
    result = recommend_module.recommend_structured(TASKS[task_key], _config(tmp_path))

    settings = result["settings"]
    assert settings["effort"] in {"Max", "Ultracode"}
    assert settings["thinking"] in {"On", "Off"}
    assert settings["thinking"].strip().lower() not in EFFORT_WORDS
    assert not settings["thinking"].strip().isdigit(), "THINKING is never a token budget"


def test_ultracode_is_the_top_effort_rung(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D3: Ultracode round-trips as an EFFORT value, with no orchestration row."""
    _install(monkeypatch, V2_CLAUDE_CODE_ULTRACODE)
    result = recommend_module.recommend_structured(TASKS["hard"], _config(tmp_path))

    settings = result["settings"]
    assert settings["effort"] == "Ultracode"
    assert settings["thinking"] == "On"
    assert "orchestration" not in settings, "Ultracode is an effort rung, not a second axis"
    assert "max_mode" not in settings


def test_every_emitted_setting_is_one_the_operator_can_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the contract: no line the operator cannot apply.

    Claude Code's real controls are the ``/effort`` dial and the extended-
    thinking toggle. Anything else in ``settings`` is a dial that does not
    exist on the surface the block names.
    """
    _install(monkeypatch, V2_CLAUDE_CODE)
    result = recommend_module.recommend_structured(TASKS["hard"], _config(tmp_path))
    assert set(result["settings"]) == {"effort", "thinking"}


def test_v1_response_still_parses_and_never_leaks_a_thinking_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy acceptance: a cached v1 block must not resurrect the D1/D2 bugs.

    Older releases and cached engine responses still emit ``MAX MODE: Off`` and
    a ``THINKING`` carrying the effort word. The display layer must fold that
    into the v2 shape rather than passing it through.
    """
    v1 = """MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
MAX MODE: Off
THINKING: Max
ORCHESTRATION: Ultracode
CONVERSATION: New
RATIONALE: TASK: Planning. PICK: Opus 4.8 is S-tier. EFFORT: Ultracode fits the scope.
"""
    _install(monkeypatch, v1)
    result = recommend_module.recommend_structured(TASKS["hard"], _config(tmp_path))

    settings = result["settings"]
    assert "max_mode" not in settings, "a v1 MAX MODE: Off must not surface as a dial"
    assert settings["thinking"] == "On", "THINKING: Max must never reach the operator"
    assert settings["effort"] == "Ultracode"


# --------------------------------------------------------------------------- #
# The roadmap annotation path shares the contract (it must not drift)
# --------------------------------------------------------------------------- #


def _roadmap_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Drive generate_phase_roadmap through a stub provider and capture prompts."""
    from roadmodel import mcp_server

    adapter = _FakeAdapter(ROADMAP_OUTPUT)
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    monkeypatch.setattr(mcp_server, "_load_runtime_config", lambda: _config(tmp_path))

    app = mcp_server.create_app()
    tool = _tool_fn(app, "generate_phase_roadmap")
    out = tool(project_brief="Ship a billing service.", phase_number=1, prior_phases=None)
    return {"adapter": adapter, "output": out}


def _tool_fn(app: Any, name: str) -> Any:
    """Pull a registered FastMCP tool's underlying callable."""
    for attr in ("_tool_manager", "_tools"):
        holder = getattr(app, attr, None)
        if holder is None:
            continue
        tools = getattr(holder, "_tools", holder)
        if isinstance(tools, dict) and name in tools:
            tool = tools[name]
            return getattr(tool, "fn", tool)
    raise AssertionError(f"tool {name!r} not registered")


# A representative roadmap annotation block, in the same v2 shape the
# single-prompt path emits. The roadmap path returns raw text, so the contract
# is enforced by the shared <output-format> in the system prompt.
ROADMAP_OUTPUT = """## Step 1.1 — Scaffold the billing service

MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: Opus 4.8 is S-tier for coding. EFFORT: Max fits the scope.
PROMPT: 1.1
"""


def test_roadmap_path_ships_the_same_output_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The roadmap annotation path must carry the identical v2 contract.

    Both paths concatenate the same bundled model-selector.txt, so a drift here
    would mean the two surfaces disagree about what a block contains.
    """
    captured = _roadmap_prompts(monkeypatch, tmp_path)
    system = captured["adapter"].calls[0]["system"]

    assert "OUTPUT CONTRACT VERSION: 2" in system
    assert "EFFORT: [Low/Medium/High/XHigh/Max/Ultracode]" in system
    assert "THINKING: [On/Off]" in system
    # The conditional-emission rule, without which the roadmap would re-emit
    # MAX MODE on every block the way the operator's roadmaps used to.
    assert "PLATFORM-CONDITIONAL" in system
    assert "exposes-max-mode" in system
    # And the operator's stack reaches the roadmap path too.
    assert "platforms.allowed" in system
    assert "FLAT-FUNDING GATE" in system


def test_roadmap_annotation_blocks_parse_under_the_shared_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A roadmap block must satisfy the same parser as a single-prompt block."""
    captured = _roadmap_prompts(monkeypatch, tmp_path)
    parsed = recommend_module.parse_response(captured["output"])

    assert parsed["platform"] == "Claude Code"
    assert parsed["effort"] == "Max"
    assert parsed["thinking"] == "On"
    assert "max_mode" not in parsed, "roadmap blocks must not carry a phantom Max Mode"

    settings = recommend_module._structured_settings(parsed)
    assert set(settings) == {"effort", "thinking"}
    assert settings["thinking"].lower() not in EFFORT_WORDS


def test_roadmap_path_front_loads_the_contract_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The roadmap path must carry the same front-loaded rules as /recommend.

    Measured drift, before this header existed: with the selector alone, roadmap
    blocks correctly omitted MAX MODE and kept THINKING a toggle, but settled at
    ``EFFORT: High`` on a flat-funded plan — the <objective> FLAT-FUNDING GATE
    was buried too deep to survive generating a long document. Losing this
    header silently reintroduces that drift, so pin it.
    """
    captured = _roadmap_prompts(monkeypatch, tmp_path)
    system = captured["adapter"].calls[0]["system"]

    assert "PLATFORM-CONDITIONAL SETTINGS" in system
    assert "'THINKING: Max' is invalid" in system
    assert "FLAT-FUNDING GATE" in system
    assert "the complexity ladder is a FLOOR" in system
    assert "HARD filter" in system
    # The header must lead, so it is not buried behind the whole template.
    assert system.index("PLATFORM-CONDITIONAL SETTINGS") < 2000
