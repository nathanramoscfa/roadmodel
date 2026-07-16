# src/roadmodel/providers/openai.py
from __future__ import annotations

from typing import Any

from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "gpt-5.4"


def _extract_output_text(response: object) -> str | None:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    pieces: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text_value = getattr(content, "text", None)
            if isinstance(text_value, str) and text_value:
                pieces.append(text_value)
    if pieces:
        return "".join(pieces).strip()
    return None


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
    # thinking_budget and temperature are accepted for ProviderAdapter Protocol
    # parity but intentionally NOT forwarded: both are Gemini-specific knobs for
    # the recommender latency/determinism work (issues #132, #176). OpenAI
    # reasoning control uses a different mechanism (`reasoning.effort` on
    # reasoning models), out of scope for the free-tier recommender, which runs
    # on Gemini Flash.
    _ = (thinking_budget, temperature)
    try:
        from openai import APIError, OpenAI
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError(
            "The OpenAI SDK is required for `roadmodel recommend` but is not "
            "installed. Install the engine extra: pip install 'roadmodel[recommend]'."
        ) from exc

    try:
        client = OpenAI(api_key=api_key)
        # `kwargs` is typed `Any` so mypy strict doesn't reject the
        # mixed-value-type dict against the SDK's overloaded `create`
        # signature; the runtime call accepts plain dicts identically.
        kwargs: Any = {
            "model": model or DEFAULT_MODEL,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        response = client.responses.create(**kwargs)
        text = _extract_output_text(response)
        if text:
            return text
        raise ProviderCallError("OpenAI response did not contain text output.")
    except ProviderCallError:
        raise
    except APIError as exc:
        raise ProviderCallError(f"OpenAI API call failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive adapter guard
        raise ProviderCallError(f"OpenAI API call failed ({type(exc).__name__}).") from exc
