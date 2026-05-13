# src/roadmodel/config.py
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from roadmodel import user_context
from roadmodel.errors import MissingProviderKeyError

ProviderName = Literal["anthropic", "openai", "google"]

PROVIDER_KEY_ENV: dict[ProviderName, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}
PROVIDER_ORDER: tuple[ProviderName, ...] = ("anthropic", "openai", "google")

_MISSING_KEY_REMEDIATION = (
    "No provider key found. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY. "
    "Try: export ANTHROPIC_API_KEY=..."
)


@dataclass(frozen=True)
class Config:
    provider: ProviderName
    model: str | None
    api_key: str
    user_context_path: Path


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
        f"Invalid provider {value!r}. Use one of: anthropic, openai, google."
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
    provider = (
        _normalize_provider(cli_provider)
        or _normalize_provider(os.environ.get("ROADMODEL_PROVIDER"))
        or _first_present_env_provider()
    )
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
    if not api_key:
        raise MissingProviderKeyError(_MISSING_KEY_REMEDIATION)

    resolved_cli_path = cli_user_context
    if (
        resolved_cli_path is None
        and not os.environ.get("ROADMODEL_USER_CONTEXT")
        and config_data
    ):
        resolved_cli_path = _config_user_context_override(config_data)

    resolved_path = user_context.resolve(cli_path=resolved_cli_path)
    return Config(
        provider=provider,
        model=cli_model.strip() if isinstance(cli_model, str) and cli_model.strip() else None,
        api_key=api_key,
        user_context_path=resolved_path,
    )
