# src/roadmodel/providers/openai_compatible.py
"""One adapter for every OpenAI-compatible recommender engine.

Speaks Chat Completions (``client.chat.completions.create``), NOT the
Responses API that :mod:`roadmodel.providers.openai` uses: most compatible
endpoints (DeepSeek, xAI, Groq, Mistral, Z.ai, OpenRouter, Together, Ollama,
vLLM, LM Studio, ...) implement only ``/chat/completions``. Reuses the ``openai``
SDK from the ``recommend`` extra with ``base_url`` pointed at the provider.

Each provider gets its own adapter INSTANCE bound to a
:class:`~roadmodel.providers.registry.CompatibleProvider` spec, so the
``ProviderAdapter`` Protocol (``recommend(prompt, system, *, model, api_key,
...)``) is unchanged and the dispatch table in ``recommend.py`` stays a flat
``name -> adapter`` map.
"""

from __future__ import annotations

import re
from typing import Any

from roadmodel.errors import ProviderCallError
from roadmodel.providers.registry import (
    COMPATIBLE_PROVIDERS,
    CUSTOM_BASE_URL_ENV,
    MODEL_ENV,
    CompatibleProvider,
    resolve_base_url,
)

# Some local / open-weight models (Qwen3 via Ollama, DeepSeek-R1 distills) put
# their chain of thought inline as <think>...</think> when the server has no
# separate reasoning field. The recommender's parser needs the labeled block
# only, so the reasoning is stripped rather than left to break the parse.
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _extract_message_text(response: object) -> str | None:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        text = _THINK_BLOCK.sub("", content).strip()
        return text or None
    if isinstance(content, list):  # multi-part content on some endpoints
        pieces = [
            part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
            for part in content
        ]
        text = _THINK_BLOCK.sub("", "".join(p for p in pieces if isinstance(p, str))).strip()
        return text or None
    return None


def _reasoning_only(response: object) -> bool:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return False
    message = getattr(choices[0], "message", None)
    for field in ("reasoning", "reasoning_content"):
        value = getattr(message, field, None)
        if isinstance(value, str) and value.strip():
            return True
    # Unknown fields ride along in the SDK's `model_extra` on pydantic models.
    extra = getattr(message, "model_extra", None) or {}
    return any(
        isinstance(extra.get(field), str) and extra[field].strip()
        for field in ("reasoning", "reasoning_content")
    )


def _reasoning_kwargs(spec: CompatibleProvider, thinking_budget: int | None) -> dict[str, Any]:
    """Map the Protocol's Gemini-shaped ``thinking_budget`` (None = provider
    default, 0 = off / minimal, >0 = bounded) onto the dial the provider
    DOCUMENTS for Chat Completions. Anything undocumented is omitted — an
    unknown field is a 400 on strict endpoints. Mirrors providers/openai.py:
    >0 selects the LOWEST effort rung, because the recommender is a
    structured-classification task where reasoning tokens count against
    ``max_tokens`` and can eat the whole budget."""
    if thinking_budget is None or spec.reasoning == "none":
        return {}
    if spec.reasoning in ("deepseek", "zai"):
        if thinking_budget == 0:
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {
            "extra_body": {"thinking": {"type": "enabled"}},
            "reasoning_effort": "low",
        }
    if spec.reasoning == "effort":
        return {"reasoning_effort": "low"}
    # "effort_none": the provider has an explicit off rung.
    return {"reasoning_effort": "none" if thinking_budget == 0 else "low"}


class OpenAICompatibleAdapter:
    """``ProviderAdapter`` for one :class:`CompatibleProvider` spec."""

    def __init__(self, spec: CompatibleProvider) -> None:
        self.spec = spec

    def recommend(
        self,
        prompt: str,
        system: str,
        *,
        model: str | None = None,
        api_key: str,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> str:
        spec = self.spec
        try:
            from openai import APIError, OpenAI
        except Exception as exc:  # pragma: no cover - dependency/runtime guard
            raise ProviderCallError(
                f"The OpenAI SDK is required for `roadmodel recommend` via {spec.label} "
                "but is not installed. Install the engine extra: "
                "pip install 'roadmodel[recommend]'."
            ) from exc

        model_id = model or spec.default_model
        if not model_id:
            raise ProviderCallError(
                f"Provider {spec.name!r} has no default model: pass --model or set {MODEL_ENV}."
            )
        base_url = resolve_base_url(spec)
        if not base_url:
            raise ProviderCallError(
                f"Provider {spec.name!r} needs an endpoint: set {CUSTOM_BASE_URL_ENV} "
                "(e.g. http://localhost:8000/v1)."
            )

        try:
            client_kwargs: Any = {"api_key": api_key, "base_url": base_url}
            if spec.timeout_s is not None:
                # Slow local generation: one long attempt, no retries that
                # would silently redo minutes of work after a timeout.
                client_kwargs["timeout"] = spec.timeout_s
                client_kwargs["max_retries"] = 0
            client = OpenAI(**client_kwargs)
            # `kwargs` is typed `Any` for the same reason as providers/openai.py:
            # the SDK's overloaded `create` signature rejects a mixed-value dict.
            kwargs: Any = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
            if max_output_tokens is not None:
                # `max_tokens`, not the newer `max_completion_tokens`: the classic
                # name is the one every compatible endpoint understands.
                kwargs["max_tokens"] = max_output_tokens
            if temperature is not None:
                # Recommender determinism (#176). Forwarded: unlike OpenAI's
                # o-series / gpt-5, compatible endpoints accept (or document
                # ignoring) temperature on reasoning models.
                kwargs["temperature"] = temperature
            kwargs.update(_reasoning_kwargs(spec, thinking_budget))
            response = client.chat.completions.create(**kwargs)
            text = _extract_message_text(response)
            if text:
                return text
            if _reasoning_only(response):
                # Thinking models on compatible endpoints return the chain of
                # thought in a separate `reasoning` / `reasoning_content` field
                # that counts against max_tokens; an exhausted budget leaves
                # no visible answer at all (observed: Qwen3 via Ollama).
                raise ProviderCallError(
                    f"{spec.label} response contained reasoning but no visible text "
                    "(the model spent its whole output budget thinking). Raise "
                    "--max-output-tokens or disable thinking with --thinking-budget 0."
                )
            raise ProviderCallError(f"{spec.label} response did not contain text output.")
        except ProviderCallError:
            raise
        except APIError as exc:
            raise ProviderCallError(f"{spec.label} API call failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive adapter guard
            raise ProviderCallError(
                f"{spec.label} API call failed ({type(exc).__name__})."
            ) from exc


ADAPTERS: dict[str, OpenAICompatibleAdapter] = {
    name: OpenAICompatibleAdapter(spec) for name, spec in COMPATIBLE_PROVIDERS.items()
}
