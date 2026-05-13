# src/roadmodel/providers/anthropic.py
from __future__ import annotations

from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "claude-sonnet-4-6"


def recommend(prompt: str, system: str, *, model: str | None = None, api_key: str) -> str:
    try:
        from anthropic import APIError, Anthropic
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError("Anthropic SDK is unavailable; install the 'anthropic' package.") from exc

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                piece = getattr(block, "text", "")
                if piece:
                    text_parts.append(piece)
        if text_parts:
            return "".join(text_parts).strip()
        raise ProviderCallError("Anthropic response did not contain text output.")
    except ProviderCallError:
        raise
    except APIError as exc:
        raise ProviderCallError(f"Anthropic API call failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive adapter guard
        raise ProviderCallError(f"Anthropic API call failed: {exc}") from exc
