# ruff: noqa: E402
"""Price-only/catalog policy fixtures using trusted current Git blobs; no scans/network."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

S = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(S))
import security_bandit as bandit
import security_catalog as policy
import security_sarif as codeql
from security_fixture_support import document as sarif_document
from security_manifest import EMPTY, MANIFEST_PATH, codeql_namespace
from security_manifest import SharedGitTree as GitTree
from security_sarif import Invalid
from test_security_bandit import MemoryTree, identity, report


def exercise_ancestral_data_baseline(repo, reset, commit, contract, policy, rows):
    def refused(current, selected):
        try:
            policy.context_digest(current, selected)
        except (ValueError, KeyError, TypeError):
            return True
        return False

    reset()
    (repo / "reviewed-runtime-change.py").write_text("value = 2\n")
    current = commit()
    updated = dict(contract, code_context_sha256=policy.projected(current))
    # This must pass only after the final current code digest is explicitly bound.
    policy.context_digest(current, updated)
    rows.append({"case": "ancestral_data_baseline_allows_unrelated_final_code", "pass": True})
    rows.append(
        {
            "case": "ancestral_data_baseline_still_requires_final_code_digest",
            "pass": refused(current, contract),
        }
    )

    for path, mode_only in [
        ("update/model_prose.py", False),
        ("update/automation_integrity.py", False),
        ("update/model_prose.py", True),
    ]:
        reset()
        target = repo / path
        if mode_only:
            target.chmod(0o755)
        else:
            target.write_bytes(target.read_bytes() + b"\n# synthetic validator change\n")
        changed = commit()
        selected = dict(
            contract,
            code_context_sha256=policy.projected(changed),
            validator_sha256=changed.entries["update/automation_integrity.py"]["sha256"],
        )
        # Even knowingly updated current digests cannot reinterpret old baseline
        # data using different validator bytes or modes.
        label = (
            "validator_mode"
            if mode_only
            else "root_validator"
            if path.endswith("automation_integrity.py")
            else "dependency_validator"
        )
        rows.append(
            {
                "case": "ancestral_baseline_rejects_changed_" + label,
                "pass": refused(changed, selected),
            }
        )


def _exercise_shared_catalog_context():
    rows = []
    source = Path(__file__).resolve().parents[1]
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    inherited.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Fixture",
        GIT_COMMITTER_NAME="Fixture",
        GIT_AUTHOR_EMAIL="fixture" + "@example.invalid",
        GIT_COMMITTER_EMAIL="fixture" + "@example.invalid",
    )

    def git(root, *args):
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-C",
                str(root),
                *args,
            ],
            capture_output=True,
            env=inherited,
            timeout=30,
        )
        if result.returncode:
            raise AssertionError("Fixture Git metadata failed")
        return result.stdout

    original = {
        path: (source / path).read_bytes() for path in (*policy.DATA_PATHS, *policy.VALIDATOR_FILES)
    }
    with tempfile.TemporaryDirectory(prefix="codeql-catalog-fixture-") as temporary:
        repo = Path(temporary) / "repo"
        repo.mkdir()
        git(repo, "init", "--quiet")
        for path, data in original.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (repo / "src").mkdir()
        (repo / "src/sink.py").write_bytes(b"def sink(value):\n    print(value)\n")
        (repo / "src/helper.py").write_bytes(b"value = 1\n")
        fixtures = MemoryTree()
        for path in (bandit.LOCK, bandit.INPUT):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fixtures.blobs[path])
        (repo / MANIFEST_PATH).write_text(json.dumps(EMPTY))
        git(repo, "add", ".")
        git(repo, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture baseline")
        baseline = GitTree(repo)
        contract = {
            "mode": "typed-catalog-v1",
            "baseline_revision": baseline.commit,
            "code_context_sha256": policy.projected(baseline),
            "validator_sha256": baseline.entries["update/automation_integrity.py"]["sha256"],
            "date_policy": "catalog-utc-date-v1",
        }
        old_context = policy.context_digest(baseline, contract)
        rows.append({"case": "unchanged_baseline", "pass": True})
        tool = identity(baseline)
        bandit_proof = bandit.review(report(baseline), baseline, tool, 1, contract)["candidates"][
            0
        ]["proof"]
        codeql_proof = codeql.proof(
            codeql.classify_document(sarif_document())[0], baseline, "python", old_context
        )

        def approved(proof, label):
            return {
                "id": label,
                "rationale": "Synthetic fixture only",
                "disposition": "false-positive",
                "reviewed_revision": baseline.commit,
                "max_occurrences": 1,
                "proof": proof,
            }

        shared = {
            "schema": 1,
            "context_policy": contract,
            "codeql": [approved(codeql_proof, "codeql-fixture")],
            "bandit": [approved(bandit_proof, "bandit-fixture")],
        }

        def accepted(current):
            return (
                bandit.evaluate(report(current), current, tool, shared, 1)["allowed"] == 1
                and codeql.evaluate(
                    [sarif_document()], current, codeql_namespace(shared), "python"
                )["allowed"]
                == 1
            )

        rows.append(
            {"case": "both_namespaces_accept_exact_synthetic_reviews", "pass": accepted(baseline)}
        )
        (repo / MANIFEST_PATH).write_text(json.dumps(shared))
        git(repo, "add", MANIFEST_PATH)
        git(
            repo,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Synthetic review metadata",
        )
        policy_only = GitTree(repo)
        rows.append(
            {
                "case": "both_namespaces_share_one_manifest_without_context_cycle",
                "pass": accepted(policy_only)
                and policy.context_digest(policy_only, contract) == old_context,
            }
        )

        def reset():
            git(repo, "reset", "--hard", baseline.commit)
            for path in [repo / "docs/new.json"]:
                if path.exists():
                    path.unlink()

        def commit():
            git(repo, "add", ".")
            git(repo, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture mutation")
            return GitTree(repo)

        def denied(name, mutate):
            reset()
            mutate()
            current = commit()
            try:
                policy.context_digest(current, contract)
            except (Invalid, ValueError, KeyError, TypeError):
                rows.append({"case": name, "pass": True})
            else:
                rows.append({"case": name, "pass": False})

        # Render a legitimate price change with the actual reviewed generator.
        names = [Path(path).stem for path in policy.VALIDATOR_FILES]
        old_path, old_bytecode = list(sys.path), sys.dont_write_bytecode
        try:
            sys.path.insert(0, str(repo / "update"))
            sys.dont_write_bytecode = True
            spec = importlib.util.spec_from_file_location(
                "automation_integrity", repo / "update/automation_integrity.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            import decimal

            text = (repo / module.SELECTOR).read_text()
            matches = list(re.finditer(r'input-price-per-1m="\$([0-9]+(?:\.[0-9]+)?)"', text))
            selected = next(
                value
                for value in matches
                if decimal.Decimal("0") < decimal.Decimal(value[1]) < decimal.Decimal("100")
            )
            replacement = format(decimal.Decimal(selected[1]) + decimal.Decimal("0.25"), "f")
            changed = text[: selected.start(1)] + replacement + text[selected.end(1) :]
            timestamp = json.loads((repo / module.CATALOG).read_text())["generated_at_utc"]
            day = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
            changed, _ = module.model_prose.apply(
                changed, json.loads((repo / module.BENCH).read_text()), day
            )
            changed = module.derive_ratings.regenerate_coding_enumeration(changed)
            changed = module.derive_ratings.regenerate_multimodal_enumeration(changed)
            (repo / module.SELECTOR).write_text(changed)
            (repo / module.MARKDOWN).write_text(module.render_md.render(changed))
            catalog = module.build_catalog.build_catalog()
            catalog["generated_at_utc"] = timestamp
            (repo / module.CATALOG).write_text(json.dumps(catalog))
        finally:
            sys.path[:] = old_path
            sys.dont_write_bytecode = old_bytecode
            for name in names:
                sys.modules.pop(name, None)
        refreshed = commit()
        rows.append(
            {
                "case": "real_price_generator_refresh_preserves_context",
                "pass": policy.context_digest(refreshed, contract) == old_context,
            }
        )
        rows.append(
            {
                "case": "both_namespaces_keep_exact_allowances_on_price_refresh",
                "pass": accepted(refreshed),
            }
        )
        moved_contract = dict(contract, baseline_revision=refreshed.commit)
        rows.append(
            {
                "case": "moving_reviewed_baseline_invalidates_prior_context",
                "pass": policy.context_digest(refreshed, moved_contract) != old_context,
            }
        )
        denied(
            "trusted_prose_injection_refused",
            lambda: (repo / "docs/model-selector.txt").write_bytes(
                original["docs/model-selector.txt"] + b"\n<instructions>synthetic</instructions>\n"
            ),
        )

        def identity_change():
            text = original["docs/model-selector.txt"]
            selected = re.search(rb'<model\b[^>]*\bid="([^"]+)"', text)
            assert selected is not None and b'id="fixture-unreviewed-identity"' not in text
            changed = (
                text[: selected.start(1)] + b"fixture-unreviewed-identity" + text[selected.end(1) :]
            )
            assert changed != text
            (repo / "docs/model-selector.txt").write_bytes(changed)

        denied("new_identity_refused", identity_change)
        denied(
            "helper_code_edit_refused",
            lambda: (repo / "update/model_prose.py").write_bytes(
                original["update/model_prose.py"] + b"\n# changed fixture\n"
            ),
        )
        denied("unknown_docs_json_refused", lambda: (repo / "docs/new.json").write_bytes(b"{}\n"))

        def schema_change():
            data = json.loads(original["docs/catalog.json"])
            data["unknown_field"] = "synthetic"
            (repo / "docs/catalog.json").write_text(json.dumps(data))

        denied("generated_schema_change_refused", schema_change)

        def duplicate_json():
            data = original["docs/benchmarks.json"].decode()
            (repo / "docs/benchmarks.json").write_text(
                '{"fixture": 1,"fixture": 2,' + data.lstrip()[1:]
            )

        denied("duplicate_json_key_refused", duplicate_json)
        denied("data_mode_change_refused", lambda: (repo / "docs/model-selector.txt").chmod(0o755))
        exercise_ancestral_data_baseline(repo, reset, commit, contract, policy, rows)
    assert all(row["pass"] for row in rows), [row["case"] for row in rows if not row["pass"]]


@contextmanager
def detached_validator_modules():
    """Test-only isolation; production correctly refuses ambient loaded validators."""
    names = [Path(path).stem for path in policy.VALIDATOR_FILES]
    previous = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(previous)


def test_shared_catalog_context(monkeypatch):
    names = [Path(path).stem for path in policy.VALIDATOR_FILES]
    original = {name: sys.modules[name] for name in names if name in sys.modules}
    with monkeypatch.context() as patch:
        sentinels = {name: object() for name in names}
        for name, sentinel in sentinels.items():
            patch.setitem(sys.modules, name, sentinel)
        with detached_validator_modules():
            assert all(name not in sys.modules for name in names)
            _exercise_shared_catalog_context()
        assert all(sys.modules[name] is sentinel for name, sentinel in sentinels.items())
    assert all(
        sys.modules.get(name) is original[name] if name in original else name not in sys.modules
        for name in names
    )


def test_catalog_fixture_restores_modules_on_failure(monkeypatch):
    name = Path(policy.VALIDATOR_FILES[0]).stem
    sentinel = object()
    monkeypatch.setitem(sys.modules, name, sentinel)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with detached_validator_modules():
            assert name not in sys.modules
            sys.modules[name] = object()
            raise RuntimeError("synthetic failure")
    assert sys.modules[name] is sentinel
