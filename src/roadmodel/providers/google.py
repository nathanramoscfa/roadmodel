# src/roadmodel/providers/google.py
from __future__ import annotations

import re
from typing import Any

from roadmodel import usage
from roadmodel.errors import ProviderCallError
from roadmodel.providers._safety import hosted_timeout, private_transport, safe_error

# The package's own engine when no model is named (`roadmodel recommend`, the MCP
# server, an SDK caller): one of service/app/engines.json's evaluated engines,
# with the settings docs/engine-eval.json measured it at. The settings apply only
# to that default; a named model runs with whatever the caller passes.
# tests/test_engine_eval_mirror.py holds all three to the registry.
# It must be callable by a NEW key: Google answers 404 NOT_FOUND to a project
# that never used an older model, so `gemini-2.5-pro` (the default until
# 0.2.90) and `gemini-3.1-pro` fail there while still working for keys that
# used them before. Thinking level low and temperature 0 (#176) are how the
# eval ran it (p50 2.5 s); left unset, the model thought at its default level
# and a recommendation took about 30 s.
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_THINKING_BUDGET: int | None = 0
DEFAULT_TEMPERATURE: float | None = 0.0

# The 2.x generation takes a numeric thinking_budget; from Gemini 3 on, the API
# documents discrete thinking LEVELS instead (update/gemini-thinking.json), so a
# numeric budget is not the dial those models expose.
_BUDGET_GENERATION_RE = re.compile(r"^gemini-[12](?:\.|-)")


def _thinking_config(model_id: str, thinking_budget: int) -> dict[str, Any]:
    """The thinking dial for this model: the numeric budget on the 2.x models,
    a level on Gemini 3 and later. `low` is the floor every Gemini 3 model
    accepts (3.8 Flash, 3.7 Flash and 3.1 Pro have no `minimal`), so a budget of
    0 (the recommender's "as fast as possible") maps to it; larger budgets map to
    the level whose spend they are closest to."""
    if _BUDGET_GENERATION_RE.match(model_id):
        return {"thinking_budget": thinking_budget}
    if thinking_budget <= 1024:
        return {"thinking_level": "low"}
    if thinking_budget <= 8192:
        return {"thinking_level": "medium"}
    return {"thinking_level": "high"}


def _record_usage(model_id: str, response: object) -> None:
    """Report Gemini's usage_metadata to roadmodel.usage. Thought tokens are
    billed at the output rate, so they count as output."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return
    candidates = getattr(meta, "candidates_token_count", None)
    thoughts = getattr(meta, "thoughts_token_count", None)
    output = (candidates or 0) + (thoughts or 0) if isinstance(candidates, int) else None
    usage.record(
        "google",
        model_id,
        input_tokens=getattr(meta, "prompt_token_count", None),
        output_tokens=output,
        cached_input_tokens=getattr(meta, "cached_content_token_count", None) or 0,
        reasoning_tokens=thoughts,
    )


@private_transport
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
    missing_sdk: ProviderCallError | None = None
    try:
        from google import genai
    except Exception:  # pragma: no cover - dependency/runtime guard
        missing_sdk = ProviderCallError(
            "The Google GenAI SDK is required for `roadmodel recommend` but is "
            "not installed. Install the engine extra: pip install 'roadmodel[recommend]'."
        )
    if missing_sdk is not None:
        raise missing_sdk

    if model is None:
        thinking_budget = DEFAULT_THINKING_BUDGET if thinking_budget is None else thinking_budget
        temperature = DEFAULT_TEMPERATURE if temperature is None else temperature
    try:
        client = genai.Client(
            api_key=api_key,
            http_options={
                "timeout": int(hosted_timeout() * 1000),
                "retry_options": {"attempts": 1},
            },
        )
        # `config` is typed `Any` so mypy strict doesn't reject a mixed
        # str|int dict literal against the SDK's `GenerateContentConfigDict`
        # TypedDict; the runtime SDK accepts plain dicts identically.
        config: Any = {"system_instruction": system}
        if max_output_tokens is not None:
            config["max_output_tokens"] = max_output_tokens
        model_id = model or DEFAULT_MODEL
        if thinking_budget is not None:
            # Gemini 2.5+ Flash reasons by default, and that reasoning is
            # decoded before the visible answer (and counts against
            # max_output_tokens). thinking_budget caps it: 0 disables
            # thinking entirely on 2.5, a small value bounds it, and on
            # Gemini 3+ it selects the matching level (_thinking_config).
            # `is not None` — not truthiness — because 0 is a meaningful value.
            config["thinking_config"] = _thinking_config(model_id, thinking_budget)
        if temperature is not None:
            # Recommender determinism (#176): without this Gemini samples at
            # its default temperature (~1.0), so identical input yields
            # different model picks run-to-run. `is not None` — not truthiness
            # — because 0.0 (greedy/deterministic) is the intended value.
            config["temperature"] = temperature
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config,
        )
        _record_usage(model_id, response)
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        raise ProviderCallError("Google response did not contain text output.")
    except ProviderCallError:
        raise
    except Exception as exc:
        failure = safe_error("Google", exc)
    # Raising outside the except block drops the raw SDK cause/context.
    raise failure
