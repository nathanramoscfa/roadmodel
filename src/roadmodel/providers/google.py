# src/roadmodel/providers/google.py
from __future__ import annotations

import re
from typing import Any

from roadmodel import usage
from roadmodel.errors import ProviderCallError

# Default engine model for direct Google API calls when no model is passed.
# Must be a model that is actually callable on the public Google Generative
# Language API (v1beta generateContent). `gemini-3.1-pro` is catalog-only
# (Cursor) and returns 404 NOT_FOUND on the direct API, so a bare
# `roadmodel recommend` / the MCP server / any SDK caller with only a Google
# key would fail; `gemini-2.5-pro` is the highest-quality callable Gemini.
# Prod (the hosted service) forces an explicit model and never relies on this.
DEFAULT_MODEL = "gemini-2.5-pro"

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
    try:
        from google import genai
        from google.genai.errors import APIError
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError(
            "The Google GenAI SDK is required for `roadmodel recommend` but is "
            "not installed. Install the engine extra: pip install 'roadmodel[recommend]'."
        ) from exc

    try:
        client = genai.Client(api_key=api_key)
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
    except APIError as exc:
        raise ProviderCallError(f"Google API call failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive adapter guard
        raise ProviderCallError(f"Google API call failed ({type(exc).__name__}).") from exc
