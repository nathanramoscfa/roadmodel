# ruff: noqa: E402
"""Run isolated, hash-locked Bandit analysis; keep raw findings in memory."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.metadata as metadata
import io
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_codeql_sarif import execution_binding, read, write_receipt
from security_bandit import (
    INPUT,
    LOCK,
    PROFILE,
    VERSION,
    evaluate,
    inventory,
    lock_versions,
    review,
    sha,
    validate_identity,
)
from security_manifest import EMPTY, MANIFEST_PATH, SharedGitTree, manifest
from security_sarif import MAX_JSON, digest, load_json, require
from security_source import bounded_command, bounded_regular

IMPLEMENTATIONS = [
    "check_bandit.py",
    "security_bandit.py",
    "security_manifest.py",
    "security_sarif.py",
    "security_source.py",
    "check_codeql_sarif.py",
    "security_catalog.py",
]


def implementation_digest(tree):
    items = []
    for name in IMPLEMENTATIONS:
        path = "scripts/" + name
        require(path in tree.blobs)
        actual = bounded_regular(Path(__file__).resolve().parent, name)[0]
        require(actual == tree.blobs[path])
        items.append([path, sha(actual)])
    return digest(items)


def tool_identity(tree):
    require(sys.flags.isolated and sys.dont_write_bytecode and sys.version_info >= (3, 12))
    pins = lock_versions(tree)
    # The workflow installs this exact lock with --require-hashes --no-compile.
    # Validate installed wheel RECORD content, not self-reported JSON versions.
    # No bytecode is allowed in these distributions, so imports cannot prefer an
    # unverified cached code object. Distribution identity excludes only generated
    # entry scripts (unused: this runner imports the module) and RECORD itself.
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    pending = ["bandit", "packaging"]
    rows = {}
    root = Path(sys.prefix).resolve()
    while pending:
        name = pending.pop()
        name = canonicalize_name(name)
        if name in rows:
            continue
        require(name in pins)
        dist = metadata.distribution(name)
        require(dist.version == pins[name])
        files = dist.files
        require(files is not None and 0 < len(files) <= 10000)
        items = []
        total = 0
        for item in files:
            relative = str(item)
            if relative.startswith("../"):
                # Console script shebangs are installation-specific and are never
                # executed here. Reject all other external RECORD paths.
                require(
                    relative.startswith("../../../bin/")
                    and "/" not in relative[len("../../../bin/") :]
                )
                continue
            path = Path(dist.locate_file(item))
            require(path.resolve().is_relative_to(root) and not path.is_symlink())
            require(path.suffix != ".pyc")
            if path.name == "RECORD":
                continue
            data = bounded_regular(path.parent.resolve(), path.name)[0]
            total += len(data)
            require(total <= 64 * 1024 * 1024)
            if item.hash is None:
                require(path.name in {"INSTALLER", "REQUESTED"})
            else:
                require(item.hash.mode == "sha256")
                actual = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                    .rstrip(b"=")
                    .decode("ascii")
                )
                require(actual == item.hash.value and item.size == len(data))
            items.append([relative, sha(data)])
        require(bool(items))
        # Require package directories to contain only RECORD-declared files;
        # extra modules and unlisted bytecode cannot escape the identity hash.
        base = Path(dist.locate_file(""))
        declared = {str(item) for item in files if not str(item).startswith("../")}
        package_names = {
            str(item).split("/")[0]
            for item in files
            if not str(item).startswith("../") and "/" in str(item)
        }
        for component in package_names:
            package = base / component
            require(not package.is_symlink())
            for actual in package.rglob("*"):
                require(not actual.is_symlink())
                if actual.is_file():
                    require(
                        actual.relative_to(base).as_posix() in declared and actual.suffix != ".pyc"
                    )
        rows[name] = {"name": name, "version": dist.version, "files_sha256": digest(sorted(items))}
        for specifier in dist.requires or []:
            requirement = Requirement(specifier)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                require(not requirement.url and not requirement.extras)
                dependency = canonicalize_name(requirement.name)
                require(dependency in pins and requirement.specifier.contains(pins[dependency]))
                pending.append(dependency)
    # Stevedore discovers installed entry points; forbid unbound third-party
    # Bandit plugins even if their distribution is outside Bandit's dependencies.
    groups = {"bandit.plugins", "bandit.blacklists", "bandit.formatters"}
    bandit_distributions = 0
    for installed in metadata.distributions():
        installed_name = canonicalize_name(installed.metadata["Name"])
        if installed_name == "bandit":
            bandit_distributions += 1
            require(Path(installed.locate_file("")).resolve().is_relative_to(root))
        for point in installed.entry_points:
            if point.group in groups:
                require(installed_name == "bandit")
    require(bandit_distributions == 1)
    identity = {
        "schema": 1,
        "bandit_version": VERSION,
        "python": ".".join(map(str, sys.version_info[:3])),
        "lock_sha256": sha(tree.blobs[LOCK]),
        "input_sha256": sha(tree.blobs[INPUT]),
        "implementation_sha256": implementation_digest(tree),
        "distributions": [rows[key] for key in sorted(rows)],
        "profile_sha256": digest(PROFILE),
    }
    validate_identity(identity, tree)
    return identity


class MemoryOutput(io.StringIO):
    name = "<private-memory>"

    def close(self):
        pass


@contextlib.contextmanager
def reject_scanner_errors():
    """Count error-level events without ever formatting their private messages."""

    class ErrorCounter(logging.Handler):
        errors = 0

        def emit(self, record):
            if record.levelno >= logging.ERROR:
                self.errors += 1

    counter = ErrorCounter()
    root = logging.getLogger()
    saved_handlers, saved_level, saved_disable = root.handlers, root.level, root.manager.disable
    try:
        root.handlers = [counter]
        root.setLevel(logging.WARNING)
        logging.disable(logging.NOTSET)
        yield
        require(counter.errors == 0)
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        logging.disable(saved_disable)


@contextlib.contextmanager
def uncached_entrypoints():
    """Use attested installed metadata, never a mutable ambient Stevedore cache."""
    from stevedore import _cache, extension

    original = _cache.get_group_all
    previous = extension.ExtensionManager.ENTRY_POINT_CACHE

    def direct(group, path=None):
        require(path is None)
        return list(metadata.entry_points(group=group))

    try:
        _cache.get_group_all = direct
        extension.ExtensionManager.ENTRY_POINT_CACHE = {}
        yield
    finally:
        _cache.get_group_all = original
        extension.ExtensionManager.ENTRY_POINT_CACHE = previous


def validate_query_inventory(extension_manager, report):
    expected = {
        group: [point.name for point in metadata.entry_points(group=group)]
        for group in ("bandit.plugins", "bandit.blacklists")
    }
    loaded = {
        "bandit.plugins": extension_manager.plugins,
        "bandit.blacklists": list(extension_manager.blacklists_mgr),
    }
    for group, plugins in loaded.items():
        names = [plugin.name for plugin in plugins]
        require(len(names) == len(set(names)) and sorted(names) == sorted(expected[group]))
    ids = [plugin.plugin._test_id for plugin in extension_manager.plugins]
    require(len(ids) == len(set(ids)))
    selected = [item for item in extension_manager.formatters if item.name == "json"]
    require(len(selected) == 1 and selected[0].plugin is report)
    return set(ids) | {"B001"}


def scan_worker(tree):
    before = tool_identity(tree)
    tree.verify_checkout()
    output = MemoryOutput()
    with (
        uncached_entrypoints(),
        contextlib.redirect_stdout(MemoryOutput()),
        contextlib.redirect_stderr(MemoryOutput()),
    ):
        # Bandit eagerly probes unused formatters (SARIF needs optional packages).
        # Verify complete query/blacklist loading and the selected JSON formatter
        # explicitly; unused output formats do not determine analysis coverage.
        saved_disable = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            from bandit.core.config import BanditConfig
            from bandit.core.extension_loader import MANAGER
            from bandit.core.manager import BanditManager
            from bandit.formatters.json import report
        finally:
            logging.disable(saved_disable)
        expected = validate_query_inventory(MANAGER, report)
        with reject_scanner_errors():
            manager = BanditManager(
                BanditConfig(),
                "file",
                debug=True,
                profile={"include": set(), "exclude": set()},
                quiet=True,
                ignore_nosec=True,
            )
            actual = {test._test_id for tests in manager.b_ts.tests.values() for test in tests}
            require(actual == expected)
            os.chdir(tree.root)
            manager.discover_files(inventory(tree), recursive=False, excluded_paths="")
            manager.run_tests()
            report(manager, output, "UNDEFINED", "UNDEFINED")
    require(before == tool_identity(tree))
    tree.verify_checkout()
    raw = output.getvalue().encode()
    require(len(raw) <= MAX_JSON)
    document = load_json(raw)
    return {
        "identity": before,
        "report": document,
        "returncode": 1 if document["results"] else 0,
        "raw_report_sha256": sha(raw),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--repo", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    worker = sub.add_parser("_worker")
    worker.add_argument("--repo", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args()
    require(sys.flags.isolated and sys.dont_write_bytecode)
    tree = SharedGitTree(args.repo)
    if args.command == "snapshot":
        implementation_digest(tree)
        tree.verify_checkout()
        write_receipt(args.output, tree.receipt())
        print("Bandit source snapshot verified.")
        return 0
    if args.command == "_worker":
        print(json.dumps(scan_worker(tree), allow_nan=False))
        return 0
    tree.verify_receipt(load_json(read(args.snapshot)))
    env = {
        key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "BANDIT"))
    }
    env.update(PYTHONDONTWRITEBYTECODE="1")
    raw = bounded_command(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "_worker",
            "--repo",
            str(tree.root),
        ],
        env,
        MAX_JSON,
        timeout=600,
    )
    result = load_json(raw)
    require(set(result) == {"identity", "report", "returncode", "raw_report_sha256"})
    tree.verify_receipt(load_json(read(args.snapshot)))
    value = manifest(load_json(tree.blobs[MANIFEST_PATH])) if MANIFEST_PATH in tree.blobs else EMPTY
    material = review(
        result["report"], tree, result["identity"], result["returncode"], value["context_policy"]
    )
    execution = execution_binding(tree, "python")
    execution.pop("query_policy")
    execution.pop("language")
    execution["scanner"] = "bandit"
    material.update(
        execution=execution,
        source_snapshot=tree.receipt(),
        raw_report_sha256=result["raw_report_sha256"],
    )
    # Valid scan evidence survives a later unmatched/stale finding refusal.
    write_receipt(args.review_output, material)
    summary = evaluate(result["report"], tree, result["identity"], value, result["returncode"])
    tree.verify_receipt(load_json(read(args.snapshot)))
    print(json.dumps(summary, sort_keys=True))
    return 1 if summary["blocking"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Bandit scan, source, coverage or reviewed allowance is invalid; gate refused.")
        raise SystemExit(1) from None
