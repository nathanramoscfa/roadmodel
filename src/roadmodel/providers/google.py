# src/roadmodel/providers/google.py
from __future__ import annotations

from typing import Any

from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "gemini-3.1-pro"


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
            "Google GenAI SDK is unavailable; install the 'google-genai' package."
        ) from exc

    try:
        client = genai.Client(api_key=api_key)
        # `config` is typed `Any` so mypy strict doesn't reject a mixed
        # str|int dict literal against the SDK's `GenerateContentConfigDict`
        # TypedDict; the runtime SDK accepts plain dicts identically.
        config: Any = {"system_instruction": system}
        if max_output_tokens is not None:
            config["max_output_tokens"] = max_output_tokens
        if thinking_budget is not None:
            # Gemini 2.5+ Flash reasons by default, and that reasoning is
            # decoded before the visible answer (and counts against
            # max_output_tokens). thinking_budget caps it: 0 disables
            # thinking entirely, a small value bounds it. `is not None` —
            # not truthiness — because 0 is a meaningful value (thinking off).
            config["thinking_config"] = {"thinking_budget": thinking_budget}
        if temperature is not None:
            # Recommender determinism (#176): without this Gemini samples at
            # its default temperature (~1.0), so identical input yields
            # different model picks run-to-run. `is not None` — not truthiness
            # — because 0.0 (greedy/deterministic) is the intended value.
            config["temperature"] = temperature
        response = client.models.generate_content(
            model=model or DEFAULT_MODEL,
            contents=prompt,
            config=config,
        )
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
