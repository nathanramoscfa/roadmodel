# hatch_build.py
"""Custom hatch build hook for the roadmodel wheel/sdist.

Contract:
    This hook keeps the bundled data in sync with the docs/ source of truth
    at every build; do not commit src/roadmodel/data/ files to git — they are
    build output. user-context.example.md is the first-run bootstrap template
    the CLI copies to ~/.config/roadmodel/user-context.md on first invocation;
    the user's filled-in copy is NEVER bundled (it carries personal
    subscription state).

Behaviour:
    On `initialize`, copy the source-of-truth docs from docs/ into
    src/roadmodel/data/, creating the directory if absent, preserving mtime
    via shutil.copy2, and register the destinations in
    build_data["force_include"] so they land in the built wheel at
    roadmodel/data/<filename>. Every allowlisted input, including the
    generated catalog, must already exist as a regular file in the tree.
"""

from __future__ import annotations

import shutil
import stat
import tomllib
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

BUNDLED_DOCS: dict[str, str] = {
    "claude-commands/roadmap-project.md": "roadmap-project.md",
    "claude-commands/roadmap-phase.md": "roadmap-phase.md",
    "claude-commands/roadmap-step.md": "roadmap-step.md",
    "claude-commands/roadmap-refresh.md": "roadmap-refresh.md",
    "claude-commands/roadmodel-upgrade.md": "roadmodel-upgrade.md",
    "model-selector.txt": "model-selector.txt",
    "model-tier-cost-scale.md": "model-tier-cost-scale.md",
    "settings-display.md": "settings-display.md",
    "user-context.example.md": "user-context.example.md",
    "catalog.json": "catalog.json",
    "benchmarks.json": "benchmarks.json",
    "context-windows.json": "context-windows.json",
    "effort-tokens.json": "effort-tokens.json",
    "templates/phase-roadmap-template.md": "phase-roadmap-template.md",
    "templates/project-roadmap-template.md": "project-roadmap-template.md",
    "templates/planning-kit-how-to-use.md": "planning-kit-how-to-use.md",
    "templates/prompt-project-roadmap.md": "prompt-project-roadmap.md",
    "templates/prompt-phase-roadmap.md": "prompt-phase-roadmap.md",
}


def _no_links(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or (
            current.exists()
            and getattr(current.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("Build inputs and outputs must not be links.")


def _source(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.anchor or path.drive or ".." in path.parts:
        raise ValueError("Build input must remain inside the source tree.")
    _no_links(root, path)
    source = root / path
    if not source.is_file():
        raise FileNotFoundError("Required allowlisted build input is missing.")
    return source


class BundleDocsHook(BuildHookInterface):  # type: ignore[misc]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root).resolve()
        _source(root, "pyproject.toml")
        manifest = tomllib.loads((root / "pyproject.toml").read_text())
        for target in ("wheel", "sdist"):
            for name in manifest["tool"]["hatch"]["build"]["targets"][target]["include"]:
                _source(root, name)
        dest_dir = root / "src" / "roadmodel" / "data"
        _no_links(root, dest_dir.relative_to(root))
        dest_dir.mkdir(parents=True, exist_ok=True)

        force_include = build_data.setdefault("force_include", {})
        for source_relpath, dest_name in BUNDLED_DOCS.items():
            src = _source(root, "docs/" + source_relpath)
            dest = dest_dir / dest_name
            if not src.is_file():
                raise FileNotFoundError(
                    f"hatch_build.py: required source doc missing at {src}; "
                    "the bundled data files must exist in docs/ before building."
                )
            _no_links(root, dest.relative_to(root))
            shutil.copy2(src, dest)
            force_include[str(dest)] = f"roadmodel/data/{dest_name}"

        # The multi-project updater ships in the wheel as a module, so each
        # machine's scheduled copy can upgrade roadmodel and hand over to the
        # updater in that release (`python -m roadmodel.update_projects`). One
        # source file: scripts/update_projects.py, mapped in rather than
        # copied under src/.
        if self.target_name == "wheel":
            for name in (
                "update_projects",
                "agent_context",
                "agent_rules",
                "upgrade_fleet",
                "worktree_memory",
                "updater_lock",
            ):
                updater = _source(root, "scripts/" + name + ".py")
                if not updater.is_file():
                    raise FileNotFoundError(f"hatch_build.py: {updater} is missing")
                force_include[str(updater)] = f"roadmodel/{name}.py"
