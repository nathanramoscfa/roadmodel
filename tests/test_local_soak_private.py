"""Private soak output contracts; no actual model, auth, notification, or workflow run."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def judge(monkeypatch):
    m = load("synthetic_judge_contract", ROOT / "scripts/judge_recommend.py")

    def blocked(*a, **k):
        raise AssertionError("Unexpected external operation")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(m.subprocess, "run", blocked)
    monkeypatch.setattr(m, "load_probes", lambda: [])
    monkeypatch.setattr(m, "bundled_context", lambda: "")
    monkeypatch.setattr(m, "unavailable_ids", lambda: [])
    monkeypatch.setattr(m._cost, "_load_catalog", lambda: {})
    monkeypatch.setattr(m.scoring, "ladder_table", lambda *a, **k: {})
    monkeypatch.setattr(m, "controls", lambda *a: [])
    monkeypatch.setattr(m, "system_prompt", lambda *a: "")
    monkeypatch.setattr(m, "b2_check", lambda *a: m.Check("synthetic-b2", "B2", True, "synthetic"))
    return m


def test_workflow_passes_exact_producer_path_to_judge(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/recommend-soak.yml").read_text())
    step = next(s for s in workflow["jobs"]["soak"]["steps"] if s.get("id") == "judge")
    # Execute ONLY the one argv-construction command, with python replaced by a
    # shell function. Never run the pipeline, real Python, judge, issue steps.
    line = next(
        line.strip()
        for line in step["run"].splitlines()
        if line.strip().startswith("python scripts/judge_recommend.py")
    )
    line = line.split(" 2>&1 |", 1)[0]
    assert "scripts/judge_recommend.py" in line and "`" not in line and "$(" not in line
    directory = tmp_path / "private path with spaces"
    directory.mkdir(mode=0o700)
    rows = directory / "rows.jsonl"
    judge = directory / "judge.json"
    capture = directory / "argv"
    script = 'python(){ printf "%s\\0" "$@" > "$CAPTURE"; }; FLAG="--no-judge"; ' + line
    env = {
        "PATH": os.environ["PATH"],
        "SOAK_OUT": str(rows),
        "SOAK_JUDGE_OUT": str(judge),
        "CAPTURE": str(capture),
    }
    result = subprocess.run(
        ["bash", "-c", script], env=env, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0
    args = capture.read_bytes().decode().rstrip("\0").split("\0")
    assert args[args.index("--rows") + 1] == str(rows)
    assert args[args.index("--out") + 1] == str(judge)
    assert args[-1] == "--no-judge"


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_judge_output_preflight_precedes_any_judge_call(judge, monkeypatch, tmp_path, link_kind):
    m = judge
    tmp_path.chmod(0o700)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("")
    target = tmp_path / "sentinel"
    target.write_text("untouched")
    target.chmod(0o600)
    out = tmp_path / "judge.json"
    out.symlink_to(target) if link_kind == "symlink" else os.link(target, out)
    calls = []
    monkeypatch.setattr(m, "claude_judge", lambda *a: lambda *a: None)
    monkeypatch.setattr(m, "judge_all", lambda *a, **k: calls.append(1) or {})
    monkeypatch.setattr(m, "b6_check", lambda *a: m.Check("synthetic-b6", "B6", True, "synthetic"))
    try:
        m.main(["--rows", str(rows), "--out", str(out)])
    except (SystemExit, OSError, ValueError):
        pass
    assert calls == []
    assert target.read_text() == "untouched"


def test_judge_output_is_private_under_permissive_umask(judge, tmp_path):
    tmp_path.chmod(0o700)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("")
    out = tmp_path / "judge.json"
    before = os.umask(0)
    try:
        assert judge.main(["--rows", str(rows), "--out", str(out), "--no-judge"]) == 0
    finally:
        os.umask(before)
    assert out.stat().st_mode & 0o777 == 0o600
    assert set(json.loads(out.read_text())) == {
        "roadmodel_version",
        "judge_model",
        "judge_list_cost_usd",
        "checks",
        "b2",
        "verdicts",
    }


@pytest.fixture
def gold(judge, monkeypatch):
    # Import resolves judge_recommend through its actual sibling module name.
    monkeypatch.setitem(sys.modules, "judge_recommend", judge)
    m = load("synthetic_gold_contract", ROOT / "scripts/gold_differential.py")
    monkeypatch.setattr(m.jr, "load_probes", lambda: [{"id": "synthetic"}])
    monkeypatch.setattr(m, "diff", lambda *a: [])
    return m


@pytest.mark.parametrize("destination", ["gold", "out"])
def test_gold_destinations_preflight_precedes_any_model_call(
    gold, monkeypatch, tmp_path, destination
):
    m = gold
    tmp_path.chmod(0o700)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("")
    target = tmp_path / "sentinel"
    target.write_text("{}")
    target.chmod(0o600)
    cache = tmp_path / "gold.json"
    out = tmp_path / "diff.json"
    (cache if destination == "gold" else out).symlink_to(target)
    calls = []
    monkeypatch.setattr(
        m, "run_gold", lambda *a: calls.append(1) or {"synthetic": {"model": "synthetic"}}
    )
    try:
        m.main(["--rows", str(rows), "--gold", str(cache), "--out", str(out)])
    except (SystemExit, OSError, ValueError):
        pass
    assert calls == []
    assert target.read_text() == "{}"


def test_gold_existing_private_cache_is_reusable(gold, monkeypatch, tmp_path):
    m = gold
    tmp_path.chmod(0o700)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("")
    cache = tmp_path / "gold.json"
    out = tmp_path / "diff.json"
    raw = json.dumps({"synthetic": {"model": "synthetic"}}) + "\n"
    cache.write_text(raw)
    cache.chmod(0o600)

    def blocked(*a, **k):
        raise AssertionError("Cached gold must not call the model")

    monkeypatch.setattr(m, "run_gold", blocked)
    assert m.main(["--rows", str(rows), "--gold", str(cache), "--out", str(out)]) == 0
    assert cache.read_text() == raw
    assert set(json.loads(out.read_text())) == {"all", "t1_battery", "rows"}


def test_gold_adds_one_missing_probe_without_losing_existing_cache(gold, monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    rows = tmp_path / "rows.jsonl"
    rows.write_text("")
    cache = tmp_path / "gold.json"
    old = {"synthetic": {"model": "preserved synthetic model"}}
    cache.write_text(json.dumps(old))
    cache.chmod(0o600)
    monkeypatch.setattr(gold.jr, "load_probes", lambda: [{"id": "synthetic"}, {"id": "second"}])
    calls = []

    def run(probes, model, concurrency):
        calls.append([p["id"] for p in probes])
        return {"second": {"model": "additional synthetic model"}}

    monkeypatch.setattr(gold, "run_gold", run)
    assert gold.main(["--rows", str(rows), "--gold", str(cache)]) == 0
    assert calls == [["second"]]
    assert json.loads(cache.read_text()) == {
        **old,
        "second": {"model": "additional synthetic model"},
    }
    assert cache.stat().st_mode & 0o777 == 0o600
    assert gold.main(["--rows", str(rows), "--gold", str(cache)]) == 0
    assert calls == [["second"]]
