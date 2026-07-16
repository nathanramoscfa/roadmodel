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
    roadmodel/data/<filename>. If docs/catalog.json is missing at build
    time (e.g. fresh clone before the first cron commit), invoke
    update/build_catalog.py to generate it so the wheel always ships a
    catalog.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

BUNDLED_DOCS: dict[str, str] = {
    "model-selector.txt": "model-selector.txt",
    "model-tier-cost-scale.md": "model-tier-cost-scale.md",
    "settings-display.md": "settings-display.md",
    "user-context.example.md": "user-context.example.md",
    "catalog.json": "catalog.json",
    "templates/phase-roadmap-template.md": "phase-roadmap-template.md",
    "templates/project-roadmap-template.md": "project-roadmap-template.md",
    "templates/planning-kit-how-to-use.md": "planning-kit-how-to-use.md",
}


class BundleDocsHook(BuildHookInterface):  # type: ignore[misc]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        src_dir = root / "docs"
        dest_dir = root / "src" / "roadmodel" / "data"
        dest_dir.mkdir(parents=True, exist_ok=True)

        catalog_path = src_dir / "catalog.json"
        if not catalog_path.is_file():
            subprocess.run(  # noqa: S603 — controlled invocation of repo script
                [sys.executable, str(root / "update" / "build_catalog.py")],
                cwd=str(root),
                check=True,
            )

        force_include = build_data.setdefault("force_include", {})
        for source_relpath, dest_name in BUNDLED_DOCS.items():
            src = src_dir / source_relpath
            dest = dest_dir / dest_name
            if not src.is_file():
                raise FileNotFoundError(
                    f"hatch_build.py: required source doc missing at {src}; "
                    "the bundled data files must exist in docs/ before building."
                )
            shutil.copy2(src, dest)
            force_include[str(dest)] = f"roadmodel/data/{dest_name}"
