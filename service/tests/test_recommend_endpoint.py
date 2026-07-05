# service/tests/test_recommend_endpoint.py
from __future__ import annotations

import importlib
import inspect
import sys
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from roadmodel.errors import MalformedResponseError  # type: ignore[import-untyped]

_MODULES_TO_RESET = (
    "app.main",
    "app.recommend",
)

_RECOMMEND_DICT: dict[str, Any] = {
    "model": "Claude Sonnet 4.6",
    "platform": "Claude Code",
    "settings": {"effort": "High", "thinking": "On"},
    "rationale": "Best for coding tasks.",
    "conversation": "New",
    "session_cost_estimate": None,
    "comparison_table": None,
}


_TEST_TOKEN = "test-internal-token"


def _load_main_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", _TEST_TOKEN)
    for module_name in _MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    return importlib.import_module("app.main")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app_main = _load_main_module(monkeypatch)
    # /v1/recommend now requires the shared edge bearer (require_bearer).
    # Send it by default so the existing behavioural tests exercise the
    # authenticated happy path; the auth-specific tests below build their
    # own header-less / wrong-token clients to cover the reject paths.
    return TestClient(
        app_main.app,
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )


def _request_payload(task_description: str = "pick a model") -> dict[str, Any]:
    return {"task_description": task_description}


def test_docs_and_openapi_disabled_on_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    # On a Vercel runtime (VERCEL=1) the interactive docs + OpenAPI schema
    # must be unreachable so the request schema isn't advertised to probers.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("VERCEL", "1")
    for module_name in _MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    app_main = importlib.import_module("app.main")
    raw = TestClient(app_main.app)
    assert raw.get("/openapi.json").status_code == 404
    assert raw.get("/docs").status_code == 404
    assert raw.get("/redoc").status_code == 404


def test_docs_enabled_off_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    # Local/dev (no VERCEL) keeps the docs on for convenience.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("VERCEL", raising=False)
    for module_name in _MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    app_main = importlib.import_module("app.main")
    raw = TestClient(app_main.app)
    assert raw.get("/openapi.json").status_code == 200


def test_recommend_rejects_missing_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    # No Authorization header at all → 401 before any upstream call.
    app_main = _load_main_module(monkeypatch)
    raw = TestClient(app_main.app)
    response = raw.post("/v1/recommend", json=_request_payload())
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_or_missing_bearer"


def test_recommend_rejects_wrong_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wrong token → 401 (constant-time mismatch in require_bearer).
    app_main = _load_main_module(monkeypatch)
    raw = TestClient(app_main.app, headers={"Authorization": "Bearer not-the-token"})
    response = raw.post("/v1/recommend", json=_request_payload())
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_or_missing_bearer"


def test_recommend_503_when_token_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bearer supplied but the server has NO ROADMODEL_INTERNAL_TOKEN set →
    # 503 (fail-closed): a misconfigured service refuses rather than serving
    # a free upstream call.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("ROADMODEL_INTERNAL_TOKEN", raising=False)
    for module_name in _MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    app_main = importlib.import_module("app.main")
    raw = TestClient(app_main.app, headers={"Authorization": "Bearer anything"})
    response = raw.post("/v1/recommend", json=_request_payload())
    assert response.status_code == 503
    assert response.json()["detail"] == "internal_token_unconfigured"


def test_healthz_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.metadata.version", lambda _: "0.2.0")

    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "roadmodel_version"}
    assert body["status"] == "ok"
    assert body["roadmodel_version"] == "0.2.0"


def test_recommend_returns_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")
    call_args: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        call_args["prompt"] = prompt
        call_args["config_provider"] = config.provider
        call_args["input_tokens"] = input_tokens
        call_args["output_tokens"] = output_tokens
        call_args["max_mode"] = max_mode
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert call_args == {
        "prompt": "pick a model",
        "config_provider": "anthropic",
        "input_tokens": None,
        "output_tokens": None,
        "max_mode": False,
    }
    assert body == {
        "model": "Claude Sonnet 4.6",
        "platform": "Claude Code",
        # Claude Code is NOT a no-thinking surface, so settings pass through
        # unchanged (#188 now normalizes only xAI API — Cursor moved to the
        # package's _structured_settings in #2 / roadmodel 0.2.17).
        "settings": {"effort": "High", "thinking": "On"},
        # #173: the model's rationale now survives the service boundary.
        "rationale": "Best for coding tasks.",
        # Structured rationale sections (task/pick/run) default to None when the
        # selector payload omits them (this fake carries only the raw string).
        "rationale_sections": None,
        # #190: the conversation-handling decision now survives too.
        "conversation": "New",
        # The fallback model (Step 7) survives the boundary too; None here
        # because this fake payload emits no backup.
        "backup": None,
        "session_cost_estimate": None,
        "comparison_table": [],
    }


def test_recommend_carries_backup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backup model emitted by recommend_structured survives the service
    boundary. RecommendResponse whitelists fields (extra="forbid"), so an
    undeclared field would be dropped — the same class as rationale (#173)
    and conversation (#190)."""
    recommend_module = importlib.import_module("app.recommend")
    payload = dict(_RECOMMEND_DICT)
    payload["backup"] = "GPT-5.5"

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        del prompt, config, input_tokens, output_tokens, max_mode
        return payload

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    assert response.json()["backup"] == "GPT-5.5"


def _monkeypatch_structured(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    recommend_module = importlib.import_module("app.recommend")

    def _fake(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        return dict(payload)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake)


def test_recommend_cursor_thinking_passes_through(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cursor is NO LONGER normalized to N/A (roadmodel >=0.2.17 / task #2): the
    package's _structured_settings deliberately emits Cursor thinking as "On"
    (Cursor's frontier models reason; the dial it exposes is Max Mode). The
    service must pass that through — listing Cursor in _NO_THINKING_PLATFORMS
    forced the intended "On" back to "N/A" and silently defeated #2 in prod."""
    cursor_dict = dict(_RECOMMEND_DICT)
    cursor_dict["platform"] = "Cursor"
    cursor_dict["settings"] = {"max_mode": "OFF", "thinking": "On"}
    _monkeypatch_structured(monkeypatch, cursor_dict)

    body = client.post("/v1/recommend", json=_request_payload()).json()
    assert body["platform"] == "Cursor"
    assert body["settings"]["thinking"] == "On"
    assert body["settings"]["max_mode"] == "OFF"
    assert body["conversation"] == "New"


def test_recommend_normalizes_thinking_na_on_xai(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """xAI API still exposes no thinking dial and the package passes its THINKING
    through unmodified, so a bogus level the model fills is flattened to N/A here
    (issue #188 — retained for xAI only after Cursor moved to the package)."""
    xai_dict = dict(_RECOMMEND_DICT)
    xai_dict["platform"] = "xAI API"
    xai_dict["settings"] = {"max_mode": "OFF", "thinking": "Medium"}
    _monkeypatch_structured(monkeypatch, xai_dict)

    body = client.post("/v1/recommend", json=_request_payload()).json()
    assert body["platform"] == "xAI API"
    assert body["settings"]["thinking"] == "N/A"


def test_recommend_input_length_cap(client: TestClient) -> None:
    # Cap raised to 50k chars (issue #142). Over-cap input is rejected 422;
    # the web edge mirrors this bound and rejects oversized input as a 400
    # before the request ever reaches the service.
    response = client.post(
        "/v1/recommend",
        json=_request_payload(task_description="a" * 50001),
    )

    assert response.status_code == 422


def test_recommend_rejects_blank_task_description(client: TestClient) -> None:
    """Issue #175: Pydantic min_length=1 counts characters, not stripped
    content, so whitespace-only input (spaces, tabs, newlines) slipped through
    to a paid LLM call. A field_validator now strips and re-checks -> 422. The
    web edge returns 400 for the same case before the upstream fetch."""
    for blank in ("   ", "\t\n  "):
        response = client.post(
            "/v1/recommend",
            json=_request_payload(task_description=blank),
        )
        assert response.status_code == 422, blank


def test_recommend_accepts_large_under_cap(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #142: a 20k-char prompt — rejected under the old 20k cap — is now
    accepted (within the raised 50k bound). Guards against the cap silently
    regressing."""
    recommend_module = importlib.import_module("app.recommend")

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post(
        "/v1/recommend",
        json=_request_payload(task_description="a" * 20000),
    )

    assert response.status_code == 200


def test_response_schema_matches_phase2_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        del prompt, config, input_tokens, output_tokens, max_mode
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "model",
        "platform",
        "settings",
        "rationale",  # #173 — carried through the service boundary
        "rationale_sections",  # structured task/pick/run — carried through, None when absent
        "conversation",  # #190 — same boundary, now carried through
        "backup",  # fallback model (Step 7) — same boundary, carried through
        "session_cost_estimate",
        "comparison_table",
    }


def test_recommend_falls_back_to_next_provider_on_malformed_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #133: a parser failure (MalformedResponseError) on the primary
    provider must fall through to the next provider in the chain instead of
    leaking a 500. Mirrors the 2026-05-31 incident shape where the primary's
    response failed the regex while a fallback could still succeed."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    recommend_module = importlib.import_module("app.recommend")
    attempted: list[str] = []

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        attempted.append(config.provider)
        if config.provider == "anthropic":
            raise MalformedResponseError("ORCHESTRATION: Ultracode\n<unparseable for old regex>")
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    # Primary (anthropic) raised MalformedResponseError; loop fell through to
    # google, which succeeded.
    assert attempted == ["anthropic", "google"]
    assert response.json()["model"] == _RECOMMEND_DICT["model"]


def test_recommend_attempts_all_providers_then_raises_when_all_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #133: when EVERY provider returns an unparseable response (the
    actual 2026-05-31 incident shape — both Gemini and Haiku followed the new
    schema the old regex rejected), the fallback loop must attempt every
    provider and then re-raise MalformedResponseError rather than swallow it.
    The service has no HTTP error mapping, so this surfaces as the same
    unhandled 500 as the pre-existing all-providers-failed path — the drift
    guard (issue #134) is what stops whole-chain schema drift from shipping.
    Tested at the function level since the loop, not the HTTP layer, owns this
    behavior."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    recommend_module = importlib.import_module("app.recommend")
    attempted: list[str] = []

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        attempted.append(config.provider)
        raise MalformedResponseError("<unparseable>")

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    request = recommend_module.RecommendRequest(task_description="pick a model")
    with pytest.raises(MalformedResponseError):
        recommend_module.recommend(request)

    # Every provider in the chain was attempted before the loop re-raised.
    assert attempted == ["anthropic", "google"]


def test_latency_kwargs_passed_only_on_gemini_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issues #132 + #146: the service applies two Gemini-only latency levers
    via recommend_structured on the google path -- thinking_budget=0 (caps the
    default reasoning that dominated P50, #132) and max_output_tokens=768
    (bounds the runaway-rationale P95 tail, #146). NEITHER is passed on the
    anthropic path (Anthropic extended-thinking has different semantics and the
    response shape does not tolerate small caps, per #128). Force each provider
    in turn and capture the kwargs actually passed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, tuple[int | None, int | None, float | None]] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured[config.provider] = (thinking_budget, max_output_tokens, temperature)
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    # Force the Gemini path: both latency kwargs must be the configured caps.
    google_req = recommend_module.RecommendRequest(
        task_description="pick a model",
        context={"force_provider": "google-gemini-2.5-flash"},
    )
    recommend_module.recommend(google_req)
    assert captured["google"] == (
        recommend_module._GEMINI_THINKING_BUDGET,
        recommend_module._GEMINI_MAX_OUTPUT_TOKENS,
        recommend_module._GEMINI_TEMPERATURE,
    )
    assert recommend_module._GEMINI_THINKING_BUDGET == 0
    assert recommend_module._GEMINI_MAX_OUTPUT_TOKENS == 512
    assert recommend_module._GEMINI_TEMPERATURE == 0.0

    # Default chain serves anthropic first: both kwargs must be None there.
    captured.clear()
    anthropic_req = recommend_module.RecommendRequest(task_description="pick a model")
    recommend_module.recommend(anthropic_req)
    assert captured["anthropic"] == (None, None, None)


def test_frontier_gemini_pro_uses_thinking_on_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.5 T3b: the signed-in quality tier forces gemini-2.5-pro, which
    must run with reasoning ON (thinking_budget=512, max_output_tokens=2048) —
    distinct from the free tier's gemini-2.5-flash (0/512). The params key off
    the MODEL, so no separate request flag is needed."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, tuple[int | None, int | None]] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured[config.model] = (thinking_budget, max_output_tokens)
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    # Frontier: gemini-2.5-pro → reasoning-ON params.
    recommend_module.recommend(
        recommend_module.RecommendRequest(
            task_description="pick a model",
            context={"force_provider": "google-gemini-2.5-pro"},
        )
    )
    assert captured["gemini-2.5-pro"] == (
        recommend_module._GEMINI_FRONTIER_THINKING_BUDGET,
        recommend_module._GEMINI_FRONTIER_MAX_OUTPUT_TOKENS,
    )
    assert recommend_module._GEMINI_FRONTIER_THINKING_BUDGET == 512
    assert recommend_module._GEMINI_FRONTIER_MAX_OUTPUT_TOKENS == 2048

    # Free tier: gemini-2.5-flash keeps reasoning OFF + the tight cap.
    captured.clear()
    recommend_module.recommend(
        recommend_module.RecommendRequest(
            task_description="pick a model",
            context={"force_provider": "google-gemini-2.5-flash"},
        )
    )
    assert captured["gemini-2.5-flash"] == (0, 512)


def _fake_returning(model: str, platform: str) -> Any:
    def _fake(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "model": model,
            "platform": platform,
            "settings": {"effort": "High", "thinking": "On"},
            "rationale": "test",
            "conversation": "New",
            "session_cost_estimate": None,
            "comparison_table": None,
        }

    return _fake


def test_recommend_populates_session_cost_for_resolvable_pick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #164: the service now computes session_cost_estimate +
    comparison_table for the recommended pick (the cost panel was always
    empty before because the service never supplied token counts)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    recommend_module = importlib.import_module("app.recommend")
    monkeypatch.setattr(
        recommend_module,
        "recommend_structured",
        _fake_returning("Opus 4.7", "Claude Code"),
    )
    resp = recommend_module.recommend(
        recommend_module.RecommendRequest(task_description="refactor a python service")
    )
    assert resp.session_cost_estimate is not None
    assert "total_usd" in resp.session_cost_estimate
    assert len(resp.comparison_table) >= 1


def test_recommend_cost_degrades_gracefully_when_platform_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cost is best-effort (#164): a pick whose platform isn't in the cost
    catalog must yield an empty cost panel, NOT a 500."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    recommend_module = importlib.import_module("app.recommend")
    monkeypatch.setattr(
        recommend_module,
        "recommend_structured",
        _fake_returning("gemini-2.5-flash", "gemini-api"),
    )
    resp = recommend_module.recommend(
        recommend_module.RecommendRequest(task_description="pick a model")
    )
    assert resp.model == "gemini-2.5-flash"
    assert resp.session_cost_estimate is None
    assert resp.comparison_table == []


def test_recommend_passes_through_rationale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #173: recommend_structured emits the model's reasoning as a
    top-level ``rationale``; the service must carry it into RecommendResponse.
    It previously dropped it (so the web "Why this model?" panel was empty for
    every user) — the same service-boundary drop class as #164."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    recommend_module = importlib.import_module("app.recommend")
    monkeypatch.setattr(
        recommend_module,
        "recommend_structured",
        _fake_returning("Opus 4.7", "Claude Code"),  # returns rationale="test"
    )
    resp = recommend_module.recommend(
        recommend_module.RecommendRequest(task_description="pick a model")
    )
    assert resp.rationale == "test"


def test_recommend_passes_through_rationale_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /recommend redesign: recommend_structured emits best-effort structured
    rationale (task/pick/run) alongside the raw string; the service must carry it
    into RecommendResponse so the web panel can render sub-headings. Same
    service-boundary carry-through as rationale (#173)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    recommend_module = importlib.import_module("app.recommend")
    sections = {
        "task": "Ship an equity research report.",
        "pick": "Fable 5 is S-tier; leads HLE.",
        "run": "Claude Code, XHigh effort, funded by Claude Max.",
    }

    def _fake(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        payload = dict(_RECOMMEND_DICT)
        payload["rationale_sections"] = sections
        return payload

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake)
    resp = recommend_module.recommend(
        recommend_module.RecommendRequest(task_description="pick a model")
    )
    assert resp.rationale_sections == sections
    # The raw string is still carried for the fallback path.
    assert resp.rationale == _RECOMMEND_DICT["rationale"]


def test_recommend_rationale_sections_absent_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When recommend_structured omits rationale_sections — an older roadmodel,
    or a model that ignored the labelled RATIONALE format — the field is None,
    and the web edge falls back to splitting the raw `rationale` string."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    recommend_module = importlib.import_module("app.recommend")
    monkeypatch.setattr(
        recommend_module,
        "recommend_structured",
        _fake_returning("Opus 4.7", "Claude Code"),  # _RECOMMEND_DICT has no sections
    )
    resp = recommend_module.recommend(
        recommend_module.RecommendRequest(task_description="pick a model")
    )
    assert resp.rationale_sections is None


def test_fake_recommend_structured_matches_real_signature() -> None:
    """Contract guard per feedback_monkeypatched_contract_validation. The fakes
    in this file assume recommend_structured(prompt, config, *, user_context_text,
    unavailable_models, input_tokens, output_tokens, max_mode, max_output_tokens,
    thinking_budget, temperature). If
    the real signature drifts, every fake silently diverges and the first live call
    500s — exactly the Phase 3 Step 3 failure mode. Pin the real contract the fakes
    are written against. (thinking_budget was added for the issue #132 Gemini
    latency work; user_context_text for the Phase 4.8 T2b per-user funding context.
    Both are optional keyword-only — the service now passes user_context_text
    (T2b-2 funding wiring) and every fake here accepts it — and the guard must
    track the real signature so a future drift still fails loudly here.)"""
    from roadmodel.recommend import recommend_structured as real  # type: ignore[import-untyped]

    params = inspect.signature(real).parameters
    assert list(params) == [
        "prompt",
        "config",
        "user_context_text",
        "unavailable_models",
        "availability_authoritative",
        "allowed_jurisdictions",
        "input_tokens",
        "output_tokens",
        "max_mode",
        "max_output_tokens",
        "thinking_budget",
        "temperature",
    ]
    # Everything after `config` is keyword-only (declared after the bare *).
    assert params["input_tokens"].kind is inspect.Parameter.KEYWORD_ONLY


def test_funding_context_is_threaded_to_recommend_structured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.8 T2b: whatever the per-user funding builder returns is passed to
    recommend_structured as user_context_text, so model SELECTION sees the user's
    funding. (Builder CONTENT is covered hermetically in test_funding.py; this
    pins the service PLUMBING — that req.context reaches the builder and its
    output reaches the recommender.)"""
    recommend_module = importlib.import_module("app.recommend")
    seen: dict[str, Any] = {}

    def _fake_from_request(context: Any) -> str:
        seen["context"] = context
        return "SENTINEL-FUNDING-CONTEXT"

    captured: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured["user_context_text"] = user_context_text
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "user_context_from_request", _fake_from_request)
    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    ctx = {"subscriptions": ["claude-max"], "api_providers": ["deepseek"]}
    response = client.post(
        "/v1/recommend", json={"task_description": "pick a model", "context": ctx}
    )

    assert response.status_code == 200
    assert seen["context"] == ctx
    assert captured["user_context_text"] == "SENTINEL-FUNDING-CONTEXT"


def test_unavailable_models_threaded_to_recommend_structured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.9 B2: the runtime unavailable-ids the web edge forwards in context
    reach recommend_structured as the Step-0a override, cleaned (blanks /
    non-strings dropped, order preserved)."""
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured["unavailable_models"] = unavailable_models
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    ctx = {"unavailable_models": ["claude-fable-5", "  ", 123, "gpt-x"]}
    response = client.post(
        "/v1/recommend", json={"task_description": "pick a model", "context": ctx}
    )

    assert response.status_code == 200
    assert captured["unavailable_models"] == ["claude-fable-5", "gpt-x"]


def test_availability_authoritative_threaded_to_recommend_structured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.9 B5: the web edge's authoritative flag (the table read succeeded)
    reaches recommend_structured. True -> the forwarded list supersedes the bundled
    fallback so a restored model is recommendable; absent -> False (fail-closed)."""
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured["authoritative"] = availability_authoritative
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    # Explicit True -> forwarded True.
    client.post(
        "/v1/recommend",
        json={"task_description": "pick a model", "context": {"availability_authoritative": True}},
    )
    assert captured["authoritative"] is True

    # Absent (or non-True) -> fail-closed default False.
    client.post("/v1/recommend", json={"task_description": "pick a model", "context": {}})
    assert captured["authoritative"] is False


def test_no_unavailable_models_passes_none(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No unavailable_models in context (legacy / direct caller) -> None, so only
    the bundled <availability-context> defaults apply."""
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured["unavailable_models"] = unavailable_models
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)
    client.post("/v1/recommend", json={"task_description": "x"})
    assert captured["unavailable_models"] is None


def test_no_funding_passes_none_user_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anon / no-funding requests pass user_context_text=None so the bundled
    template is used and the free path is unchanged (T2b guardrail). Exercises
    the REAL builder's None short-circuit end-to-end (no monkeypatch on it)."""
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, Any] = {}

    def _fake_recommend_structured(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        max_mode: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured["user_context_text"] = user_context_text
        return dict(_RECOMMEND_DICT)

    monkeypatch.setattr(recommend_module, "recommend_structured", _fake_recommend_structured)

    response = client.post("/v1/recommend", json=_request_payload())

    assert response.status_code == 200
    assert captured["user_context_text"] is None


# --- /v1/recommend/ladder (tasks #1/#3) --------------------------------------


def _ladder_pick(model: str, platform: str, effort: str) -> dict[str, Any]:
    return {
        "model": model,
        "platform": platform,
        "settings": {"effort": effort, "thinking": "On"},
        "rationale": f"TASK: Coding. PICK: {model}. RUN: {platform}.",
        "conversation": "New",
        "session_cost_estimate": None,
        "comparison_table": None,
    }


def test_ladder_endpoint_returns_three_anchored_picks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")
    captured: dict[str, Any] = {}

    def _fake_ladder(
        prompt: str,
        config: Any,
        *,
        user_context_text: str | None = None,
        unavailable_models: list[str] | None = None,
        availability_authoritative: bool = False,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        captured["prompt"] = prompt
        captured["max_output_tokens"] = max_output_tokens
        return {
            "picks": {
                "quality": _ladder_pick("Opus 4.8", "Claude Code", "Max"),
                "balanced": _ladder_pick("Sonnet 4.6", "Claude Code", "High"),
                "cost": _ladder_pick("Composer 2.5", "Cursor", "Low"),
            },
            "guard": {
                "duplicate_models": False,
                "misordered": False,
                "distinct_tiers": True,
                "healthy": True,
            },
        }

    monkeypatch.setattr(recommend_module, "recommend_structured_ladder", _fake_ladder)

    response = client.post("/v1/recommend/ladder", json=_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert set(body["picks"]) == {"quality", "balanced", "cost"}
    assert body["picks"]["quality"]["model"] == "Opus 4.8"
    assert body["picks"]["balanced"]["model"] == "Sonnet 4.6"
    assert body["picks"]["cost"]["model"] == "Composer 2.5"
    # Each pick is shaped like a single RecommendResponse (rationale carried).
    assert body["picks"]["quality"]["rationale"].startswith("TASK:")
    # The deterministic guard rides along for the edge's fallback decision.
    assert body["guard"]["healthy"] is True
    # Ladder mode lifts the Gemini output cap (~3x) for the three-block body —
    # but the anthropic default hint passes None (no Gemini cap). Assert the call
    # was made; cap behavior is covered by the package-level tests.
    assert captured["prompt"] == "pick a model"


def test_ladder_endpoint_requires_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    app_main = _load_main_module(monkeypatch)
    raw = TestClient(app_main.app)
    response = raw.post("/v1/recommend/ladder", json=_request_payload())
    assert response.status_code == 401


def test_ladder_endpoint_carries_backup_and_guard(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommend_module = importlib.import_module("app.recommend")

    def _fake_ladder(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        quality = _ladder_pick("Opus 4.8", "Claude Code", "Max")
        quality["backup"] = "GPT-5.5"
        return {
            "picks": {
                "quality": quality,
                "balanced": _ladder_pick("Sonnet 4.6", "Claude Code", "High"),
                "cost": _ladder_pick("Composer 2.5", "Cursor", "Low"),
            },
            "guard": {"healthy": True, "distinct_tiers": True},
        }

    monkeypatch.setattr(recommend_module, "recommend_structured_ladder", _fake_ladder)

    body = client.post("/v1/recommend/ladder", json=_request_payload()).json()
    assert body["picks"]["quality"]["backup"] == "GPT-5.5"
    assert body["guard"]["distinct_tiers"] is True
