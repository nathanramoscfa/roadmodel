# src/roadmodel/providers/anthropic.py
from __future__ import annotations

from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "claude-sonnet-4-6"


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
    # the recommender latency/determinism work (issues #132, #176). Anthropic
    # extended-thinking has different semantics (a `thinking` block with its own
    # budget_tokens and minimums) and the recommender response shape does not
    # tolerate small caps on Anthropic at all (PR #128). Anthropic reasoning
    # control is Phase 5 paid-frontier scope.
    _ = (thinking_budget, temperature)
    try:
        from anthropic import Anthropic, APIError
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError(
            "The Anthropic SDK is required for `roadmodel recommend` but is not "
            "installed. Install the engine extra: pip install 'roadmodel[recommend]'."
        ) from exc

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=max_output_tokens if max_output_tokens is not None else 4096,
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
        raise ProviderCallError(f"Anthropic API call failed ({type(exc).__name__}).") from exc
