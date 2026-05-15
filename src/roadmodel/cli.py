# src/roadmodel/cli.py
from __future__ import annotations

import json
import os
import traceback
from functools import wraps
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

import click

from roadmodel import __version__, user_context
from roadmodel import recommend as recommender
from roadmodel.config import load_config
from roadmodel.errors import (
    BundledDocNotFoundError,
    MalformedResponseError,
    MissingProviderKeyError,
    ProviderCallError,
    UserContextNotFoundError,
)

F = TypeVar("F", bound=Callable[..., Any])


def _error_mapped(command: F) -> F:
    @wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except click.ClickException:
            raise
        except click.exceptions.Exit:
            raise
        except click.Abort:
            raise
        except MissingProviderKeyError as exc:
            click.echo(str(exc), err=True)
            raise click.exceptions.Exit(2) from exc
        except ProviderCallError as exc:
            click.echo(str(exc), err=True)
            raise click.exceptions.Exit(3) from exc
        except MalformedResponseError as exc:
            click.echo(f"Malformed provider response (truncated to 2KB):\n{exc.raw_text}", err=True)
            raise click.exceptions.Exit(4) from exc
        except BundledDocNotFoundError as exc:
            click.echo(str(exc), err=True)
            raise click.exceptions.Exit(5) from exc
        except UserContextNotFoundError as exc:
            click.echo(
                f"User context file not found: {exc.path}. "
                "create the file, or omit --user-context to let the CLI bootstrap one",
                err=True,
            )
            raise click.exceptions.Exit(7) from exc
        except Exception as exc:
            if os.environ.get("ROADMODEL_DEBUG") == "1":
                traceback.print_exc()
            else:
                click.echo(f"Unexpected error: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc

    return cast(F, wrapper)


def _catalog_doc_resource(doc: str) -> tuple[Traversable, str]:
    normalized = doc.lower()
    if normalized == "tier-cost-scale":
        return recommender.BUNDLED_TIER_COST_PATH, "model-tier-cost-scale.md"
    return recommender.BUNDLED_SELECTOR_PATH, "model-selector.txt"


def _read_catalog_doc(doc: str) -> str:
    resource, filename = _catalog_doc_resource(doc)
    try:
        return resource.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BundledDocNotFoundError(filename) from exc


def _catalog_doc_path(doc: str) -> Path:
    resource, filename = _catalog_doc_resource(doc)
    try:
        with resources.as_file(resource) as on_disk_path:
            return on_disk_path
    except FileNotFoundError as exc:
        raise BundledDocNotFoundError(filename) from exc


@click.group(help=None)
def cli() -> None:
    """Recommend AI models and access paths from the bundled roadmodel catalog."""


@cli.command()
@click.argument("prompt", required=False)
@click.option(
    "--file",
    "prompt_file",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=False),
    help="Read the recommendation prompt from a file.",
)
@click.option("--json", "emit_json", is_flag=True, help="Emit parsed structured output as JSON.")
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai", "google"], case_sensitive=False),
    help="Provider override (anthropic/openai/google).",
)
@click.option(
    "--model", type=str, help="Optional explicit model id override for the selected provider."
)
@click.option(
    "--user-context",
    "user_context_path",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=False),
    help="Path to user-context.md override.",
)
@_error_mapped
def recommend(
    prompt: str | None,
    prompt_file: Path | None,
    emit_json: bool,
    provider: str | None,
    model: str | None,
    user_context_path: Path | None,
) -> None:
    """Recommend MODEL/PLATFORM/MAX MODE/THINKING/CONVERSATION/RATIONALE for a prompt."""

    if prompt and prompt_file:
        raise click.UsageError("Use either PROMPT or --file, not both.")
    if not prompt and not prompt_file:
        raise click.UsageError("Provide PROMPT or --file PATH.")
    if prompt is not None:
        prompt_text = prompt
    elif prompt_file is not None:
        prompt_text = prompt_file.read_text(encoding="utf-8")
    else:
        raise click.UsageError("Provide PROMPT or --file PATH.")
    config = load_config(
        cli_provider=provider,
        cli_model=model,
        cli_user_context=user_context_path,
    )

    if user_context_path is not None and not user_context_path.expanduser().exists():
        raise UserContextNotFoundError(user_context_path.expanduser())
    env_user_context = os.environ.get("ROADMODEL_USER_CONTEXT")
    if (
        user_context_path is None
        and env_user_context
        and not Path(env_user_context).expanduser().exists()
    ):
        raise UserContextNotFoundError(Path(env_user_context).expanduser())

    if not config.user_context_path.exists():
        bootstrap_target = user_context.default_user_context_home()
        user_context.bootstrap(bootstrap_target)
        click.echo(
            f"Created {bootstrap_target} from bundled template. "
            "Edit it with your real subscription state, then re-run.",
            err=True,
        )
        raise click.exceptions.Exit(6)

    if user_context.is_bootstrap_unchanged(config.user_context_path):
        click.echo(
            "Warning: user-context.md still includes placeholder values like $XXX; proceeding anyway.",
            err=True,
        )

    result = recommender.recommend(prompt_text, config)
    if emit_json:
        click.echo(json.dumps(result))
        return
    click.echo(
        "\n".join(
            [
                f"MODEL: {result['model']}",
                f"PLATFORM: {result['platform']}",
                f"MAX MODE: {result['max_mode']}",
                f"THINKING: {result['thinking']}",
                f"CONVERSATION: {result['conversation']}",
                f"RATIONALE: {result['rationale']}",
            ]
        )
    )


@cli.group()
def catalog() -> None:
    """Read bundled catalog documents shipped with roadmodel."""


@catalog.command("show")
@click.option(
    "--doc",
    type=click.Choice(["selector", "tier-cost-scale"], case_sensitive=False),
    default="selector",
    show_default=True,
    help="Catalog document to print.",
)
@_error_mapped
def catalog_show(doc: str) -> None:
    """Print a bundled catalog document to stdout."""

    click.echo(_read_catalog_doc(doc), nl=False)


@catalog.command("path")
@click.option(
    "--doc",
    type=click.Choice(["selector", "tier-cost-scale"], case_sensitive=False),
    default="selector",
    show_default=True,
    help="Catalog document path to print.",
)
@_error_mapped
def catalog_path(doc: str) -> None:
    """Print the on-disk path for a bundled catalog document."""

    click.echo(str(_catalog_doc_path(doc)))


@cli.group()
def context() -> None:
    """Inspect or initialize the user-context.md file used at recommendation time."""


@context.command("show")
@click.option(
    "--user-context",
    "user_context_path",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=False),
    help="Path override for user-context.md.",
)
@_error_mapped
def context_show(user_context_path: Path | None) -> None:
    """Print the resolved user-context.md file."""

    resolved = user_context.resolve(cli_path=user_context_path)
    if user_context_path is not None and not user_context_path.expanduser().exists():
        raise UserContextNotFoundError(user_context_path.expanduser())
    if not resolved.exists():
        raise UserContextNotFoundError(resolved)
    click.echo(user_context.read(resolved), nl=False)


@context.command("path")
@click.option(
    "--user-context",
    "user_context_path",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=False),
    help="Path override for user-context.md.",
)
@_error_mapped
def context_path(user_context_path: Path | None) -> None:
    """Print the resolved user-context.md path (or bootstrap target when missing)."""

    click.echo(str(user_context.resolve(cli_path=user_context_path)))


@context.command("init")
@click.option("--force", is_flag=True, help="Overwrite the existing file if present.")
@_error_mapped
def context_init(force: bool) -> None:
    """Bootstrap user-context.md from the bundled template at the default config location."""

    target = user_context.default_user_context_home()
    if target.exists() and not force:
        raise click.ClickException(f"{target} already exists; re-run with --force to overwrite.")
    user_context.bootstrap(target)
    click.echo(str(target))


@cli.command()
@_error_mapped
def version() -> None:
    """Print the installed roadmodel version."""

    click.echo(__version__)


def main() -> None:
    cli()
