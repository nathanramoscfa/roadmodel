# src/roadmodel/mcp_server.py
# mypy: disable-error-code="import-not-found,untyped-decorator"
from __future__ import annotations

import json
import sys
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from roadmodel import recommend as recommender
from roadmodel import user_context
from roadmodel.config import Config, load_config
from roadmodel.errors import BundledDocNotFoundError
from roadmodel.providers import ProviderAdapter

BUNDLED_SELECTOR_PATH: Traversable = resources.files("roadmodel.data") / "model-selector.txt"
BUNDLED_TIER_COST_PATH: Traversable = resources.files("roadmodel.data") / "model-tier-cost-scale.md"
BUNDLED_CATALOG_PATH: Traversable = resources.files("roadmodel.data") / "catalog.json"
BUNDLED_PHASE_TEMPLATE_PATH: Traversable = (
    resources.files("roadmodel.data") / "phase-roadmap-template.md"
)


def _read_bundled_doc(path: Traversable, filename: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BundledDocNotFoundError(filename) from exc


def _load_runtime_config() -> Config:
    return load_config(cli_provider=None, cli_model=None, cli_user_context=None)


def _recommend_system_prompt(user_context_text: str, context: str | None) -> str:
    selector_text = _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
    tier_cost_text = _read_bundled_doc(BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md")
    parts = [selector_text, tier_cost_text, user_context_text]
    if context is not None and context.strip():
        parts.append(f"Project context:\n{context.strip()}")
    return "\n\n".join(parts)


def _recommend_user_prompt(task_description: str, context: str | None) -> str:
    prompt = task_description.strip()
    if context is not None and context.strip():
        prompt = f"{prompt}\n\nProject context:\n{context.strip()}"
    return prompt


def _phase_roadmap_system_prompt(user_context_text: str) -> str:
    template_text = _read_bundled_doc(BUNDLED_PHASE_TEMPLATE_PATH, "phase-roadmap-template.md")
    selector_text = _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
    tier_cost_text = _read_bundled_doc(BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md")
    return "\n\n".join([template_text, selector_text, tier_cost_text, user_context_text])


def _phase_roadmap_user_prompt(
    project_brief: str, phase_number: int, prior_phases: list[str] | None
) -> str:
    lines = [project_brief.strip(), "", f"Phase number: {phase_number}"]
    cleaned_prior = [phase.strip() for phase in (prior_phases or []) if phase.strip()]
    if cleaned_prior:
        lines.append("")
        lines.append("Prior phases:")
        lines.extend(f"- {phase}" for phase in cleaned_prior)
    return "\n".join(lines).strip()


def _provider_recommend(config: Config, user_prompt: str, system_prompt: str) -> str:
    adapter: ProviderAdapter = recommender.PROVIDER_ADAPTERS[config.provider]
    return adapter.recommend(
        user_prompt,
        system_prompt,
        model=config.model,
        api_key=config.api_key,
    )


def _recommend_structured_with_prompts(
    config: Config,
    *,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    original_build_prompt = recommender.build_prompt
    forced_user_prompt = user_prompt

    def _build_prompt_override(
        user_prompt: str,
        *,
        user_context_text: str,
        unavailable_models: list[str] | None = None,
    ) -> tuple[str, str]:
        # Signature must match recommender.build_prompt. The MCP path forces a
        # fully pre-built system prompt, so all build inputs (incl. the runtime
        # unavailable_models override) are intentionally ignored here.
        del user_prompt
        del user_context_text
        del unavailable_models
        return system_prompt, forced_user_prompt

    recommender.build_prompt = _build_prompt_override
    try:
        return recommender.recommend_structured(forced_user_prompt, config)
    finally:
        recommender.build_prompt = original_build_prompt


def create_app() -> Any:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("roadmodel", log_level="ERROR")

    @app.tool()
    def recommend_model(
        task_description: str,
        context: str | None = None,
    ) -> dict[str, Any]:
        config = _load_runtime_config()
        user_context_text = user_context.read(config.user_context_path)
        system_prompt = _recommend_system_prompt(user_context_text, context)
        user_prompt = _recommend_user_prompt(task_description, context)
        return _recommend_structured_with_prompts(
            config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    @app.tool()
    def generate_phase_roadmap(
        project_brief: str,
        phase_number: int,
        prior_phases: list[str] | None = None,
    ) -> str:
        config = _load_runtime_config()
        user_context_text = user_context.read(config.user_context_path)
        system_prompt = _phase_roadmap_system_prompt(user_context_text)
        user_prompt = _phase_roadmap_user_prompt(project_brief, phase_number, prior_phases)
        return _provider_recommend(config, user_prompt, system_prompt)

    @app.tool()
    def read_catalog() -> dict[str, Any]:
        selector_text = _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
        model_tier_cost_scale_text = _read_bundled_doc(
            BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md"
        )
        catalog_raw = _read_bundled_doc(BUNDLED_CATALOG_PATH, "catalog.json")
        catalog_json: object = json.loads(catalog_raw)
        if not isinstance(catalog_json, dict):
            raise ValueError("Bundled catalog.json payload is not a JSON object.")
        source_doc_sha256 = catalog_json.get("source_doc_sha256")
        selector_key = "model" + "_selector_txt"
        return {
            selector_key: selector_text,
            "model_tier_cost_scale_md": model_tier_cost_scale_text,
            "catalog_json": catalog_json,
            "source_doc_sha256": source_doc_sha256,
        }

    return app


def main() -> None:
    try:
        from mcp.server.stdio import stdio_server
    except ModuleNotFoundError:
        print(
            "roadmodel-mcp: install with 'pip install roadmodel[mcp]' to enable the MCP server",
            file=sys.stderr,
        )
        sys.exit(2)

    _ = stdio_server
    app = create_app()
    app.run(transport="stdio")
