# tests/test_mcp_server.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel import mcp_server  # noqa: E402
from roadmodel import recommend as recommend_module  # noqa: E402

RESPONSE_GPT_TEST_CODEX = (
    "MODEL: GPT Test\n"
    "PLATFORM: Codex\n"
    "MAX MODE: Off\n"
    "THINKING: High\n"
    "CONVERSATION: New\n"
    "RATIONALE: Fixture rationale for MCP tests.\n"
)


def _set_runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "ROADMODEL_PROVIDER",
        "ROADMODEL_USER_CONTEXT",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    context_path = tmp_path / "user-context.md"
    context_path.write_text("# user context for tests\n", encoding="utf-8")
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(context_path))


def _tool_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    content = getattr(result, "content", [])
    if not content:
        return None
    text = getattr(content[0], "text", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def test_tools_list_exactly_four() -> None:
    app = mcp_server.create_app()

    async def _run() -> list[str]:
        async with create_connected_server_and_client_session(app) as session:
            tools = await session.list_tools()
            return sorted(tool.name for tool in tools.tools)

    names = anyio.run(_run)
    assert names == [
        "generate_phase_roadmap",
        "read_catalog",
        "recommend_model",
        "score_candidates",
    ]


def test_recommend_model_calls_recommend_structured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_runtime_env(monkeypatch, tmp_path)

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

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
            self.calls.append(
                {"prompt": prompt, "system": system, "model": model, "api_key": api_key}
            )
            return RESPONSE_GPT_TEST_CODEX

    adapter = FakeAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    app = mcp_server.create_app()

    async def _run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool(
                "recommend_model", {"task_description": "build a SQL agent"}
            )
            return _tool_payload(result)

    payload = anyio.run(_run)
    assert adapter.calls, "provider adapter was not called"
    assert set(payload.keys()) == {
        "model",
        "platform",
        "settings",
        "rationale",
        "conversation",
        "session_cost_estimate",
        "comparison_table",
    }


def test_recommend_model_with_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_runtime_env(monkeypatch, tmp_path)
    context_text = "Repo has a strict phase-verify policy."

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

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
            self.calls.append(
                {"prompt": prompt, "system": system, "model": model, "api_key": api_key}
            )
            return RESPONSE_GPT_TEST_CODEX

    adapter = FakeAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    app = mcp_server.create_app()

    async def _run() -> None:
        async with create_connected_server_and_client_session(app) as session:
            await session.call_tool(
                "recommend_model",
                {
                    "task_description": "build a SQL agent",
                    "context": context_text,
                },
            )

    anyio.run(_run)
    assert adapter.calls, "provider adapter was not called"
    assert context_text in str(adapter.calls[0]["system"])


def test_generate_phase_roadmap_uses_template(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_runtime_env(monkeypatch, tmp_path)

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

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
            self.calls.append(
                {"prompt": prompt, "system": system, "model": model, "api_key": api_key}
            )
            return "# Phase 2 Roadmap\n\n- Step 1\n"

    adapter = FakeAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    app = mcp_server.create_app()

    async def _run() -> str:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool(
                "generate_phase_roadmap",
                {
                    "project_brief": "Ship MCP support for roadmodel.",
                    "phase_number": 2,
                    "prior_phases": ["Phase 1 shipped the CLI."],
                },
            )
            payload = _tool_payload(result)
            return str(payload)

    payload = anyio.run(_run)
    assert payload.startswith("# Phase 2 Roadmap")
    assert adapter.calls, "provider adapter was not called"
    assert "PHASE ROADMAP TEMPLATE" in str(adapter.calls[0]["system"])


def test_read_catalog_returns_three_keys() -> None:
    """The offline reasoning payload — everything a consumer needs WITHOUT an
    API call: the selector, the cost scale, the catalog, and the per-surface
    settings-display rules (which live in `_structured_settings` rather than the
    selector, and are otherwise unknowable from `read_catalog` alone).

    (Name kept: it is pinned by scripts/verify-phase02.sh Check 19 as a Step 4
    acceptance artifact. The payload has grown past three keys since.)
    """
    app = mcp_server.create_app()

    async def _run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool("read_catalog", {})
            payload = _tool_payload(result)
            if not isinstance(payload, dict):
                raise TypeError(f"Expected dict payload, got {type(payload)!r}")
            return payload

    payload = anyio.run(_run)
    selector_key = "model" + "_selector_txt"
    assert set(payload.keys()) == {
        selector_key,
        "model_tier_cost_scale_md",
        "settings_display_md",
        "catalog_json",
        "source_doc_sha256",
        "output_contract_version",
    }
    assert isinstance(payload["catalog_json"], dict)
    # The rule the raw selector cannot express: Claude Code folds a legacy
    # ORCHESTRATION:Ultracode into the effort VALUE and Thinking is a toggle.
    assert "effort=Ultracode; thinking=On" in payload["settings_display_md"]
    # ...and the v2 emission rule the offline consumer must honour: a dial the
    # platform lacks is an ABSENT line, never "Off"/"N/A".
    assert "the LINE IS ABSENT" in payload["settings_display_md"]


def test_read_catalog_declares_the_output_contract_version() -> None:
    """An offline consumer (planning kit, exported catalog) has to know WHICH
    block contract the bundled selector emits — v1 (MAX MODE always present,
    THINKING carrying the effort level) or v2 (platform-conditional dials, EFFORT
    and THINKING split). Diffing the doc is not a contract; this key is."""
    app = mcp_server.create_app()

    async def _run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool("read_catalog", {})
            payload = _tool_payload(result)
            if not isinstance(payload, dict):
                raise TypeError(f"Expected dict payload, got {type(payload)!r}")
            return payload

    payload = anyio.run(_run)
    assert payload["output_contract_version"] == recommend_module.OUTPUT_CONTRACT_VERSION
    assert payload["output_contract_version"] == 2
    # The bundled selector must actually declare the same version it advertises.
    assert (
        f"OUTPUT CONTRACT VERSION: {payload['output_contract_version']}"
        in payload["model" + "_selector_txt"]
    )


def test_main_exits_2_when_mcp_sdk_absent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for module_name in list(sys.modules.keys()):
        if module_name == "mcp" or module_name.startswith("mcp."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setitem(sys.modules, "mcp", None)
    with pytest.raises(SystemExit) as excinfo:
        mcp_server.main()
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert (
        "roadmodel-mcp: install with 'pip install roadmodel[mcp]' to enable the MCP server"
        in captured.err
    )


# --------------------------------------------------------------------------- #
# score_candidates — the deterministic scoring core over MCP (no engine call)
# --------------------------------------------------------------------------- #

TWO_PROVIDERS_CONTEXT = """# User Context

## Active subscriptions

| Subscription | Monthly | Provider | What it pays for |
| --- | --- | --- | --- |
| claude.ai Max ($200) | $200 | Anthropic | Claude Code |
| ChatGPT Pro ($100) | $100 | OpenAI | Codex |

## Active API keys

| Provider | Key present | Notes |
| --- | --- | --- |

## Budget priority and speed posture

**Budget priority:** `cheap`

**Consumption headroom:** `capped`
"""


def _call_score(args: dict[str, Any]) -> tuple[bool, Any]:
    app = mcp_server.create_app()

    async def _run() -> tuple[bool, Any]:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool("score_candidates", args)
            return bool(getattr(result, "isError", False)), _tool_payload(result)

    return anyio.run(_run)


def test_score_candidates_ranks_without_a_provider_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The scorer makes no engine call, so it must work with NO provider key
    configured at all — only the user-context resolution chain."""
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "ROADMODEL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    ctx = tmp_path / "user-context.md"
    ctx.write_text(TWO_PROVIDERS_CONTEXT, encoding="utf-8")
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(ctx))

    is_error, payload = _call_score({"category": "coding", "complexity": "medium", "top": 5})
    assert not is_error, payload
    assert payload["task"] == {
        "category": "coding",
        "complexity": "medium",
        "novel": False,
        "budget": "cheap",  # read from the user-context's Budget priority
    }
    assert payload["primary"]["funding"] == "subscription"
    assert payload["backup"] is not None
    assert payload["backup"]["provider"] != payload["primary"]["provider"]
    assert payload["backup_warning"] is None
    assert len(payload["candidates"]) == 5
    assert {"quality", "requirement_penalty", "cost_penalty", "effort", "score"} <= set(
        payload["candidates"][0]
    )


def test_score_candidates_is_case_insensitive_and_warns_without_a_second_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = tmp_path / "user-context.md"
    ctx.write_text(
        TWO_PROVIDERS_CONTEXT.replace("| ChatGPT Pro ($100) | $100 | OpenAI | Codex |\n", ""),
        encoding="utf-8",
    )
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(ctx))
    is_error, payload = _call_score(
        {"category": "Coding", "complexity": "HIGH", "novel": True, "budget": "Best", "top": 3}
    )
    assert not is_error, payload
    assert payload["task"]["budget"] == "best"
    assert payload["backup"] is None
    assert "funds only anthropic" in payload["backup_warning"]
