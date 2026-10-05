# service/tests/test_visitor_endpoint.py
"""The visitor lane (app/visitor.py): one ladder call on the visitor's own key.

The guarantees under test:

- the call runs on the visitor's key and the resolved engine, exactly once,
  with no fallback chain: a failing visitor key never reaches an adapter with
  an environment (operator) key;
- provider failures map to visitor_key_rejected / visitor_quota /
  provider_error, with bodies that carry the code and provider only;
- a canary key pushed through every path appears in no captured log, response
  body or response header.

The provider adapters themselves are replaced by recording fakes, so the real
package path (Config -> recommend_structured_ladder -> PROVIDER_ADAPTERS) runs
end to end and every adapter invocation is counted by the key it received.
Fixture keys are fake and assembled at runtime, never committed as a literal.
"""

from __future__ import annotations

import importlib
import logging
import secrets
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from roadmodel import recommend as package_recommend  # type: ignore[import-untyped]
from roadmodel.errors import ProviderCallError  # type: ignore[import-untyped]

_TOKEN = "test-internal-token"
_PATH = "/v1/visitor/recommend/ladder"
_PROVIDERS = ("openai", "google", "anthropic", "openrouter")


def _fake_key(prefix: str) -> str:
    # Assembled at runtime from parts, so no secret-shaped literal is committed.
    return "-".join([prefix, "canary", "0411", secrets.token_hex(12)])


# The canary: an OpenAI-shaped key no provider will ever issue.
CANARY = _fake_key("sk")
VISITOR_KEYS = {
    "openai": CANARY,
    "google": "AIza" + secrets.token_hex(16),
    "anthropic": _fake_key("sk-ant"),
    "openrouter": _fake_key("sk-or-v1"),
}
# The operator's environment keys, each a distinct sentinel, so a call that
# reached one is unmistakable.
ENV_KEYS = {
    "OPENAI_API_KEY": "env-sentinel-openai",
    "GOOGLE_API_KEY": "env-sentinel-google",
    "ANTHROPIC_API_KEY": "env-sentinel-anthropic",
    "OPENROUTER_API_KEY": "env-sentinel-openrouter",
}

_LADDER_TEXT = """\
TIER: QUALITY
MODEL: Test Frontier Model
BACKUP: None
PLATFORM: Claude Code
EFFORT: High
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: the strongest model. EFFORT: High for a hard task.

TIER: BALANCED
MODEL: Test Middle Model
BACKUP: None
PLATFORM: Claude Code
EFFORT: Medium
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: the best value. EFFORT: Medium clears it.

TIER: COST
MODEL: Test Small Model
BACKUP: None
PLATFORM: Claude Code
EFFORT: Low
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: the cheapest that does the job. EFFORT: Low.
"""


class _StatusError(Exception):
    """Stands in for an SDK's HTTP error: carries the status as the OpenAI and
    Anthropic SDKs do (``status_code``) or as Google's does (``code``)."""

    def __init__(self, message: str, *, status_code: int | None = None, code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class _Recorder:
    """Every adapter invocation, as (provider, model, api_key)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []
        self.behaviour: Callable[[str, str], str] = lambda _provider, _key: _LADDER_TEXT

    def adapter(self, provider: str) -> ModuleType:
        recorder = self

        def recommend(
            prompt: str,
            system: str,
            *,
            model: str | None = None,
            api_key: str,
            max_output_tokens: int | None = None,
            thinking_budget: int | None = None,
            temperature: float | None = None,
        ) -> str:
            recorder.calls.append((provider, model, api_key))
            return recorder.behaviour(provider, api_key)

        module = ModuleType(f"fake_{provider}_adapter")
        module.recommend = recommend  # type: ignore[attr-defined]
        return module

    def keys(self) -> list[str]:
        return [key for _, _, key in self.calls]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    for provider in _PROVIDERS:
        monkeypatch.setitem(package_recommend.PROVIDER_ADAPTERS, provider, rec.adapter(provider))
    return rec


def _load_main(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for name, value in ENV_KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", _TOKEN)
    for module_name in ("app.main", "app.recommend", "app.visitor"):
        sys.modules.pop(module_name, None)
    return importlib.import_module("app.main")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> TestClient:
    return TestClient(_load_main(monkeypatch).app, headers={"Authorization": f"Bearer {_TOKEN}"})


def _post(
    client: TestClient,
    provider: str | None,
    key: str | None,
    *,
    engine: str | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if provider is not None:
        headers["X-Roadmodel-Visitor-Provider"] = provider
    if key is not None:
        headers["X-Roadmodel-Visitor-Key"] = key
    body: dict[str, Any] = {"task_description": "refactor a data pipeline"}
    if engine is not None:
        body["context"] = {"force_provider": engine}
    return client.post(_PATH, json=body, headers=headers)


def _assert_no_canary(response: Any, caplog: pytest.LogCaptureFixture, key: str = CANARY) -> None:
    assert key not in response.text
    for name, value in response.headers.items():
        assert key not in name and key not in value
    assert key not in caplog.text
    for record in caplog.records:
        assert key not in record.getMessage()
        assert key not in (record.exc_text or "")


def _raising(status: int | None = None, *, google_code: int | None = None, text: str = "") -> Any:
    """An adapter behaviour that fails the way the real adapters do: a
    ProviderCallError whose message carries the SDK's text (which echoes the
    key) raised from the SDK's status error."""

    def behaviour(provider: str, key: str) -> str:
        message = text or f"Error code: {status} - Incorrect API key provided: {key}"
        cause = _StatusError(message, status_code=status, code=google_code)
        raise ProviderCallError(f"{provider} API call failed: {cause}") from cause

    return behaviour


# --- Happy path ---------------------------------------------------------------


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_one_call_on_the_visitor_key_and_the_provider_default_engine(
    client: TestClient,
    recorder: _Recorder,
    provider: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    key = VISITOR_KEYS[provider]
    response = _post(client, provider, key)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["picks"]) == {"quality", "balanced", "cost"}
    from app.engines import REGISTRY

    default = REGISTRY.engines[REGISTRY.visitor_defaults[provider]]
    assert body["engine"] == default.hint
    # Exactly one adapter call, on the visitor's key and the resolved model.
    assert recorder.calls == [(provider, default.model, key)]
    _assert_no_canary(response, caplog, key)


def test_an_evaluated_engine_of_the_key_provider_runs_even_on_the_founder_tier(
    client: TestClient, recorder: _Recorder
) -> None:
    # Opus 5.5 is founder-only on the operator's account; the visitor pays.
    response = _post(
        client, "anthropic", VISITOR_KEYS["anthropic"], engine="anthropic-claude-opus-5-5"
    )
    assert response.status_code == 200
    assert response.json()["engine"] == "anthropic-claude-opus-5-5"
    assert recorder.calls == [("anthropic", "claude-opus-5-5", VISITOR_KEYS["anthropic"])]


@pytest.mark.parametrize(
    "engine",
    [
        # Another provider's engine: the key cannot pay for it.
        "openai-gpt-6.1-sol",
        # No passing eval record: not offered.
        "anthropic-haiku-4-5",
        # Not an engine at all.
        "anthropic-nope",
    ],
)
def test_any_other_requested_engine_runs_the_provider_default(
    client: TestClient, recorder: _Recorder, engine: str
) -> None:
    response = _post(client, "anthropic", VISITOR_KEYS["anthropic"], engine=engine)
    assert response.status_code == 200
    assert response.json()["engine"] == "anthropic-claude-haiku-4-5"
    assert [p for p, _, _ in recorder.calls] == ["anthropic"]


# --- OpenRouter: the real OpenAI-compatible adapter ---------------------------


class _FakeOpenAI:
    """Stands in for the openai SDK client the compatible adapter builds:
    records each client (its key and endpoint) and each create() call."""

    clients: list[dict[str, Any]] = []
    creates: list[dict[str, Any]] = []
    answer: Callable[[], Any] = staticmethod(lambda: None)

    def __init__(self, **kwargs: Any) -> None:
        _FakeOpenAI.clients.append(kwargs)
        self.chat = self
        self.completions = self

    def create(self, **kwargs: Any) -> Any:
        _FakeOpenAI.creates.append(kwargs)
        return _FakeOpenAI.answer()


def _completion(text: str) -> Any:
    from types import SimpleNamespace

    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


@pytest.fixture
def openrouter_sdk(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> type[_FakeOpenAI]:
    """The real openrouter adapter (the recorder's fake undone) over a fake SDK."""
    import openai
    from roadmodel.providers import openai_compatible  # type: ignore[import-untyped]

    monkeypatch.setitem(
        package_recommend.PROVIDER_ADAPTERS, "openrouter", openai_compatible.ADAPTERS["openrouter"]
    )
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    _FakeOpenAI.clients, _FakeOpenAI.creates = [], []
    _FakeOpenAI.answer = staticmethod(lambda: _completion(_LADDER_TEXT))
    return _FakeOpenAI


def test_openrouter_runs_the_compatible_adapter_on_the_visitor_key_once(
    client: TestClient,
    recorder: _Recorder,
    openrouter_sdk: type[_FakeOpenAI],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    key = VISITOR_KEYS["openrouter"]
    response = _post(client, "openrouter", key)
    assert response.status_code == 200, response.text
    assert response.json()["engine"] == "openrouter-gpt-6-luna"
    # One client, on the visitor's key, at OpenRouter's endpoint; one call, on
    # OpenRouter's id for GPT-6 Luna. No other adapter ran.
    assert openrouter_sdk.clients == [{"api_key": key, "base_url": "https://openrouter.ai/api/v1"}]
    assert [c["model"] for c in openrouter_sdk.creates] == ["openai/gpt-6-luna"]
    assert recorder.calls == []
    _assert_no_canary(response, caplog, key)


@pytest.mark.parametrize(
    ("status", "http", "code"),
    [
        (401, 401, "visitor_key_rejected"),
        # OpenRouter: out of credits.
        (402, 429, "visitor_quota"),
        (429, 429, "visitor_quota"),
        (500, 502, "provider_error"),
    ],
)
def test_an_openrouter_failure_maps_from_the_sdk_status_with_no_fallback(
    client: TestClient,
    recorder: _Recorder,
    openrouter_sdk: type[_FakeOpenAI],
    caplog: pytest.LogCaptureFixture,
    status: int,
    http: int,
    code: str,
) -> None:
    """The compatible adapter wraps the SDK's APIStatusError, whose
    status_code visitor.classify reads; the call is never retried elsewhere."""
    import httpx
    import openai

    caplog.set_level(logging.DEBUG)
    key = VISITOR_KEYS["openrouter"]

    def fail() -> Any:
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        raise openai.APIStatusError(
            f"Error code: {status} - key {key} refused",
            response=httpx.Response(status, request=request),
            body=None,
        )

    openrouter_sdk.answer = staticmethod(fail)
    response = _post(client, "openrouter", key)
    assert response.status_code == http
    assert response.json() == {"error": code, "provider": "openrouter"}
    assert len(openrouter_sdk.creates) == 1
    assert {c["api_key"] for c in openrouter_sdk.clients} == {key}
    assert recorder.calls == []
    _assert_no_canary(response, caplog, key)


def test_the_response_carries_the_timing_header(client: TestClient) -> None:
    response = _post(client, "openai", CANARY)
    assert response.headers["X-Roadmodel-Timing"].startswith("service_scoring_ms=")


# --- Failures: mapped, scrubbed, never retried --------------------------------


@pytest.mark.parametrize(
    ("behaviour", "status", "code"),
    [
        (_raising(401), 401, "visitor_key_rejected"),
        (_raising(403), 401, "visitor_key_rejected"),
        (_raising(429), 429, "visitor_quota"),
        (_raising(500), 502, "provider_error"),
        (_raising(None), 502, "provider_error"),
        # Anthropic: an exhausted prepaid balance is a 400.
        (_raising(400, text="Your credit balance is too low"), 429, "visitor_quota"),
    ],
)
def test_provider_failures_map_to_codes_only(
    client: TestClient,
    recorder: _Recorder,
    caplog: pytest.LogCaptureFixture,
    behaviour: Any,
    status: int,
    code: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    recorder.behaviour = behaviour
    response = _post(client, "openai", CANARY)
    assert response.status_code == status
    assert response.json() == {"error": code, "provider": "openai"}
    _assert_no_canary(response, caplog)


def test_google_answers_an_invalid_key_with_400_which_maps_to_rejected(
    client: TestClient, recorder: _Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    recorder.behaviour = _raising(
        google_code=400, text="400 INVALID_ARGUMENT. API key not valid. reason: API_KEY_INVALID"
    )
    response = _post(client, "google", VISITOR_KEYS["google"])
    assert response.status_code == 401
    assert response.json() == {"error": "visitor_key_rejected", "provider": "google"}
    _assert_no_canary(response, caplog, VISITOR_KEYS["google"])


def test_an_unparseable_answer_is_a_provider_error(client: TestClient, recorder: _Recorder) -> None:
    recorder.behaviour = lambda _p, _k: "no tiers here"
    response = _post(client, "openai", CANARY)
    assert response.status_code == 502
    assert response.json() == {"error": "provider_error", "provider": "openai"}
    assert len(recorder.calls) == 1


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_a_failing_visitor_key_never_reaches_an_environment_key(
    client: TestClient,
    recorder: _Recorder,
    caplog: pytest.LogCaptureFixture,
    provider: str,
) -> None:
    """The core invariant: the operator path falls back down a provider chain
    on any provider error; the visitor path makes one call and stops."""
    recorder.behaviour = _raising(401)
    key = VISITOR_KEYS[provider]
    response = _post(client, provider, key)
    assert response.status_code == 401
    assert recorder.keys() == [key]
    for env_key in ENV_KEYS.values():
        assert env_key not in recorder.keys()
    _assert_no_canary(response, caplog, key)


def test_an_unexpected_exception_is_a_scrubbed_provider_error(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"something echoed the key {CANARY}")

    monkeypatch.setattr("app.visitor.ladder_once", boom)
    response = _post(client, "openai", CANARY)
    assert response.status_code == 502
    assert response.json() == {"error": "provider_error", "provider": "openai"}
    _assert_no_canary(response, caplog)


def test_a_log_line_that_carries_the_key_is_scrubbed(
    client: TestClient, recorder: _Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    """Whatever logs inside the request (an SDK's retry message, a traceback)
    has the key replaced, through any logger."""
    caplog.set_level(logging.DEBUG)

    def chatty(provider: str, key: str) -> str:
        logging.getLogger("openai._base_client").warning("retrying request with key %s", key)
        logging.getLogger("httpx").info(f"Authorization: Bearer {key}")
        try:
            raise ValueError(f"bad key {key}")
        except ValueError:
            logging.getLogger("some.sdk").exception("request failed")
        return _LADDER_TEXT

    recorder.behaviour = chatty
    response = _post(client, "openai", CANARY)
    assert response.status_code == 200
    assert "[visitor-key]" in caplog.text
    _assert_no_canary(response, caplog)


def test_the_filter_scrubs_any_key_shaped_token_and_is_on_the_root_logger() -> None:
    from app.visitor import VisitorKeyFilter, scrub

    assert any(isinstance(f, VisitorKeyFilter) for f in logging.getLogger().filters)
    google = "AIza" + secrets.token_hex(16)
    anthropic = _fake_key("sk-ant")
    openrouter = _fake_key("sk-or-v1")
    text = f"a {CANARY} b {google} c {anthropic} d {openrouter}"
    assert scrub(text) == "a [visitor-key] b [visitor-key] c [visitor-key] d [visitor-key]"


# --- Rejected before any call -------------------------------------------------


@pytest.mark.parametrize("provider", [None, "", "together", "deepseek", "custom"])
def test_an_unsupported_provider_is_400_with_zero_adapter_calls(
    client: TestClient, recorder: _Recorder, provider: str | None
) -> None:
    response = _post(client, provider, CANARY)
    assert response.status_code == 400
    assert response.json()["error"] == "visitor_provider_unsupported"
    assert recorder.calls == []
    assert CANARY not in response.text


@pytest.mark.parametrize("key", [None, "", "   "])
def test_a_missing_key_is_400_with_zero_adapter_calls(
    client: TestClient, recorder: _Recorder, key: str | None
) -> None:
    response = _post(client, "openai", key)
    assert response.status_code == 400
    assert response.json() == {"error": "visitor_key_missing", "provider": "openai"}
    assert recorder.calls == []


def test_the_endpoint_requires_the_edge_bearer(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    app_main = _load_main(monkeypatch)
    for headers in ({}, {"Authorization": "Bearer not-the-token"}):
        raw = TestClient(app_main.app, headers=headers)
        response = _post(raw, "openai", CANARY)
        assert response.status_code == 401
        assert CANARY not in response.text
    assert recorder.calls == []


def test_healthz_lists_the_visitor_key_capability(client: TestClient) -> None:
    assert "visitor-key" in client.get("/healthz").json()["capabilities"]
