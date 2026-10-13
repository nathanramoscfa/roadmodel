"""Validate typed catalog refreshes against a reviewed immutable code baseline."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from security_sarif import MANIFEST_PATH, digest, load_json, obj, require
from security_source import GitTree

DATA_PATHS = (
    "docs/model-selector.txt",
    "docs/model-tier-cost-scale.md",
    "docs/benchmarks.json",
    "docs/catalog.json",
    "docs/model-selector.md",
    "infra/model-availability.json",
    "update/claude-code-effort.json",
    "update/codex-reasoning.json",
    "update/gemini-thinking.json",
    "update/deepseek-thinking.json",
)
VALIDATOR_FILES = tuple(
    "update/" + name + ".py"
    for name in (
        "automation_integrity",
        "build_catalog",
        "derive_ratings",
        "model_prose",
        "render_md",
        "sync_static_availability",
        "selector_re",
        "stale_claims",
    )
)


def projected(tree, manifest_path=None) -> str:
    manifest_path = manifest_path or getattr(tree, "manifest_path", MANIFEST_PATH)
    require(manifest_path in {MANIFEST_PATH, ".github/security-allowances.json"})
    return digest(
        {
            "policy": "typed-catalog-code-v1",
            "files": [
                [path, row["mode"], row["sha256"]]
                for path, row in sorted(tree.entries.items())
                if path not in {*DATA_PATHS, manifest_path}
            ],
        }
    )


def timestamp(data: bytes) -> dt.datetime:
    value = json.loads(data)["generated_at_utc"]
    require(isinstance(value, str))
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0))
    return parsed


def validate_with_bound_code(baseline, current, day: dt.date) -> None:
    # Call only after code projection equality and validator digest checks.
    module_names = [Path(path).stem for path in VALIDATOR_FILES]
    require(not any(name in sys.modules for name in module_names))
    original_path = list(sys.path)
    original_bytecode = sys.dont_write_bytecode
    original_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="codeql-reviewed-catalog-") as temporary:
            root = Path(temporary)
            update = root / "update"
            update.mkdir(mode=0o700)
            for path in VALIDATOR_FILES:
                destination = root / path
                destination.write_bytes(current.blobs[path])
                destination.chmod(0o600)
            sys.dont_write_bytecode = True
            sys.path.insert(0, str(update))
            path = update / "automation_integrity.py"
            spec = importlib.util.spec_from_file_location("automation_integrity", path)
            require(spec is not None and spec.loader is not None)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            require(tuple(module.INPUTS) == DATA_PATHS)
            module.validate_documents(
                lambda path: baseline.blobs[path].decode("utf-8"),
                lambda path: current.blobs[path].decode("utf-8"),
                day,
            )
    finally:
        sys.path[:] = original_path
        sys.dont_write_bytecode = original_bytecode
        for name in module_names:
            sys.modules.pop(name, None)
        os.umask(original_umask)


def context_digest(tree, policy: dict) -> str:
    policy = obj(policy)
    require(
        set(policy)
        == {"mode", "baseline_revision", "code_context_sha256", "validator_sha256", "date_policy"}
    )
    require(policy["mode"] == "typed-catalog-v1" and policy["date_policy"] == "catalog-utc-date-v1")
    require(
        isinstance(policy["baseline_revision"], str)
        and re.fullmatch(r"[0-9a-f]{40}", policy["baseline_revision"])
    )
    manifest_path = getattr(tree, "manifest_path", MANIFEST_PATH)
    code_digest = projected(tree, manifest_path)
    require(code_digest == policy["code_context_sha256"])
    require(tree.entries["update/automation_integrity.py"]["sha256"] == policy["validator_sha256"])
    baseline = GitTree(tree.root, policy["baseline_revision"])
    require(projected(baseline, manifest_path) == code_digest)
    for path in DATA_PATHS:
        require(path in baseline.entries and path in tree.entries)
        require(baseline.entries[path]["mode"] == tree.entries[path]["mode"] == "100644")
        if path.endswith(".json"):
            load_json(baseline.blobs[path])
            load_json(tree.blobs[path])
    before = timestamp(baseline.blobs["docs/catalog.json"])
    after = timestamp(tree.blobs["docs/catalog.json"])
    # Deterministic rendering date, not today's date. This upper bound never
    # invalidates an unchanged admitted catalog on a later day.
    require(before <= after <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    if any(baseline.blobs[path] != tree.blobs[path] for path in DATA_PATHS):
        validate_with_bound_code(baseline, tree, after.date())
    return digest(
        {
            "policy": "typed-catalog-v1",
            "date_policy": policy["date_policy"],
            "code_context_sha256": code_digest,
            "baseline_data": [
                [path, baseline.entries[path]["mode"], baseline.entries[path]["sha256"]]
                for path in DATA_PATHS
            ],
        }
    )
