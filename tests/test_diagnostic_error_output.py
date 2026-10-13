"""Exercise the real evaluator entrypoint with a signature-bound synthetic provider."""

from __future__ import annotations

import importlib.util
import inspect
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "SYNTHETIC_PRIVATE_RESPONSE"


@pytest.mark.parametrize("fails", [True, False], ids=["provider-error", "successful-score"])
def test_classification_main_has_fixed_errors_and_preserves_scores(
    monkeypatch, tmp_path, capsys, fails
):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(sys, "path", list(sys.path))
    unexpected_calls = []

    def blocked(*args, **kwargs):
        unexpected_calls.append(1)
        raise AssertionError("Unexpected network or subprocess operation")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    spec = importlib.util.spec_from_file_location(
        "synthetic_classification_error_contract", ROOT / "scripts/eval_classification.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    signature = inspect.signature(module.recommend_structured_ladder)
    engine = {
        "provider": "openai",
        "model": "synthetic-model",
        "hint": "synthetic-engine",
        "ladder_max_output_tokens": 1,
        "thinking_budget": 0,
        "temperature": 0,
    }
    monkeypatch.setenv(module.PROVIDER_KEY_ENV[engine["provider"]], "synthetic-provider-key")
    monkeypatch.setattr(module, "default_engine", lambda: engine)
    probes = tmp_path / "synthetic-probes.json"
    probes.write_text(
        json.dumps(
            {
                "probes": [
                    {
                        "id": "synthetic",
                        "task": "Synthetic prompt",
                        "category": "coding",
                        "complexity": "medium",
                        "novel": False,
                    }
                ]
            }
        )
    )
    probes.chmod(0o600)
    monkeypatch.setattr(module, "PROBES_FILE", probes)
    calls = []
    contexts = []

    def provider(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        calls.append(bound)
        assert bound.arguments["prompt"] == "Synthetic prompt"
        config = bound.arguments["config"]
        assert config.api_key == "synthetic-provider-key"
        context = config.user_context_path
        assert context.parent == tmp_path and context.is_file()
        contexts.append(context)
        assert bound.arguments["classification_votes"] == 0
        assert bound.arguments["user_context_text"] is None
        if fails:
            raise RuntimeError(MARKER)
        return {"guard": {"classification": "coding/medium"}}

    monkeypatch.setattr(module, "recommend_structured_ladder", provider)
    assert module.main(["--runs", "1", "--concurrency", "1"]) == 0
    captured = capsys.readouterr()
    assert len(calls) == 1
    assert unexpected_calls == []
    assert MARKER not in captured.out and MARKER not in captured.err
    assert captured.err == ("Classification request failed.\n" if fails else "")
    summary = json.loads(captured.out.splitlines()[-1])
    assert summary == {
        "engine": "synthetic-engine",
        "probes": 1,
        "runs": 1,
        "votes": 0,
        "agree": int(not fails),
        "under": 0,
        "stable": int(not fails),
        "calls": 1,
    }
    assert len(contexts) == 1 and not contexts[0].exists()
    assert set(tmp_path.iterdir()) == {probes}
