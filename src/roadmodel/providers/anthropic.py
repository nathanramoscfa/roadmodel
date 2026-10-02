# src/roadmodel/providers/anthropic.py
from __future__ import annotations

import re
from typing import Any

from roadmodel import usage
from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "claude-sonnet-4-6"

# claude-<family>-<major>[-<minor>][-<yyyymmdd>]: claude-haiku-4-5-20251001,
# claude-sonnet-5, claude-opus-5-5, claude-fable-5-1.
_MODEL_RE = re.compile(
    r"^claude-(?P<family>[a-z]+)-(?P<major>\d+)(?:-(?P<minor>\d{1,2}))?(?:-\d{8})?$"
)


def _generation(model_id: str) -> tuple[str, tuple[int, int]] | None:
    match = _MODEL_RE.match(model_id)
    if match is None:
        return None
    return match["family"], (int(match["major"]), int(match["minor"] or 0))


def _takes_effort(model_id: str) -> bool:
    """Whether the model accepts output_config.effort: Opus 4.5 and later,
    Sonnet 4.6 and later, and the Fable/Mythos line. Haiku 4.5 rejects it."""
    gen = _generation(model_id)
    if gen is None:
        return False
    family, version = gen
    if family == "opus":
        return version >= (4, 5)
    if family == "sonnet":
        return version >= (4, 6)
    return family in ("fable", "mythos")


def _record_usage(model_id: str, response: object) -> None:
    """Report the Messages API's token counts to roadmodel.usage. Anthropic
    splits the prompt into uncached input, cache reads and cache writes; the
    total is their sum."""
    u = getattr(response, "usage", None)
    if u is None:
        return
    uncached = getattr(u, "input_tokens", None)
    read = getattr(u, "cache_read_input_tokens", None) or 0
    write = getattr(u, "cache_creation_input_tokens", None) or 0
    total = uncached + read + write if isinstance(uncached, int) else None
    usage.record(
        "anthropic",
        model_id,
        input_tokens=total,
        output_tokens=getattr(u, "output_tokens", None),
        cached_input_tokens=read,
        cache_write_tokens=write,
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
        from anthropic import Anthropic, APIError
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError(
            "The Anthropic SDK is required for `roadmodel recommend` but is not "
            "installed. Install the engine extra: pip install 'roadmodel[recommend]'."
        ) from exc

    model_id = model or DEFAULT_MODEL
    # `kwargs` is typed `Any` for the same reason as providers/openai.py: the
    # SDK's overloaded `create` signature rejects a mixed-value dict literal.
    kwargs: Any = {
        "model": model_id,
        "max_tokens": max_output_tokens if max_output_tokens is not None else 4096,
        # The system prompt is the selector + catalog (~60k tokens) and is the
        # same on every call, so it is cached: a warm call reads it at a tenth
        # of the input price instead of paying for it again.
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": prompt}],
    }
    # thinking_budget is the Protocol's "how hard to reason" dial. Current Claude
    # models take no token budget (it is a 400 on Sonnet 5 and Opus 4.7+), so
    # any value maps to the lowest effort, which keeps the classification fast,
    # like reasoning.effort on providers/openai.py. Thinking itself is left at
    # the model's default: Opus 5.5 cannot disable it, and lowering effort is
    # the documented way to make it brief.
    if thinking_budget is not None and _takes_effort(model_id):
        kwargs["output_config"] = {"effort": "low"}
    # `temperature` (the Gemini determinism knob, #176) is never sent: the
    # anthropic SDK removed the parameter in 1.0 (a TypeError before any
    # request), and Sonnet 5, Opus 4.7+ and Fable reject sampling anyway.
    _ = temperature

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(**kwargs)
        _record_usage(model_id, response)
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
