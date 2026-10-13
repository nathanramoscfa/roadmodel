"""Actual eval privacy contracts; engine and network operations are intercepted."""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import pathlib
import socket
import sys
import types

import pytest


@pytest.fixture
def evaluator(monkeypatch):
    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "synthetic_eval_contract", root / "scripts/eval_recommend_engines.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    def blocked(*a, **k):
        raise AssertionError("Unexpected network/model operation")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(module.urllib.request, "urlopen", blocked)
    monkeypatch.setattr(
        module.urllib.request, "build_opener", lambda *handlers: types.SimpleNamespace(open=blocked)
    )
    module._audit_recommend_signature = inspect.signature(module.recommend_structured_ladder)
    monkeypatch.setattr(module, "recommend_structured_ladder", blocked)
    monkeypatch.setattr(module, "_key_for", lambda provider: "synthetic-provider-key")
    return module


@pytest.mark.parametrize("which", ["service", "package", "fallback"])
def test_errors_have_closed_categories(evaluator, monkeypatch, which):
    m = evaluator
    marker = "SYNTHETIC_PRIVATE_RESPONSE"
    calls = []

    def failure(*a, **k):
        calls.append(1)
        raise RuntimeError(marker)

    # The deployed-source caller uses OpenerDirector.open, not urlopen.
    open_signature = inspect.signature(m.urllib.request.OpenerDirector.open)

    def opener(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], m.NoRedirect)

        def invoke(request, **kwargs):
            open_signature.bind(None, request, **kwargs)
            assert request.full_url == "https://service.invalid/v1/recommend/ladder"
            assert kwargs == {"timeout": 180}
            return failure(request, **kwargs)

        return types.SimpleNamespace(open=invoke)

    def provider_failure(*a, **k):
        m._audit_recommend_signature.bind(*a, **k)
        return failure(*a, **k)

    monkeypatch.setattr(m.urllib.request, "build_opener", opener)
    monkeypatch.setattr(m, "recommend_structured_ladder", provider_failure)
    if which == "fallback":

        class Reply:
            def __enter__(self):
                return io.StringIO(json.dumps({"engine": marker}))

            def __exit__(self, *a):
                return False

        def fallback(*a, **k):
            calls.append(1)
            return Reply()

        def fallback_opener(*handlers):
            assert len(handlers) == 1 and isinstance(handlers[0], m.NoRedirect)
            return types.SimpleNamespace(open=fallback)

        monkeypatch.setattr(m.urllib.request, "build_opener", fallback_opener)
    eng = m.ENGINES[0]
    result = (
        m._run_one(eng, "Synthetic prompt")
        if which == "package"
        else m._run_via_service(
            eng, "Synthetic prompt", "https://service.invalid", "synthetic-token"
        )
    )
    assert calls == [1], "Mock must reach the actual current transport/provider boundary"
    assert marker not in json.dumps(result)
    assert set(result) <= {"error", "latency_s"}
    assert isinstance(result["latency_s"], (int, float))


@pytest.mark.parametrize("suffix", [".jsonl", ".md"])
def test_both_private_destinations_preflight_before_engine(
    evaluator, monkeypatch, tmp_path, suffix
):
    m = evaluator
    tmp_path.chmod(0o700)
    prefix = tmp_path / "result"
    target = tmp_path / "sentinel"
    target.write_text("untouched")
    target.chmod(0o600)
    pathlib.Path(str(prefix) + suffix).symlink_to(target)
    calls = []
    monkeypatch.setattr(
        m,
        "_run_one",
        lambda *a: calls.append(1) or {"error": "synthetic_failure", "latency_s": 0.1},
    )
    monkeypatch.setattr(
        sys, "argv", ["eval", "--out", str(prefix), "--engines", m.ENGINES[0].key, "--probes", "1"]
    )
    with pytest.raises((SystemExit, OSError, ValueError)):
        m.main()
    assert not calls
    assert target.read_text() == "untouched"


def test_missing_service_token_cannot_truncate_link(evaluator, monkeypatch, tmp_path):
    m = evaluator
    tmp_path.chmod(0o700)
    prefix = tmp_path / "result"
    target = tmp_path / "sentinel"
    target.write_text("untouched")
    target.chmod(0o600)
    pathlib.Path(str(prefix) + ".jsonl").symlink_to(target)
    monkeypatch.delenv("ROADMODEL_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval",
            "--out",
            str(prefix),
            "--engines",
            m.ENGINES[0].key,
            "--probes",
            "1",
            "--via-service",
            "https://service.invalid",
        ],
    )
    with pytest.raises((SystemExit, OSError, ValueError)):
        m.main()
    assert target.read_text() == "untouched"


def test_private_modes_with_permissive_umask(evaluator, monkeypatch, tmp_path):
    m = evaluator
    tmp_path.chmod(0o700)
    prefix = tmp_path / "result"
    monkeypatch.setattr(m, "_run_one", lambda *a: {"error": "synthetic_failure", "latency_s": 0.1})
    monkeypatch.setattr(
        sys, "argv", ["eval", "--out", str(prefix), "--engines", m.ENGINES[0].key, "--probes", "1"]
    )
    previous = os.umask(0)
    try:
        assert m.main() == 0
    finally:
        os.umask(previous)
    for suffix in [".jsonl", ".md"]:
        assert pathlib.Path(str(prefix) + suffix).stat().st_mode & 0o777 == 0o600


def test_flushed_row_survives_interrupted_engine_loop(evaluator, monkeypatch, tmp_path):
    m = evaluator
    tmp_path.chmod(0o700)
    prefix = tmp_path / "result"
    calls = []

    def engine(*a):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return {"error": "synthetic_failure", "latency_s": 0.1}

    monkeypatch.setattr(m, "_run_one", engine)
    monkeypatch.setattr(
        sys, "argv", ["eval", "--out", str(prefix), "--engines", m.ENGINES[0].key, "--probes", "2"]
    )
    with pytest.raises(KeyboardInterrupt):
        m.main()
    lines = pathlib.Path(str(prefix) + ".jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["error"] == "synthetic_failure"


def test_offline_summary_preserves_public_shape_and_mirror(evaluator, monkeypatch, tmp_path):
    m = evaluator
    tmp_path.chmod(0o700)
    repo = tmp_path / "isolated-repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "service/app").mkdir(parents=True)
    (repo / "scripts").mkdir()
    monkeypatch.setattr(m, "__file__", str(repo / "scripts/eval_recommend_engines.py"))
    engine = m.ENGINES[0]
    probe = m.PROBES[0]
    source = tmp_path / "saved.jsonl"
    prefix = tmp_path / "report"
    row = {
        "engine": engine.key,
        "ga": engine.ga,
        "probe": probe["id"],
        "latency_s": 0.2,
        "healthy": True,
        "usage": None,
        "picks": {
            tier: {"model": "Synthetic Model", "platform": "synthetic", "settings": {}}
            for tier in ["cost", "balanced", "quality"]
        },
        "checks": {
            "all_fields": True,
            "sections_parse": True,
            "no_task_leak": True,
            "no_cost_demotion": True,
        },
        "ignored_private": "SYNTHETIC_PRIVATE_RESPONSE",
    }
    source.write_text(json.dumps(row) + "\n")
    source.chmod(0o600)
    summary = repo / "docs/engine-eval.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", "--from-jsonl", str(source), "--out", str(prefix), "--summary-json", str(summary)],
    )
    assert m.main() == 0
    assert summary.read_bytes() == (repo / "service/app/engine-eval.json").read_bytes()
    doc = json.loads(summary.read_text())
    assert "SYNTHETIC_PRIVATE_RESPONSE" not in summary.read_text()
    assert set(doc) == {"engines", "_comment", "generated_at"}
    metrics = doc["engines"][m._service_hint(engine)]
    assert set(metrics) == {
        "evaluated_on",
        "probes",
        "parsed",
        "passed",
        "healthy_ladder",
        "p50_latency_s",
        "mean_cost_usd",
        "mean_input_tokens",
        "cached_share",
        "quality_pick_blended_per_1m",
        "via",
    }
