# src/roadmodel/user_context.py
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Final

from importlib import resources

from roadmodel.errors import BundledDocNotFoundError, UserContextNotFoundError

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


def _repo_user_context_candidate() -> Path | None:
    cwd = Path.cwd()
    for root in (cwd, *cwd.parents):
        if (root / ".git").exists():
            return root / "docs" / "user-context.md"
    return None


def resolve(*, cli_path: Path | None) -> Path:
    candidates: list[Path] = []
    if cli_path is not None:
        candidates.append(cli_path.expanduser())

    env_path = os.environ.get("ROADMODEL_USER_CONTEXT")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    default_path = default_user_context_home()
    candidates.append(default_path)

    repo_path = _repo_user_context_candidate()
    if repo_path is not None:
        candidates.append(repo_path)

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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template_text, encoding="utf-8")
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)


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
