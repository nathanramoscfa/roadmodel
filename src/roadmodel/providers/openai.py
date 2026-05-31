# src/roadmodel/providers/openai.py
from __future__ import annotations

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
) -> str:
    try:
        from openai import APIError, OpenAI
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError("OpenAI SDK is unavailable; install the 'openai' package.") from exc

    try:
        client = OpenAI(api_key=api_key)
        kwargs: dict[str, object] = {
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
