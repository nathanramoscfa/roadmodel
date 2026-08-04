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
BUNDLED_SETTINGS_DISPLAY_PATH: Traversable = (
    resources.files("roadmodel.data") / "settings-display.md"
)
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


# The roadmap path emits the SAME annotation blocks as the single-prompt path,
# but it never carried the single-prompt path's front-loaded reminders (those
# live in recommend._SAAS_HEADER). Generating a long document dilutes attention
# across dozens of blocks, and measured drift was real: with the selector alone,
# roadmap blocks correctly omitted MAX MODE and kept THINKING a toggle, but
# down-tiered the model and settled at `High` effort on a flat-funded plan —
# ignoring the <objective> FLAT-FUNDING GATE that the single-prompt path honors.
# Front-load the same rules here so the two paths cannot diverge.
_ROADMAP_CONTRACT_HEADER = (
    "BEFORE YOU WRITE ANY MODEL SELECTION BLOCK, apply these rules from the "
    "selector below. They are the ones most often lost when generating a long "
    "document:\n"
    "- PLATFORM-CONDITIONAL SETTINGS: emit ONLY the setting lines the chosen "
    "PLATFORM exposes. MAX MODE only where the platform exposes Max Mode "
    "(today: Cursor). EFFORT and THINKING only where it exposes a reasoning "
    "dial. ORCHESTRATION only where it exposes one (today: Claude Code). A dial "
    "the platform lacks gets NO LINE AT ALL — never 'Off', never 'N/A'.\n"
    "- EFFORT and THINKING are DIFFERENT FIELDS. EFFORT carries the level "
    "(Low/Medium/High/XHigh/Max/Ultracode, Ultracode being the top rung). "
    "THINKING is a two-position toggle taking ONLY 'On' or 'Off'. "
    "'THINKING: Max' is invalid.\n"
    "- FLAT-FUNDING GATE: when the chosen platform is subscription-funded, the "
    "model family is covered by that subscription, and the budget is not "
    "exhausted, price is FLAT across candidates — down-tiering saves the user "
    "NOTHING. HOLD the capability tier the task warrants (do NOT drop to a "
    "Sonnet-/Haiku-class model to 'save' $0, not even on trivial steps) and "
    "RAISE EFFORT to the top useful rung the model and surface support. Under "
    "an open gate the complexity ladder is a FLOOR, not the final value: do not "
    "stop at 'High'. This applies to EVERY step in the roadmap.\n"
    "- The operator's platform allowlist / denylist is a HARD filter applied "
    "before scoring; never recommend an excluded platform.\n"
    "- TIER CLAIMS MUST BE READ OFF THE ROW. When a RATIONALE cites a model's "
    "tier for a category, use the rating <model-options> gives THAT EXACT model "
    "id for THAT exact category. Do NOT generalise from a model family or "
    "'lineage' (e.g. 'S-tier for the Sonnet lineage') and do NOT round an A up "
    "to S — tiers are per-model, and a sibling's rating says nothing about this "
    "one.\n"
)


def _phase_roadmap_system_prompt(user_context_text: str) -> str:
    template_text = _read_bundled_doc(BUNDLED_PHASE_TEMPLATE_PATH, "phase-roadmap-template.md")
    selector_text = _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
    tier_cost_text = _read_bundled_doc(BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md")
    return "\n\n".join(
        [
            _ROADMAP_CONTRACT_HEADER,
            template_text,
            selector_text,
            tier_cost_text,
            user_context_text,
        ]
    )


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
        availability_authoritative: bool = False,
        ladder: bool = False,
    ) -> tuple[str, str]:
        # Signature must match recommender.build_prompt. The MCP path forces a
        # fully pre-built system prompt, so all build inputs (incl. the runtime
        # unavailable_models override, its authoritative flag, and the ladder
        # flag) are intentionally ignored here.
        del user_prompt
        del user_context_text
        del unavailable_models
        del availability_authoritative
        del ladder
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
        """Recommend a model + access method for ``task_description``.

        Returns the structured payload: ``model``, ``platform``, optional
        ``backup``, ``rationale`` (+ ``rationale_sections``), ``conversation``,
        and ``settings`` — the per-surface controls. ``settings`` carries ONLY
        the dials the chosen platform actually exposes (Claude Code: effort +
        thinking; Codex / OpenAI API: intelligence; Cursor: max_mode +
        thinking), never a placeholder for a control that surface lacks.
        """
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
        """Return the bundled offline reasoning payload: the model selector, the
        tier-cost scale, the parsed catalog, its source-doc hash, the
        per-surface settings-DISPLAY rules, and ``output_contract_version`` —
        the version of the selector's output block contract (2 = every setting
        field is platform-conditional and EFFORT/THINKING are separate fields;
        1 = MAX MODE always emitted and THINKING carried the effort level).
        """
        selector_text = _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
        model_tier_cost_scale_text = _read_bundled_doc(
            BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md"
        )
        catalog_raw = _read_bundled_doc(BUNDLED_CATALOG_PATH, "catalog.json")
        catalog_json: object = json.loads(catalog_raw)
        if not isinstance(catalog_json, dict):
            raise ValueError("Bundled catalog.json payload is not a JSON object.")
        source_doc_sha256 = catalog_json.get("source_doc_sha256")
        # The selector emits PLATFORM-CONDITIONAL setting fields (MAX MODE /
        # EFFORT / THINKING / ORCHESTRATION — only the dials the chosen platform
        # exposes). Ship the per-surface DISPLAY rules alongside it, or an
        # offline consumer has no way to render a surface's real controls and
        # emits raw selector vocabulary (e.g. "Thinking: XHigh" for Claude Code,
        # whose THINKING is a toggle and whose top effort rung is Ultracode).
        settings_display_text = _read_bundled_doc(
            BUNDLED_SETTINGS_DISPLAY_PATH, "settings-display.md"
        )
        selector_key = "model" + "_selector_txt"
        return {
            selector_key: selector_text,
            "model_tier_cost_scale_md": model_tier_cost_scale_text,
            "settings_display_md": settings_display_text,
            "catalog_json": catalog_json,
            "source_doc_sha256": source_doc_sha256,
            # Which block contract the bundled selector emits, so an offline
            # consumer can tell a v1 kit (MAX MODE always present, THINKING
            # carrying the effort level) from a v2 one WITHOUT diffing the doc.
            # Mirrors <output-format>'s "OUTPUT CONTRACT VERSION:" line.
            "output_contract_version": recommender.OUTPUT_CONTRACT_VERSION,
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
