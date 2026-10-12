"""Load the private writer from this checkout, independent of ambient packages."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from types import ModuleType


@lru_cache(maxsize=1)
def private_files() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "src/roadmodel/private_files.py"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Private file helper is unavailable.")
    module = ModuleType("roadmodel_local_private")
    # The fixed checkout companion is reviewed source, never downloaded input.
    # Avoid bytecode writes during otherwise nonmutating diagnostic operations.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102  # nosec B102
    return module
