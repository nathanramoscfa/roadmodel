# src/roadmodel/recommend.py
from __future__ import annotations

import json
import re
from dataclasses import asdict
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any, Final

from roadmodel import cost, user_context
from roadmodel.config import Config
from roadmodel.errors import BundledDocNotFoundError, MalformedResponseError
from roadmodel.providers import ProviderAdapter
from roadmodel.providers import anthropic as anthropic_provider
from roadmodel.providers import google as google_provider
from roadmodel.providers import openai as openai_provider

BUNDLED_SELECTOR_PATH: Traversable = resources.files("roadmodel.data") / "model-selector.txt"
BUNDLED_TIER_COST_PATH: Traversable = resources.files("roadmodel.data") / "model-tier-cost-scale.md"
BUNDLED_USER_CONTEXT_TEMPLATE_PATH: Traversable = (
    resources.files("roadmodel.data") / "user-context.example.md"
)

_REQUIRED_KEYS: Final = ("model", "platform", "max_mode", "thinking", "conversation", "rationale")

# ORCHESTRATION is optional in the response block: the bundled selector
# emits it on Claude Code surfaces (Ultracode), and not at all elsewhere.
# Pre-orchestration responses (and any provider that omits the line) must
# still parse, so the line is wrapped in a non-capturing optional group.
# The captured value is intentionally not propagated into the parsed dict
# yet — surfacing it via recommend_structured is a separate change.
_RESPONSE_BLOCK_RE: Final = re.compile(
    r"(?:^\s*PROMPT:\s*[^\n]*\n\s*)*"
    r"MODEL:\s*(?P<model>[^\n]+)\s*\n"
    r"PLATFORM:\s*(?P<platform>[^\n]+)\s*\n"
    r"MAX\s+MODE:\s*(?P<max_mode>[^\n]+)\s*\n"
    r"THINKING:\s*(?P<thinking>[^\n]+)\s*\n"
    r"(?:ORCHESTRATION:\s*(?P<orchestration>[^\n]+)\s*\n)?"
    r"CONVERSATION:\s*(?P<conversation>[^\n]+)\s*\n"
    r"RATIONALE:\s*(?P<rationale>.+?)(?=\n\s*(?:PROMPT:|MODEL:)|\Z)",
    flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

PROVIDER_ADAPTERS: dict[str, ProviderAdapter] = {
    "anthropic": anthropic_provider,
    "openai": openai_provider,
    "google": google_provider,
}


def _read_bundled_doc(path: Traversable, filename: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BundledDocNotFoundError(filename) from exc


def build_prompt(user_prompt: str, *, user_context_text: str) -> tuple[str, str]:
    selector_text = _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
    tier_cost_text = _read_bundled_doc(BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md")
    _ = _read_bundled_doc(BUNDLED_USER_CONTEXT_TEMPLATE_PATH, "user-context.example.md")

    header = (
        "You are roadmodel. Follow the selector algorithm and return exactly one six-field block:\n"
        "MODEL / PLATFORM / MAX MODE / THINKING / CONVERSATION / RATIONALE.\n"
        "Do not emit extra sections or commentary.\n"
    )
    system = "\n\n".join(
        [
            header,
            selector_text,
            tier_cost_text,
            user_context_text,
        ]
    )
    return system, user_prompt


def _normalize_dict_payload(payload: dict[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in payload.items():
        normalized_key = key.strip().lower().replace(" ", "_")
        if normalized_key not in _REQUIRED_KEYS:
            continue
        if isinstance(value, str):
            normalized[normalized_key] = value.strip()
        else:
            normalized[normalized_key] = str(value).strip()
    if all(normalized.get(key) for key in _REQUIRED_KEYS):
        return {key: normalized[key] for key in _REQUIRED_KEYS}
    raise ValueError("JSON payload missing required keys.")


def parse_response(text: str) -> dict[str, str]:
    stripped = text.strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        try:
            return _normalize_dict_payload(parsed)
        except ValueError:
            pass

    regex_match = _RESPONSE_BLOCK_RE.search(text)
    if regex_match:
        # The ORCHESTRATION group is optional and captures None when absent;
        # coerce None → "" so .strip() doesn't crash. orchestration is
        # consumed silently — not yet surfaced via the returned dict.
        parsed_block = {
            key: (value.strip() if value else "")
            for key, value in regex_match.groupdict().items()
        }
        if all(parsed_block.get(key) for key in _REQUIRED_KEYS):
            return {key: parsed_block[key] for key in _REQUIRED_KEYS}

    raise MalformedResponseError(text)


def recommend(
    prompt: str,
    config: Config,
    *,
    max_output_tokens: int | None = None,
) -> dict[str, str]:
    user_context_text = user_context.read(config.user_context_path)
    system_prompt, user_prompt = build_prompt(prompt, user_context_text=user_context_text)
    adapter = PROVIDER_ADAPTERS[config.provider]
    raw_response = adapter.recommend(
        user_prompt,
        system_prompt,
        model=config.model,
        api_key=config.api_key,
        max_output_tokens=max_output_tokens,
    )
    return parse_response(raw_response)


def _structured_settings(base: dict[str, str]) -> dict[str, str]:
    """Map the six-field block to per-surface settings (phase roadmap table)."""
    plat = base["platform"].strip().lower()
    max_mode_raw = base["max_mode"].strip()
    thinking_raw = base["thinking"].strip()

    def max_mode_on() -> bool:
        lowered = max_mode_raw.lower()
        return lowered in {"on", "yes", "true", "enabled"}

    if "claude code" in plat.replace("_", " "):
        offish = {"off", "n/a", "none", "no"}
        if thinking_raw.lower() in offish:
            return {"effort": "Low", "thinking": "Off"}
        return {"effort": thinking_raw, "thinking": "On"}

    if plat == "codex" or plat.endswith(" codex"):
        return {"intelligence": thinking_raw}

    max_label = "ON" if max_mode_on() else "OFF"
    return {"max_mode": max_label, "thinking": thinking_raw}


def recommend_structured(
    prompt: str,
    config: Config,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    max_mode: bool = False,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Return roadmap-style structured output plus optional cost estimates."""
    base = recommend(prompt, config, max_output_tokens=max_output_tokens)
    payload: dict[str, Any] = {
        "model": base["model"],
        "platform": base["platform"],
        "settings": _structured_settings(base),
        "rationale": base["rationale"],
        "conversation": base["conversation"],
        "session_cost_estimate": None,
        "comparison_table": None,
    }
    if input_tokens is None or output_tokens is None:
        return payload

    primary = cost.estimate_session_cost(
        base["model"],
        base["platform"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        max_mode=max_mode,
    )
    payload["session_cost_estimate"] = asdict(primary)
    ranked = cost.compare_alternatives_funding_rank(
        base["model"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        max_mode=max_mode,
    )
    payload["comparison_table"] = [asdict(est) for est in ranked]
    return payload
