"""Exercise actual authenticated callables through urllib's real redirect logic."""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("status", [200, 301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "target", ["https://receiver.invalid/target", "http://receiver.invalid/target"]
)
@pytest.mark.parametrize(
    "caller",
    [
        "funding",
        "keyless",
        "sync_get",
        "sync_post",
        "sync_delete",
        "anthropic",
        "openai",
        "google",
        "collector",
        "watcher",
        "eval",
        "pool",
    ],
)
def test_authenticated_calls_never_follow_redirects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int, target: str, caller: str
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    calls: list[urllib.request.Request] = []
    real_builder = urllib.request.build_opener

    def response(request: urllib.request.Request) -> Any:
        calls.append(request)
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Location"] = target
        if caller == "funding":
            data: Any = []
        elif caller == "collector":
            data = {"data": {"limit": 20, "limit_remaining": 10}}
        else:
            data = {
                "data": [{"id": "synthetic-model"}],
                "models": [{"name": "models/synthetic-model"}],
                "result": None,
            }
        # A denied redirect body must not misclassify a provider as unavailable.
        payload = b"not found" if status != 200 else json.dumps(data).encode()
        result = urllib.response.addinfourl(io.BytesIO(payload), headers, request.full_url, status)
        result.msg = "Synthetic response"
        return result

    class HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request: urllib.request.Request) -> Any:
            return response(request)

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, request: urllib.request.Request) -> Any:
            return response(request)

    def build(*handlers: Any) -> urllib.request.OpenerDirector:
        return real_builder(urllib.request.ProxyHandler({}), HTTPS(), HTTP(), *handlers)

    monkeypatch.setattr(urllib.request, "build_opener", build)
    # Old urlopen callers use the same synthetic transport in fail-before runs.
    monkeypatch.setattr(urllib.request, "_opener", build())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("Real network"))
    credential = "synthetic-credential"
    try:
        if caller == "funding":
            m = load("redirect_funding", "scripts/check_funding_invariant.py")
            m.postgrest_page("https://database.invalid", credential)("2000-01-01", 0, 10)
        elif caller == "keyless":
            m = load("redirect_keyless", "scripts/eval_keyless_agreement.py")
            m._post("https://service.invalid", "/synthetic", {}, credential, 30)
        elif caller.startswith("sync_"):
            m = load("redirect_sync", "update/sync_availability.py")
            m._request(
                caller[5:].upper(),
                "https://database.invalid/rest/v1/model_availability",
                credential,
                [],
            )
        elif caller in ("anthropic", "openai", "google"):
            m = load("redirect_probe", "update/probe_availability.py")
            result = (
                m.probe_invoke("synthetic-model", credential)
                if caller == "anthropic"
                else m.fetch_model_list(caller, credential)
            )
            if status != 200:
                assert result == ("ambiguous" if caller == "anthropic" else None)
        elif caller == "watcher":
            m = load("redirect_watcher", "scripts/gate-alert-watcher.py")
            m._rpop("https://queue.invalid", credential)
        elif caller == "collector":
            m = load("redirect_collector", "scripts/collect_openrouter_pool.py")
            monkeypatch.setattr(
                m.subprocess,
                "run",
                lambda argv, **kw: subprocess.CompletedProcess(argv, 0, credential.encode()),
            )
            cache = tmp_path / "cache"
            cache.mkdir(mode=0o700)
            snapshot = cache / "openrouter.json"
            snapshot.write_bytes(b"previous snapshot")
            before = snapshot.stat().st_mtime_ns
            monkeypatch.setattr(sys, "argv", ["collector", "--cache", str(cache)])
            assert m.main() == (0 if status == 200 else 1)
            if status != 200:
                assert snapshot.read_bytes() == b"previous snapshot"
                assert snapshot.stat().st_mtime_ns == before
        elif caller == "pool":
            m = load("redirect_pool", "scripts/push_pool_status.py")
            m.request("https://database.invalid/path", credential, credential)
        else:
            m = load("redirect_eval", "scripts/eval_recommend_engines.py")
            result = m._run_via_service(
                m.ENGINES[0], "synthetic prompt", "https://service.invalid", credential
            )
            if status != 200:
                assert result["error"] == f"HTTP {status}"
    except urllib.error.HTTPError as error:
        assert status != 200 and error.code == status
    assert len(calls) == 1
    assert calls[0].host != "receiver.invalid"
