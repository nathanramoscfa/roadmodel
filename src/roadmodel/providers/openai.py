# src/roadmodel/providers/openai.py
from __future__ import annotations

import re
from typing import Any

from roadmodel import usage
from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "gpt-5.4"


# The reasoning generations: gpt-5 and everything after it (gpt-6, gpt-6.1,
# ...). Each one bills reasoning against max_output_tokens, so each gets the
# reasoning.effort cap below. Matching only "gpt-5" left the gpt-6 line running
# at its default effort: slower, dearer, and free to spend the whole output
# budget thinking.
_REASONING_RE = re.compile(r"^gpt-(?:5|[6-9])")

# gpt-5.6 and later dropped the `minimal` reasoning rung; their floor is `low`.
_NO_MINIMAL_RE = re.compile(r"^gpt-(?:5\.[6-9]|5\.\d\d|[6-9])")


def _record_usage(model_id: str, response: object) -> None:
    """Report the Responses API's token counts to roadmodel.usage."""
    u = getattr(response, "usage", None)
    if u is None:
        return
    usage.record(
        "openai",
        model_id,
        input_tokens=getattr(u, "input_tokens", None),
        output_tokens=getattr(u, "output_tokens", None),
        cached_input_tokens=getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0),
        reasoning_tokens=getattr(
            getattr(u, "output_tokens_details", None), "reasoning_tokens", None
        ),
    )


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
    # temperature is a Gemini-specific determinism knob (#176) and reasoning
    # models reject it — not forwarded. thinking_budget IS forwarded for OpenAI
    # reasoning models (gpt-5*) as reasoning.effort: those models count reasoning
    # tokens against max_output_tokens, so without an effort cap the reasoning can
    # consume the ENTIRE budget and return no visible text (observed: gpt-5-mini
    # 32s, empty output). The recommender is a structured-classification task
    # where the pick is easy (T1), so a low effort is fast + cheap + sufficient;
    # 0 -> minimal for the highest-volume anon path.
    _ = temperature
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
        model_id = model or DEFAULT_MODEL
        kwargs: Any = {
            "model": model_id,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        # Cap reasoning on the gpt-5+ reasoning models so it doesn't eat the
        # whole max_output_tokens budget (see the note above). Default low; a
        # thinking_budget of 0 selects the FLOOR of that model's ladder for the
        # anon tier — `minimal` on the gpt-5.0-5.5 generation, `low` from the
        # gpt-5.6 generation on, which rejects `minimal` outright ("Unsupported
        # value: 'minimal' is not supported with the 'gpt-5.6-luna' model").
        if _REASONING_RE.match(model_id):
            floor = "low" if _NO_MINIMAL_RE.match(model_id) else "minimal"
            kwargs["reasoning"] = {"effort": floor if thinking_budget == 0 else "low"}
        response = client.responses.create(**kwargs)
        _record_usage(model_id, response)
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
