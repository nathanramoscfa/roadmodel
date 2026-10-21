# src/roadmodel/mcp_server.py
# mypy: disable-error-code="import-not-found,untyped-decorator"
from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

from roadmodel import recommend as recommender
from roadmodel import user_context
from roadmodel.config import Config, load_config
from roadmodel.errors import BundledDocNotFoundError, MissingProviderKeyError
from roadmodel.providers import ProviderAdapter
from roadmodel.providers._safety import transport_timeout

_CONTEXT_BYTES = 262_144
_PROMPT_BYTES = 1_048_576
# Marks a tool error whose text names a setup fix and may reach the client.
_CONFIG_ERROR_META = "roadmodel/configuration-error"
_STDIO_ACTIVE: ContextVar[bool] = ContextVar("roadmodel_private_stdio", default=False)


class _PrivateMCPLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        sdk = record.name.startswith("mcp.") or record.pathname.replace("\\", "/").endswith(
            "/mcp/shared/session.py"
        )
        return not (_STDIO_ACTIVE.get() and sdk)


_MCP_LOG_FILTER = _PrivateMCPLogs()


@contextmanager
def _private_mcp_logs() -> Iterator[None]:
    # SDK diagnostics can include protocol bodies. Other host tasks retain
    # their own logging context; no levels, handlers or factories are replaced.
    for name in (
        "",
        "mcp.server.lowlevel.server",
        "mcp.server.fastmcp.server",
        "mcp.server.fastmcp.resources.resource_manager",
    ):
        logging.getLogger(name).addFilter(_MCP_LOG_FILTER)
    token = _STDIO_ACTIVE.set(True)
    try:
        yield
    finally:
        _STDIO_ACTIVE.reset(token)


def _bounded_context(path: Path) -> str:
    with path.open("rb") as handle:
        raw = handle.read(_CONTEXT_BYTES + 1)
    if len(raw) > _CONTEXT_BYTES:
        raise ValueError("Private context exceeds the tool byte limit.")
    return raw.decode("utf-8")


def _check_prompts(system: str, user: str) -> None:
    if len(system.encode("utf-8")) + len(user.encode("utf-8")) > _PROMPT_BYTES:
        raise ValueError("Combined prompts exceed the tool byte limit.")


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
    selector_text = recommender.selector_for_engine(
        _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
    )
    tier_cost_text = _read_bundled_doc(BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md")
    parts = [selector_text, tier_cost_text, user_context_text]
    # Caller-supplied project context belongs in the user message below.
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
    "- A model that always thinks (Opus 5.5, Sonnet 5.5, Haiku 5.5, the Fable "
    'models — always-thinks="yes" in <model-options>) has no thinking '
    "toggle on any surface: emit EFFORT and NO THINKING line for it, never "
    "'THINKING: Off'.\n"
    "- FLAT-FUNDING GATE: when the chosen platform is subscription-funded, the "
    "model family is covered by that subscription, AND the user-context "
    "declares 'Consumption headroom: uncapped' for it (the operator does not "
    "exhaust that pool), price is FLAT across candidates — down-tiering saves "
    "the user NOTHING. HOLD the capability tier the task warrants (do NOT drop "
    "to a Sonnet-/Haiku-class model to 'save' $0, not even on trivial steps) "
    "and RAISE EFFORT to the top useful rung the model and surface support. "
    "Under an OPEN gate the complexity ladder is a FLOOR, not the final value: "
    "do not stop at 'High'. This applies to EVERY step in the roadmap.\n"
    "- CAPPED HEADROOM (the DEFAULT, and whenever the user-context says "
    "'Consumption headroom: capped' or reports a usage pool 'tight' / "
    "'exhausted'): the gate is CLOSED. The weekly usage pool is a real budget "
    "metered by model AND by effort level, so BOTH axes follow the ordinary "
    "budget-priority ladder step by step: under Cost or Balanced a bounded, "
    "well-specified step takes a mid-tier model at the complexity-ladder "
    "EFFORT (Low/Medium/High), and the frontier model and XHigh/Max are "
    "reserved for the steps whose complexity warrants them; under Quality the "
    "frontier model is held and only EFFORT follows the ladder. Never raise a "
    "step to Max 'because it is funded'.\n"
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
    selector_text = recommender.selector_for_engine(
        _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
    )
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
        max_output_tokens=4096,
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
        ladder_table: str | None = None,
    ) -> tuple[str, str]:
        # Signature must match recommender.build_prompt. The MCP path forces a
        # fully pre-built system prompt, so all build inputs (incl. the runtime
        # unavailable_models override, its authoritative flag, the ladder flag
        # and its table) are intentionally ignored here.
        del user_prompt
        del user_context_text
        del unavailable_models
        del availability_authoritative
        del ladder
        del ladder_table
        return system_prompt, forced_user_prompt

    recommender.build_prompt = _build_prompt_override
    try:
        return recommender.recommend_structured(
            forced_user_prompt, config, user_context_text="", max_output_tokens=4096
        )
    finally:
        recommender.build_prompt = original_build_prompt


def _user_context_text_without_provider() -> str:
    """The operator's user-context text for tools that make no engine call:
    ``$ROADMODEL_USER_CONTEXT`` → ``[paths].user_context`` in config.toml → the
    default config-home file; empty when none exists."""
    from roadmodel.config import _config_user_context_override, _read_config_toml

    override = None
    if not os.environ.get("ROADMODEL_USER_CONTEXT"):
        override = _config_user_context_override(_read_config_toml())
    resolved = user_context.resolve(cli_path=override)
    return _bounded_context(resolved) if resolved.exists() else ""


def create_app() -> Any:
    from mcp import types as mcp_types
    from mcp.server.fastmcp import FastMCP
    from pydantic import Field

    class SafeFastMCP(FastMCP):
        async def run_stdio_async(self) -> None:
            with _private_mcp_logs():
                await self._run_private_stdio()

        async def _run_private_stdio(self) -> None:
            import anyio
            from mcp.server.stdio import stdio_server
            from mcp.shared.message import SessionMessage

            # Transport validation happens before the tool handlers. Pydantic
            # exceptions include raw input, and the lowlevel server logs them.
            async with stdio_server() as (incoming, outgoing):
                sender, receiver = anyio.create_memory_object_stream[SessionMessage | Exception](0)

                async def forward() -> None:
                    async with sender:
                        async for message in incoming:
                            if not isinstance(message, Exception):
                                root = message.message.root
                                try:
                                    # The session performs a second validation
                                    # pass and logs its raw exceptions at WARNING.
                                    # Validate those envelopes before handing over.
                                    if isinstance(root, mcp_types.JSONRPCRequest):
                                        mcp_types.ClientRequest.model_validate(
                                            root.model_dump(
                                                by_alias=True, mode="json", exclude_none=True
                                            )
                                        )
                                    elif isinstance(root, mcp_types.JSONRPCNotification):
                                        mcp_types.ClientNotification.model_validate(
                                            root.model_dump(
                                                by_alias=True, mode="json", exclude_none=True
                                            )
                                        )
                                except Exception:
                                    if isinstance(root, mcp_types.JSONRPCRequest):
                                        await outgoing.send(
                                            SessionMessage(
                                                mcp_types.JSONRPCMessage(
                                                    mcp_types.JSONRPCError(
                                                        jsonrpc="2.0",
                                                        id=root.id,
                                                        error=mcp_types.ErrorData(
                                                            code=-32602,
                                                            message="Invalid request parameters",
                                                        ),
                                                    )
                                                )
                                            )
                                        )
                                    continue
                            await sender.send(
                                ValueError("Invalid MCP transport message")
                                if isinstance(message, Exception)
                                else message
                            )

                async with anyio.create_task_group() as group:
                    group.start_soon(forward)
                    await self._mcp_server.run(
                        receiver, outgoing, self._mcp_server.create_initialization_options()
                    )

        def _setup_handlers(self) -> None:
            super()._setup_handlers()
            # This server exposes tools only. These unused SDK handlers echo
            # unknown prompt names/resource URIs in logs and error messages.
            self._mcp_server.request_handlers.pop(mcp_types.GetPromptRequest, None)
            self._mcp_server.request_handlers.pop(mcp_types.ReadResourceRequest, None)
            original = self._mcp_server.request_handlers[mcp_types.CallToolRequest]

            async def guarded(request: mcp_types.CallToolRequest) -> Any:
                # Lowlevel MCP logs an unknown name before FastMCP dispatch.
                # Refuse it before that diagnostic can echo client input. The
                # registered tools are the allowlist, so a new tool can't be
                # left off it.
                if self._tool_manager.get_tool(request.params.name) is None:
                    return mcp_types.ServerResult(self._safe_error())
                result = await original(request)
                if (
                    isinstance(result.root, mcp_types.CallToolResult)
                    and result.root.isError
                    and (result.root.meta or {}).get(_CONFIG_ERROR_META) is not True
                ):
                    return mcp_types.ServerResult(self._safe_error())
                return result

            self._mcp_server.request_handlers[mcp_types.CallToolRequest] = guarded

        @staticmethod
        def _safe_error() -> Any:
            return mcp_types.CallToolResult(
                isError=True,
                content=[
                    mcp_types.TextContent(
                        type="text",
                        text="Tool call failed; check input limits and provider configuration.",
                    )
                ],
            )

        @staticmethod
        def _config_error(error: MissingProviderKeyError) -> Any:
            # load_config builds these messages from provider and variable
            # names only (never a key, a path or tool input), and they name
            # the fix, which the generic error hides.
            return mcp_types.CallToolResult(
                isError=True,
                content=[mcp_types.TextContent(type="text", text=str(error))],
                _meta={_CONFIG_ERROR_META: True},
            )

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            try:
                if name in {"score_candidates", "roadmap_settings"}:
                    arguments = dict(arguments)
                    for field in ("category", "complexity", "budget"):
                        value = arguments.get(field)
                        if isinstance(value, str):
                            arguments[field] = value.strip().lower()
                return await super().call_tool(name, arguments)
            except Exception as exc:
                # FastMCP wraps the tool's exception in a ToolError.
                cause = exc.__cause__ if exc.__cause__ is not None else exc
                if isinstance(cause, MissingProviderKeyError):
                    return self._config_error(cause)
                # Covers pre-function validation, unknown names, and provider
                # failures. FastMCP's default includes arbitrary exception text.
                return self._safe_error()

    app = SafeFastMCP("roadmodel", log_level="ERROR")

    @app.tool()
    def recommend_model(
        task_description: str = Field(..., min_length=1, max_length=16_384),
        context: str | None = Field(None, max_length=65_536),
    ) -> dict[str, Any]:
        """Recommend a model + access method for ``task_description``.

        Returns the structured payload: ``model``, ``platform``, optional
        ``backup``, ``rationale`` (+ ``rationale_sections``), ``conversation``,
        and ``settings`` — the per-surface controls. ``settings`` carries ONLY
        the dials the chosen platform actually exposes (Claude Code: effort,
        ultracode when on, and thinking on models that can turn it off;
        Codex / OpenAI API: intelligence; Cursor: max_mode + thinking), never a
        placeholder for a control that surface lacks.
        """
        if not task_description.strip():
            raise ValueError("Task must contain text.")
        config = _load_runtime_config()
        user_context_text = _bounded_context(config.user_context_path)
        system_prompt = _recommend_system_prompt(user_context_text, context)
        user_prompt = _recommend_user_prompt(task_description, context)
        _check_prompts(system_prompt, user_prompt)
        with transport_timeout(120):
            return _recommend_structured_with_prompts(
                config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

    @app.tool()
    def generate_phase_roadmap(
        project_brief: str = Field(..., min_length=1, max_length=65_536),
        phase_number: int = Field(..., ge=1, le=1_000, strict=True),
        prior_phases: list[str] | None = Field(None, max_length=24),  # noqa: B008 - MCP schema
    ) -> str:
        if not project_brief.strip():
            raise ValueError("Brief must contain text.")
        prior = prior_phases or []
        if any(len(item) > 8_192 for item in prior) or sum(map(len, prior)) > 131_072:
            raise ValueError("Prior phase summaries exceed tool limits.")
        config = _load_runtime_config()
        user_context_text = _bounded_context(config.user_context_path)
        system_prompt = _phase_roadmap_system_prompt(user_context_text)
        user_prompt = _phase_roadmap_user_prompt(project_brief, phase_number, prior_phases)
        _check_prompts(system_prompt, user_prompt)
        with transport_timeout(120):
            return _provider_recommend(config, user_prompt, system_prompt)

    @app.tool()
    def score_candidates(
        category: Literal[
            "coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed"
        ],
        complexity: Literal["low", "medium", "high"],
        novel: bool = False,
        budget: Literal["cheap", "balanced", "best"] | None = None,
        top: int = Field(10, ge=0, le=100, strict=True),
    ) -> dict[str, Any]:
        """Rank (model, platform, effort) candidates in CODE — no engine call.

        ``category`` is one of coding / planning / agentic / multimodal /
        long-context / knowledge / speed (the selector's Step 1); ``complexity``
        is low / medium / high (Step 2); ``novel`` marks a High task that is
        novel problem-solving or multi-step proof. ``budget`` overrides the
        user-context's declared Budget priority. Returns the primary, the
        funded cross-provider backup (or ``backup_warning`` when the
        user-context funds only one provider), and every candidate with its
        quality / requirement-penalty / cost-penalty terms, so the pick can be
        audited term by term. Call it after classifying the task; use the
        result to write the rationale.
        """
        from roadmodel import scoring

        # No engine call, so no provider key is needed: resolve the user-context
        # the way the CLI does (env override → config.toml → default home).
        text = _user_context_text_without_provider()
        posture = (budget or scoring.declared_budget(text)).strip().lower()
        task = scoring.Task(
            category=category.strip().lower(),
            complexity=complexity.strip().lower(),
            novel=novel,
            budget=posture,
        )
        payload = scoring.rank(task, text).to_dict()
        payload["candidates"] = payload["candidates"][: max(0, top)]
        return payload

    @app.tool()
    def roadmap_settings(
        category: Literal[
            "coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed"
        ],
        complexity: Literal["low", "medium", "high"],
        novel: bool = False,
        phase: bool = False,
        budget: Literal["cheap", "balanced", "best"] | None = None,
    ) -> dict[str, Any]:
        """A roadmap Settings table as the full ladder, in CODE — no engine call.

        The Cost / Balanced / Quality picks /recommend shows for the step's
        classification, each with its effort and a backup from another maker,
        read with every usage pool at headroom, plus the column the step runs
        (``runs``) and the rule for a tight or exhausted pool. ``phase`` is the
        session that writes a phase roadmap: it runs Quality at its deepest
        rung. ``markdown`` is the table to paste under the step (or phase);
        same as `roadmodel ladder`.
        """
        from roadmodel import scoring

        text = _user_context_text_without_provider()
        posture = (budget or scoring.declared_budget(text)).strip().lower()
        task = scoring.Task(
            category=category.strip().lower(),
            complexity=complexity.strip().lower(),
            novel=novel,
            budget=posture,
        )
        settings = scoring.settings_ladder(task, text, phase=phase)
        if settings is None:
            raise ValueError("No model in this user-context's pool carries an AA Index.")
        return settings

    @app.tool()
    def read_catalog() -> dict[str, Any]:
        """Return the bundled offline reasoning payload: the model selector, the
        tier-cost scale, the parsed catalog, its source-doc hash, the
        per-surface settings-DISPLAY rules, and ``output_contract_version`` —
        the version of the selector's output block contract (2 = every setting
        field is platform-conditional and EFFORT/THINKING are separate fields;
        1 = MAX MODE always emitted and THINKING carried the effort level).
        """
        selector_text = recommender.selector_for_engine(
            _read_bundled_doc(BUNDLED_SELECTOR_PATH, "model-selector.txt")
        )
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
        # whose THINKING is a toggle and whose Ultracode is its own switch).
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
