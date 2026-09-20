# src/roadmodel/config.py
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from roadmodel import user_context
from roadmodel.errors import MissingProviderKeyError
from roadmodel.providers.registry import (
    COMPATIBLE_PROVIDERS,
    CUSTOM_BASE_URL_ENV,
    MODEL_ENV,
    OLLAMA_PLACEHOLDER_KEY,
)

# The three native adapters, then the OpenAI-compatible table
# (providers/registry.py) and the `custom` escape hatch.
ProviderName = Literal[
    "anthropic",
    "openai",
    "google",
    "deepseek",
    "xai",
    "groq",
    "mistral",
    "zai",
    "openrouter",
    "together",
    "ollama",
    "custom",
]

PROVIDER_KEY_ENV: dict[ProviderName, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "zai": "ZAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "together": "TOGETHER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "custom": "ROADMODEL_API_KEY",
}
# Auto-detection order when ROADMODEL_PROVIDER / --provider is absent: the
# first of these whose key is present wins. `ollama` (no key) and `custom`
# (needs ROADMODEL_BASE_URL too) are explicit-only and deliberately absent.
PROVIDER_ORDER: tuple[ProviderName, ...] = (
    "anthropic",
    "openai",
    "google",
    "deepseek",
    "xai",
    "groq",
    "mistral",
    "zai",
    "openrouter",
    "together",
)
PROVIDER_CHOICES: tuple[str, ...] = (*PROVIDER_ORDER, "ollama", "custom")

_MISSING_KEY_REMEDIATION = (
    "No provider key found. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY "
    "(or another supported provider's key, or ROADMODEL_PROVIDER=ollama|custom — see "
    "`roadmodel recommend --help`). Try: export ANTHROPIC_API_KEY=..."
)


@dataclass(frozen=True, repr=False)
class Config:
    provider: ProviderName
    model: str | None
    api_key: str
    user_context_path: Path

    def __repr__(self) -> str:
        masked = f"{self.api_key[:4]}***" if self.api_key else "<empty>"
        return (
            f"Config(provider={self.provider!r}, model={self.model!r}, "
            f"api_key={masked!r}, user_context_path={self.user_context_path!r})"
        )


def _config_home() -> Path:
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_home:
        return Path(xdg_home).expanduser() / "roadmodel"
    return Path.home() / ".config" / "roadmodel"


def _config_path() -> Path:
    return _config_home() / "config.toml"


def _normalize_provider(value: str | None) -> ProviderName | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in PROVIDER_KEY_ENV:
        return normalized
    raise MissingProviderKeyError(
        f"Invalid provider {value!r}. Use one of: {', '.join(PROVIDER_CHOICES)}."
    )


def _first_present_env_provider() -> ProviderName | None:
    for provider in PROVIDER_ORDER:
        env_name = PROVIDER_KEY_ENV[provider]
        if os.environ.get(env_name):
            return provider
    return None


def _read_config_toml() -> dict[str, Any]:
    config_path = _config_path()
    if not config_path.exists():
        return {}
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    if isinstance(data, dict):
        return data
    return {}


def _config_api_key(config_data: dict[str, Any], provider: ProviderName) -> str | None:
    providers = config_data.get("providers")
    if not isinstance(providers, dict):
        return None
    provider_config = providers.get(provider)
    if not isinstance(provider_config, dict):
        return None
    api_key = provider_config.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    return None


def _config_user_context_override(config_data: dict[str, Any]) -> Path | None:
    paths = config_data.get("paths")
    if not isinstance(paths, dict):
        return None
    raw_path = paths.get("user_context")
    if isinstance(raw_path, str) and raw_path.strip():
        return Path(raw_path).expanduser()
    return None


def load_config(
    *, cli_provider: str | None, cli_model: str | None, cli_user_context: Path | None
) -> Config:
    explicit_provider = _normalize_provider(cli_provider) or _normalize_provider(
        os.environ.get("ROADMODEL_PROVIDER")
    )
    provider = explicit_provider or _first_present_env_provider()
    if provider is None:
        raise MissingProviderKeyError(_MISSING_KEY_REMEDIATION)

    key_env_name = PROVIDER_KEY_ENV[provider]
    env_api_key = os.environ.get(key_env_name, "").strip()
    config_data: dict[str, Any] = {}
    if env_api_key:
        api_key = env_api_key
    else:
        config_data = _read_config_toml()
        api_key = _config_api_key(config_data, provider) or ""
    compatible = COMPATIBLE_PROVIDERS.get(provider)
    if not api_key and compatible is not None and not compatible.key_required:
        # Local Ollama ignores the key but the SDK requires a non-empty one.
        api_key = OLLAMA_PLACEHOLDER_KEY
    if not api_key:
        if explicit_provider is not None:
            raise MissingProviderKeyError(
                f"Provider {provider!r} selected but {key_env_name} is not set. "
                f"Try: export {key_env_name}=..."
            )
        raise MissingProviderKeyError(_MISSING_KEY_REMEDIATION)

    # --model wins; ROADMODEL_MODEL is its env form (any provider). The two
    # providers without a default model (ollama, custom) must name one here.
    model = cli_model.strip() if isinstance(cli_model, str) and cli_model.strip() else None
    if model is None:
        model = os.environ.get(MODEL_ENV, "").strip() or None
    if compatible is not None:
        if model is None and compatible.default_model is None:
            raise MissingProviderKeyError(
                f"Provider {provider!r} has no default model: pass --model or set {MODEL_ENV}."
            )
        if provider == "custom" and not os.environ.get(CUSTOM_BASE_URL_ENV, "").strip():
            raise MissingProviderKeyError(
                f"Provider 'custom' selected but {CUSTOM_BASE_URL_ENV} is not set. "
                f"Try: export {CUSTOM_BASE_URL_ENV}=http://localhost:8000/v1"
            )

    resolved_cli_path = cli_user_context
    if resolved_cli_path is None and not os.environ.get("ROADMODEL_USER_CONTEXT") and config_data:
        resolved_cli_path = _config_user_context_override(config_data)

    resolved_path = user_context.resolve(cli_path=resolved_cli_path)
    return Config(
        provider=provider,
        model=model,
        api_key=api_key,
        user_context_path=resolved_path,
    )
