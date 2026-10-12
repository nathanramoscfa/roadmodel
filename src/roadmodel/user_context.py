# src/roadmodel/user_context.py
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
from typing import Final

from roadmodel.errors import BundledDocNotFoundError, UserContextNotFoundError
from roadmodel.private_files import atomic_private_write

DEFAULT_USER_CONTEXT_HOME = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "roadmodel"
    / "user-context.md"
)
_USER_CONTEXT_TEMPLATE: Final = "user-context.example.md"


def default_user_context_home() -> Path:
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "roadmodel"
        / "user-context.md"
    )


def resolve(*, cli_path: Path | None) -> Path:
    candidates: list[Path] = []
    if cli_path is not None:
        candidates.append(cli_path.expanduser())

    env_path = os.environ.get("ROADMODEL_USER_CONTEXT")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    default_path = default_user_context_home()
    candidates.append(default_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return default_path


def bootstrap(target: Path) -> None:
    target = target.expanduser()
    template_path = resources.files("roadmodel.data") / _USER_CONTEXT_TEMPLATE
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BundledDocNotFoundError(_USER_CONTEXT_TEMPLATE) from exc
    atomic_private_write(target, template_text.encode("utf-8"))


def read(path: Path) -> str:
    target = path.expanduser()
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise UserContextNotFoundError(target) from exc


def is_bootstrap_unchanged(path: Path) -> bool:
    try:
        text = path.expanduser().read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return "$XXX" in text
