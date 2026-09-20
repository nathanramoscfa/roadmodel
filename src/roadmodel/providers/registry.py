# src/roadmodel/providers/registry.py
"""Table of OpenAI-compatible recommender engines.

Every entry is served by ONE adapter (:mod:`roadmodel.providers.openai_compatible`)
that speaks the Chat Completions API against ``base_url``. Anthropic / OpenAI /
Google keep their native adapters; this table is for the providers whose only
public surface is an OpenAI-compatible endpoint (plus local Ollama and the
``custom`` escape hatch for any other endpoint).

``reasoning`` names how ``thinking_budget`` is forwarded — only where the
provider DOCUMENTS a Chat-Completions field for it (base URLs and dial fields
were verified against each provider's docs when the table was written; see
docs/byo-key-setup.md for the citations):

- ``"deepseek"`` — ``thinking: {type: enabled|disabled}`` + ``reasoning_effort``
  low/high/max (DeepSeek thinking-mode guide).
- ``"zai"`` — same ``thinking`` object + ``reasoning_effort`` max/high/low
  (Z.ai chat-completion reference; GLM-4.5+).
- ``"effort"`` — plain ``reasoning_effort`` low/medium/high (Groq gpt-oss).
- ``"effort_none"`` — ``reasoning_effort`` with a ``none`` rung (Mistral:
  none/minimal/low/medium/high/xhigh; Ollama: none/low/medium/high/max).
- ``"none"`` — nothing forwarded (xAI grok-4.x, OpenRouter / Together whose
  models are heterogeneous, and ``custom`` whose endpoint is unknown).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ReasoningDial = Literal["none", "deepseek", "zai", "effort", "effort_none"]

# The Ollama docs tell OpenAI-SDK callers to pass a non-empty placeholder key;
# the local server ignores it.
OLLAMA_PLACEHOLDER_KEY = "ollama"
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"

# The ``custom`` provider is configured entirely from these three variables.
CUSTOM_BASE_URL_ENV = "ROADMODEL_BASE_URL"
CUSTOM_API_KEY_ENV = "ROADMODEL_API_KEY"
# Honored for EVERY provider as the env-var form of ``--model`` (the CLI flag
# wins); REQUIRED for ``ollama`` and ``custom``, which have no sane default.
MODEL_ENV = "ROADMODEL_MODEL"


@dataclass(frozen=True)
class CompatibleProvider:
    name: str
    label: str
    base_url: str | None  # None => resolved from the environment at call time
    key_env: str
    default_model: str | None  # None => the user MUST name a model
    reasoning: ReasoningDial
    key_required: bool = True
    # Local / self-hosted endpoints generate slowly (a 32B model on a laptop
    # takes minutes per call); the SDK's default 10-minute timeout — and its
    # automatic retries, which redo the whole generation — are wrong for them.
    # None = SDK defaults.
    timeout_s: float | None = None


LOCAL_TIMEOUT_S = 1800.0


COMPATIBLE_PROVIDERS: dict[str, CompatibleProvider] = {
    "deepseek": CompatibleProvider(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com",
        "DEEPSEEK_API_KEY",
        "deepseek-v4-pro",
        "deepseek",
    ),
    "xai": CompatibleProvider(
        "xai", "xAI", "https://api.x.ai/v1", "XAI_API_KEY", "grok-4.6", "none"
    ),
    "groq": CompatibleProvider(
        "groq",
        "Groq",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        "openai/gpt-oss-120b",
        "effort",
    ),
    "mistral": CompatibleProvider(
        "mistral",
        "Mistral",
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        "mistral-medium-latest",
        "effort_none",
    ),
    "zai": CompatibleProvider(
        "zai", "Z.ai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY", "glm-5.2", "zai"
    ),
    "openrouter": CompatibleProvider(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        None,
        "none",
    ),
    "together": CompatibleProvider(
        "together",
        "Together",
        "https://api.together.ai/v1",
        "TOGETHER_API_KEY",
        None,
        "none",
    ),
    "ollama": CompatibleProvider(
        "ollama",
        "Ollama",
        None,
        "OLLAMA_API_KEY",
        None,
        "effort_none",
        key_required=False,
        timeout_s=LOCAL_TIMEOUT_S,
    ),
    "custom": CompatibleProvider(
        "custom",
        "Custom endpoint",
        None,
        CUSTOM_API_KEY_ENV,
        None,
        "none",
        timeout_s=LOCAL_TIMEOUT_S,
    ),
}


def resolve_base_url(spec: CompatibleProvider) -> str | None:
    """The endpoint for ``spec``: the table value, or for the two env-driven
    providers ``OLLAMA_HOST`` (Ollama's own variable, ``host:port`` or a URL;
    default localhost:11434) and ``ROADMODEL_BASE_URL`` (``custom``)."""
    if spec.base_url is not None:
        return spec.base_url
    if spec.name == "ollama":
        host = os.environ.get("OLLAMA_HOST", "").strip()
        if not host:
            return OLLAMA_DEFAULT_BASE_URL
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return host.rstrip("/") + "/v1"
    if spec.name == "custom":
        base_url = os.environ.get(CUSTOM_BASE_URL_ENV, "").strip()
        return base_url or None
    return None  # pragma: no cover - every table entry is handled above
