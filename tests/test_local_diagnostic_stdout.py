"""Diagnostic stdout stays bounded; actual entrypoints use synthetic provider responses."""

from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib
import runpy
import socket
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKER = "SYNTHETIC_PRIVATE_RESPONSE"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def world(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def blocked(*a, **k):
        raise AssertionError("Unexpected external operation")

    monkeypatch.setattr(socket, "create_connection", blocked)
    original_run_signature = inspect.signature(subprocess.run)
    monkeypatch.setattr(subprocess, "run", blocked)
    m = load("synthetic_judge_stdout_contract", ROOT / "scripts/judge_recommend.py")
    monkeypatch.setitem(sys.modules, "judge_recommend", m)
    probe = {
        "id": "synthetic",
        "task": "Synthetic prompt",
        "category": "coding",
        "complexity": "low",
        "novel": False,
    }
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "id": "synthetic",
                "mode": "anon",
                "iter": 1,
                "status": 200,
                "engine": {"maker": "synthetic"},
                "ladder": [
                    {
                        "priority": p,
                        "model": "Synthetic Model",
                        "platform": "synthetic",
                        "settings": {"effort": "low"},
                    }
                    for p in ["cheap", "balanced", "best"]
                ],
            }
        )
        + "\n"
    )
    rows.chmod(0o600)
    monkeypatch.setattr(m, "load_probes", lambda: [probe])
    monkeypatch.setattr(m, "bundled_context", lambda: "")
    monkeypatch.setattr(m, "unavailable_ids", lambda: [])
    monkeypatch.setattr(m._cost, "_load_catalog", lambda: {"models": []})
    monkeypatch.setattr(m.scoring, "ladder_table", lambda *a, **k: {})
    monkeypatch.setattr(m, "b2_probe", lambda *a: [])
    monkeypatch.setattr(m, "controls", lambda *a: [])
    monkeypatch.setattr(m, "system_prompt", lambda *a: "")
    return m, rows, original_run_signature


@pytest.mark.parametrize("case", ["invalid_criterion", "blocker_evidence", "b2_detail"])
def test_judge_scorecard_excludes_response_text(world, monkeypatch, tmp_path, capsys, case):
    m, rows, signature = world
    calls = []
    criteria = [
        {
            "id": c,
            "pass": True,
            "severity": "minor",
            "evidence": "Synthetic evidence long enough for validation",
        }
        for c in m.CRITERIA
    ]
    if case == "invalid_criterion":
        criteria[0]["id"] = MARKER
    if case == "blocker_evidence":
        criteria[0].update(
            {"pass": False, "severity": "blocker", "evidence": MARKER + " synthetic evidence"}
        )
    if case == "b2_detail":
        monkeypatch.setattr(m, "b2_probe", lambda *a: [MARKER])
    payload = {
        "structured_output": {"criteria": criteria, "accept": case != "blocker_evidence"},
        "total_cost_usd": 0.01,
    }

    def run(*args, **kwargs):
        signature.bind(*args, **kwargs)
        assert args[0][0] == "claude"
        assert kwargs["timeout"] == 300
        calls.append(1)
        return subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", run)
    output = tmp_path / "judge.json"
    assert m.main(["--rows", str(rows), "--out", str(output)]) == 1
    logged = capsys.readouterr()
    assert calls and MARKER not in logged.out + logged.err
    assert "=== JUDGE SCORECARD" in logged.out and "JUDGE_RESULT: FAIL" in logged.out
    assert MARKER in output.read_text()  # diagnostics remain available privately
    assert output.stat().st_mode & 0o777 == 0o600
    assert {(x["id"], x["bar"]) for x in json.loads(output.read_text())["checks"]} == {
        ("pick-spec-correct", "B2"),
        ("judge-accept", "B6"),
    }


def test_gold_cache_extension_keeps_prior_entries_and_closes_stdout(
    world, monkeypatch, tmp_path, capsys
):
    jr, rows, _ = world
    m = load("synthetic_gold_cache_contract", ROOT / "scripts/gold_differential.py")
    calls = []

    def gold(*args):
        inspect.signature(m.run_gold_original).bind(*args)
        calls.append(1)
        return {
            "synthetic": {
                "category": "coding",
                "complexity": "low",
                "novel": False,
                "model": MARKER,
                "platform": "synthetic",
                "effort": "low",
            }
        }

    m.run_gold_original = m.run_gold
    monkeypatch.setattr(m, "run_gold", gold)
    cache = tmp_path / "gold.json"
    cache.write_text(json.dumps({"old": {"model": "Preserved"}}))
    cache.chmod(0o600)
    for index in [1, 2]:
        output = tmp_path / f"report-{index}.json"
        assert m.main(["--rows", str(rows), "--gold", str(cache), "--out", str(output)]) == 0
        logged = capsys.readouterr()
        assert MARKER not in logged.out + logged.err
        assert MARKER in output.read_text()
        assert output.stat().st_mode & 0o777 == 0o600
    assert calls == [1]
    data = json.loads(cache.read_text())
    assert data["old"] == {"model": "Preserved"}
    assert data["synthetic"]["model"] == MARKER
    assert cache.stat().st_mode & 0o777 == 0o600


def test_gold_timeout_cli_has_fixed_error_and_removes_prompt_file(
    world, monkeypatch, tmp_path, capsys
):
    jr, rows, signature = world
    calls = []
    prompt_files = []

    def run(*args, **kwargs):
        signature.bind(*args, **kwargs)
        assert args[0][0] == "claude"
        assert kwargs["timeout"] == 600
        prompt_files.append(pathlib.Path(args[0][args[0].index("--system-prompt-file") + 1]))
        calls.append(1)
        raise subprocess.TimeoutExpired(["claude", MARKER], 600, output=MARKER, stderr=MARKER)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gold",
            "--rows",
            str(rows),
            "--gold",
            str(tmp_path / "gold.json"),
            "--out",
            str(tmp_path / "report.json"),
        ],
    )
    with pytest.raises(SystemExit) as exit_result:
        runpy.run_path(str(ROOT / "scripts/gold_differential.py"), run_name="__main__")
    assert exit_result.value.code == 2
    assert calls == [1]
    assert prompt_files and all(not p.exists() for p in prompt_files)
    logged = capsys.readouterr()
    assert MARKER not in logged.out + logged.err
    assert "Traceback" not in logged.err
    assert "Diagnostic input or private output is unavailable." in logged.err


def test_eval_progress_does_not_print_returned_model(world, monkeypatch, tmp_path, capsys):
    m = load("synthetic_eval_stdout_contract", ROOT / "scripts/eval_recommend_engines.py")
    calls = []

    def engine(*args):
        calls.append(1)
        return {
            "latency_s": 0.1,
            "healthy": True,
            "usage": None,
            "picks": {
                tier: {"model": MARKER, "platform": "synthetic", "settings": {"effort": "low"}}
                for tier in ["cost", "balanced", "quality"]
            },
            "checks": {
                "all_fields": True,
                "sections_parse": True,
                "no_task_leak": True,
                "no_cost_demotion": True,
            },
        }

    monkeypatch.setattr(m, "_run_one", engine)
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", "--out", str(tmp_path / "eval"), "--engines", m.ENGINES[0].key, "--probes", "1"],
    )
    assert m.main() == 0
    logged = capsys.readouterr()
    assert calls == [1] and MARKER not in logged.out + logged.err
    assert MARKER in (tmp_path / "eval.jsonl").read_text()
    assert MARKER in (tmp_path / "eval.md").read_text()
