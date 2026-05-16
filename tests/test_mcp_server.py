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


def test_tools_list_exactly_three() -> None:
    app = mcp_server.create_app()

    async def _run() -> list[str]:
        async with create_connected_server_and_client_session(app) as session:
            tools = await session.list_tools()
            return sorted(tool.name for tool in tools.tools)

    names = anyio.run(_run)
    assert names == ["generate_phase_roadmap", "read_catalog", "recommend_model"]


def test_recommend_model_calls_recommend_structured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_runtime_env(monkeypatch, tmp_path)

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

        def recommend(
            self, prompt: str, system: str, *, model: str | None = None, api_key: str
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
            self, prompt: str, system: str, *, model: str | None = None, api_key: str
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
            self, prompt: str, system: str, *, model: str | None = None, api_key: str
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
    app = mcp_server.create_app()

    async def _run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool("read_catalog", {})
            payload = _tool_payload(result)
            if not isinstance(payload, dict):
                raise TypeError(f"Expected dict payload, got {type(payload)!r}")
            return payload

    payload = anyio.run(_run)
    assert set(payload.keys()) == {
        "model_selector_txt",
        "model_tier_cost_scale_md",
        "catalog_json",
        "source_doc_sha256",
    }
    assert isinstance(payload["catalog_json"], dict)


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
