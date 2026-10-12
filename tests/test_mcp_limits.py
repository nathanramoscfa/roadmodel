"""Real MCP error serialization must not echo invalid private inputs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

anyio = pytest.importorskip("anyio")
pytest.importorskip("mcp")
from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from roadmodel import mcp_server  # noqa: E402
from roadmodel.config import Config  # noqa: E402

MARKER = "SYNTHETIC_PRIVATE_INPUT"


@pytest.mark.parametrize("logging_level", ["ERROR", "WARNING", "DEBUG"])
def test_malformed_stdio_never_echoes_input(logging_level: str) -> None:
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "privacy-test", "version": "1"},
        },
    }
    payload = (
        json.dumps(initialize)
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + '\n{"PRIVATECANARY":\n'
    )
    payload += json.dumps({"jsonrpc": "2.0", "id": 2, "method": "PRIVATECANARY"}) + "\n"
    payload += (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": {"PRIVATECANARY": True}},
            }
        )
        + "\n"
    )
    payload += json.dumps({"jsonrpc": "2.0", "method": "notifications/PRIVATECANARY"}) + "\n"
    payload += json.dumps({"jsonrpc": "2.0", "id": 777, "result": {"PRIVATECANARY": True}}) + "\n"
    payload += (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "prompts/get",
                "params": {"name": "PRIVATECANARY"},
            }
        )
        + "\n"
    )
    payload += (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/read",
                "params": {"uri": "file:///PRIVATECANARY"},
            }
        )
        + "\n"
    )
    payload += (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progressToken": 8, "progress": 1, "message": "PRIVATECANARY"},
            }
        )
        + "\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import logging; logging.basicConfig(level=logging.{logging_level}); from roadmodel.mcp_server import main; main()",
        ],
        input=payload,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert '"protocolVersion"' in result.stdout
    assert "PRIVATECANARY" not in result.stdout + result.stderr
    assert '"code":-32602' in result.stdout
    assert '"code":-32601' in result.stdout


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("recommend_model", {"task_description": "x" * 16_385}),
        ("recommend_model", {"task_description": "ok", "context": "x" * 65_537}),
        ("recommend_model", {"task_description": "  "}),
        ("generate_phase_roadmap", {"project_brief": "x" * 65_537, "phase_number": 1}),
        ("generate_phase_roadmap", {"project_brief": "ok", "phase_number": MARKER}),
        ("generate_phase_roadmap", {"project_brief": "ok", "phase_number": True}),
        ("generate_phase_roadmap", {"project_brief": "ok", "phase_number": -1}),
        ("generate_phase_roadmap", {"project_brief": "ok", "phase_number": 1001}),
        (
            "generate_phase_roadmap",
            {"project_brief": "ok", "phase_number": 1, "prior_phases": json.dumps(["x"] * 25)},
        ),
        (
            "generate_phase_roadmap",
            {"project_brief": "ok", "phase_number": 1, "prior_phases": ["x"] * 25},
        ),
        (
            "generate_phase_roadmap",
            {"project_brief": "ok", "phase_number": 1, "prior_phases": ["x" * 8193]},
        ),
        (
            "generate_phase_roadmap",
            {"project_brief": "ok", "phase_number": 1, "prior_phases": ["x" * 8192] * 17},
        ),
        ("score_candidates", {"category": MARKER, "complexity": "low"}),
        ("score_candidates", {"category": "coding", "complexity": "low", "top": 101}),
        (MARKER, {}),
    ],
)
def test_invalid_inputs_never_load_context_or_echo_values(
    name: str,
    arguments: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    def forbidden() -> Config:
        calls.append("configuration")
        raise AssertionError("Input must be validated first")

    monkeypatch.setattr(mcp_server, "_load_runtime_config", forbidden)
    app = mcp_server.create_app()

    async def run() -> None:
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool(name, arguments)
            assert result.isError
            assert MARKER not in result.model_dump_json()

    anyio.run(run)
    assert not calls
    output = capsys.readouterr()
    assert MARKER not in output.out + output.err + caplog.text


def test_bounded_read_and_final_utf8_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = tmp_path / "context"
    context.write_bytes(b"x" * (262_144 + 1))
    with pytest.raises(ValueError, match="byte limit"):
        mcp_server._bounded_context(context)
    with pytest.raises(ValueError, match="byte limit"):
        mcp_server._check_prompts("x" * 524_288, "\U0001f600" * 131_073)


def test_roadmap_budget_and_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = tmp_path / "context"
    context.write_text("synthetic private context")
    config = Config(
        provider="anthropic", model=None, api_key="fixture-credential", user_context_path=context
    )
    monkeypatch.setattr(mcp_server, "_load_runtime_config", lambda: config)
    captured: list[Any] = []

    class Adapter:
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
            captured.append(max_output_tokens)
            return "roadmap"

    monkeypatch.setitem(mcp_server.recommender.PROVIDER_ADAPTERS, "anthropic", Adapter())
    app = mcp_server.create_app()

    async def run() -> None:
        async with create_connected_server_and_client_session(app) as session:
            tools = await session.list_tools()
            schema = next(t.inputSchema for t in tools.tools if t.name == "generate_phase_roadmap")
            assert schema["properties"]["project_brief"]["maxLength"] == 65_536
            result = await session.call_tool(
                "generate_phase_roadmap",
                {
                    "project_brief": "x" * 65_536,
                    "phase_number": 1000,
                    "prior_phases": ["x" * 8192] * 16,
                },
            )
            assert not result.isError

    anyio.run(run)
    assert captured == [4096]


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("recommend_model", {"task_description": "ok"}),
        ("generate_phase_roadmap", {"project_brief": "ok", "phase_number": 1}),
    ],
)
def test_mcp_provider_failure_is_private_and_has_one_bounded_attempt(
    name, arguments, tmp_path, monkeypatch, caplog
):
    context = tmp_path / "context"
    context.write_text("private fixture context")
    config = Config(
        provider="anthropic", model=None, api_key="fixture-credential", user_context_path=context
    )
    monkeypatch.setattr(mcp_server, "_load_runtime_config", lambda: config)
    attempts = []

    class Adapter:
        def recommend(
            self,
            prompt,
            system,
            *,
            model=None,
            api_key,
            max_output_tokens=None,
            thinking_budget=None,
            temperature=None,
        ):
            from roadmodel.providers._safety import hosted_timeout

            attempts.append((max_output_tokens, hosted_timeout()))
            raise ValueError("PRIVATECANARY")

    monkeypatch.setitem(mcp_server.recommender.PROVIDER_ADAPTERS, "anthropic", Adapter())
    app = mcp_server.create_app()

    async def run():
        async with create_connected_server_and_client_session(app) as session:
            result = await session.call_tool(name, arguments)
            assert result.isError
            assert "PRIVATECANARY" not in result.model_dump_json()

    anyio.run(run)
    assert attempts == [(4096, 120)]
    assert "PRIVATECANARY" not in caplog.text


def test_mcp_logging_scope_restores_and_keeps_other_threads(caplog):
    import logging
    from concurrent.futures import ThreadPoolExecutor

    logger = logging.getLogger("mcp.server.lowlevel.server")
    with caplog.at_level(logging.DEBUG):
        with mcp_server._private_mcp_logs():
            logger.error("PRIVATECANARY")
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(logger.error, "unrelated thread").result()
            logging.getLogger("host.application").error("host diagnostic")
        logger.error("restored")
    assert "PRIVATECANARY" not in caplog.text
    assert "unrelated thread" in caplog.text
    assert "host diagnostic" in caplog.text
    assert "restored" in caplog.text
