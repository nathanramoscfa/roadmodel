# ruff: noqa: E402
"""Synthetic + existing SARIF contract tests; no CodeQL scan or network calls."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

S = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(S))
import security_sarif as gate
from check_codeql_sarif import language_binding
from security_source import GitTree

FIXTURES = Path(__file__).parent / "fixtures" / "security-sarif"


class MemoryTree:
    def __init__(self):
        self.root_uri = "file:///fixture/"
        self.blobs = {
            "src/sink.py": b"def sink(value):\n    print(value)\n",
            "src/helper.py": b"value = 1\n",
            "README.md": b"fixture documentation\n",
            gate.MANIFEST_PATH: b"fixture manifest\n",
        }
        self.entries = {
            path: {"mode": "100644", "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in self.blobs.items()
        }

    context_digest = GitTree.context_digest
    bind_region = GitTree.bind_region

    def change(self, path, data):
        self.blobs[path] = data
        self.entries[path] = {
            "mode": self.entries.get(path, {}).get("mode", "100644"),
            "sha256": hashlib.sha256(data).hexdigest(),
        }


def document():
    def location(path, index, line=1):
        return {
            "physicalLocation": {
                "artifactLocation": {"uri": path, "index": index},
                "region": {"startLine": line, "endLine": line, "startColumn": 1, "endColumn": 4},
            }
        }

    result = {
        "ruleId": "py/fixture",
        "ruleIndex": 0,
        "message": {"text": "fixture message"},
        "locations": [location("src/sink.py", 0, 2)],
        "relatedLocations": [location("src/helper.py", 1)],
        "codeFlows": [
            {
                "threadFlows": [
                    {
                        "locations": [
                            {"location": location("src/helper.py", 1)},
                            {"location": location("src/sink.py", 0, 2)},
                        ]
                    }
                ]
            }
        ],
    }
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeQL",
                        "semanticVersion": "2.27.2",
                        "rules": [
                            {
                                "id": "py/fixture",
                                "properties": {"security-severity": "7.5", "tags": ["security"]},
                                "defaultConfiguration": {"level": "warning"},
                            }
                        ],
                    },
                    "extensions": [
                        {"name": "codeql/python-queries", "semanticVersion": "1.0.0+fixture"}
                    ],
                },
                "columnKind": "utf16CodeUnits",
                "artifacts": [
                    {"location": {"uri": "src/sink.py", "index": 0}},
                    {"location": {"uri": "src/helper.py", "index": 1}},
                ],
                "properties": {
                    "codeqlConfigSummary": {
                        "disableDefaultQueries": False,
                        "queries": [{"uses": "security-extended", "type": "builtinSuite"}],
                    }
                },
                "results": [result],
            }
        ],
    }


def approval(tree, doc):
    finding = gate.classify_document(doc)[0]
    return {
        "schema": 1,
        "context_policy": "whole-tree-v1",
        "entries": [
            {
                "id": "fixture-exact-review",
                "disposition": "false-positive",
                "rationale": "Synthetic test only; not an active approval",
                "reviewed_revision": "a" * 40,
                "max_occurrences": 1,
                "proof": gate.proof(finding, tree, "python", tree.context_digest()),
            }
        ],
    }


class ExactAllowanceTests(unittest.TestCase):
    def setUp(self):
        self.tree, self.doc = MemoryTree(), document()
        self.manifest = approval(self.tree, self.doc)

    def blocked(self, docs=None):
        try:
            return (
                gate.evaluate(docs or [self.doc], self.tree, self.manifest, "python")["blocking"]
                > 0
            )
        except gate.Invalid:
            return True

    def test_exact_once(self):
        self.assertEqual(
            gate.evaluate([self.doc], self.tree, self.manifest, "python")["allowed"], 1
        )

    def test_result_duplicated_across_documents(self):
        value = gate.evaluate(
            [self.doc, copy.deepcopy(self.doc)], self.tree, self.manifest, "python"
        )
        self.assertEqual((value["allowed"], value["blocking"]), (1, 1))

    def test_same_rule_new_location(self):
        second = copy.deepcopy(self.doc["runs"][0]["results"][0])
        second["locations"][0]["physicalLocation"]["region"]["startLine"] = 1
        second["locations"][0]["physicalLocation"]["region"]["endLine"] = 1
        self.doc["runs"][0]["results"].append(second)
        self.assertTrue(self.blocked())

    def test_file_edit_outside_span(self):
        self.tree.change("src/sink.py", self.tree.blobs["src/sink.py"] + b"outside = 1\n")
        self.assertTrue(self.blocked())

    def test_helper_not_displayed_in_flow_still_changes_context(self):
        self.tree.change("README.md", b"changed semantic input\n")
        self.assertTrue(self.blocked())

    def test_new_file_changes_context(self):
        self.tree.change("new.json", b"{}\n")
        self.assertTrue(self.blocked())

    def test_source_mode_changes_context(self):
        self.tree.entries["src/sink.py"]["mode"] = "100755"
        self.assertTrue(self.blocked())

    def test_manifest_content_excluded_from_its_own_context(self):
        before = self.tree.context_digest()
        self.tree.change(gate.MANIFEST_PATH, b"new review metadata\n")
        self.assertEqual(self.tree.context_digest(), before)

    def test_message_changes(self):
        self.doc["runs"][0]["results"][0]["message"]["text"] = "changed"
        self.assertTrue(self.blocked())

    def test_flow_state_changes(self):
        self.doc["runs"][0]["results"][0]["codeFlows"][0]["threadFlows"][0]["locations"][0][
            "state"
        ] = {"value": {"text": "changed"}}
        self.assertTrue(self.blocked())

    def test_related_location_changes(self):
        self.doc["runs"][0]["results"][0]["relatedLocations"][0]["physicalLocation"]["region"][
            "endColumn"
        ] = 5
        self.assertTrue(self.blocked())

    def test_cli_version_changes(self):
        self.doc["runs"][0]["tool"]["driver"]["semanticVersion"] = "2.27.3"
        self.assertTrue(self.blocked())

    def test_pack_version_changes(self):
        self.doc["runs"][0]["tool"]["extensions"][0]["semanticVersion"] = "1.0.1"
        self.assertTrue(self.blocked())

    def test_rule_metadata_changes(self):
        self.doc["runs"][0]["tool"]["driver"]["rules"][0]["properties"]["security-severity"] = "8.0"
        self.assertTrue(self.blocked())

    def test_query_configuration_changes(self):
        self.doc["runs"][0]["properties"]["codeqlConfigSummary"]["queries"][0]["uses"] = (
            "security-and-quality"
        )
        self.assertTrue(self.blocked())

    def test_duplicate_manifest_proof_refuses(self):
        duplicate = copy.deepcopy(self.manifest["entries"][0])
        duplicate["id"] = "other-id"
        self.manifest["entries"].append(duplicate)
        self.assertTrue(self.blocked())

    def test_unused_current_language_refuses(self):
        self.doc["runs"][0]["results"] = []
        self.assertTrue(self.blocked())

    def test_other_language_is_not_unused_here(self):
        duplicate = copy.deepcopy(self.manifest["entries"][0])
        duplicate["id"] = "js-fixture"
        duplicate["proof"]["language"] = "javascript-typescript"
        duplicate["proof"]["rule_id"] = "js/fixture"
        self.manifest["entries"].append(duplicate)
        self.assertFalse(self.blocked())

    def test_sarif_suppression_never_approves(self):
        self.manifest["entries"] = []
        self.doc["runs"][0]["results"][0]["suppressions"] = [
            {"kind": "inSource", "status": "accepted"}
        ]
        self.assertTrue(self.blocked())

    def test_unhandled_location_carrier_never_matches(self):
        self.doc["runs"][0]["results"][0]["stacks"] = [{"frames": []}]
        self.assertTrue(self.blocked())

    def test_unknown_base_id_refuses(self):
        self.doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"][
            "uriBaseId"
        ] = "UNKNOWN"
        self.assertTrue(self.blocked())

    def test_artifact_index_uri_mismatch_refuses(self):
        self.doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"][
            "index"
        ] = 1
        self.assertTrue(self.blocked())

    def test_column_convention_changes_proof(self):
        self.doc["runs"][0]["columnKind"] = "unicodeCodePoints"
        self.assertTrue(self.blocked())

    def test_run_level_flow_location_resolves_equivalently(self):
        run = self.doc["runs"][0]
        locations = run["results"][0]["codeFlows"][0]["threadFlows"][0]["locations"]
        run["threadFlowLocations"] = copy.deepcopy(locations)
        locations[:] = [{"index": 0}, {"index": 1}]
        self.assertFalse(self.blocked())

    def test_run_level_flow_location_change_refuses(self):
        run = self.doc["runs"][0]
        locations = run["results"][0]["codeFlows"][0]["threadFlows"][0]["locations"]
        run["threadFlowLocations"] = copy.deepcopy(locations)
        locations[:] = [{"index": 0}, {"index": 1}]
        run["threadFlowLocations"][0]["location"]["physicalLocation"]["region"]["endColumn"] = 5
        self.assertTrue(self.blocked())

    def test_matrix_language_binding(self):
        language_binding(self.doc, "python")
        with self.assertRaises(gate.Invalid):
            language_binding(self.doc, "javascript-typescript")

    def test_zero_results_failed_analysis(self):
        self.doc["runs"][0]["results"] = []
        self.doc["runs"][0]["invocations"] = [{"executionSuccessful": False}]
        with self.assertRaises(gate.Invalid):
            gate.classify_document(self.doc)


class GitSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codeql-source-fixture-")
        self.directory = Path(self.temp.name)
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Fixture",
            GIT_COMMITTER_NAME="Fixture",
            GIT_AUTHOR_EMAIL="fixture" + "@example.invalid",
            GIT_COMMITTER_EMAIL="fixture" + "@example.invalid",
        )
        self.git("init", "--quiet")
        for path, content in MemoryTree().blobs.items():
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        self.tree = GitTree(self.repo)

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(self.repo), *args],
            env=self.env,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, "Synthetic Git setup failed")
        return result.stdout

    def test_clean_snapshot_and_receipt(self):
        self.tree.verify_receipt(self.tree.receipt())

    def test_worktree_content_drift(self):
        (self.repo / "src/sink.py").write_bytes(b"changed\n")
        with self.assertRaises(gate.Invalid):
            self.tree.verify_checkout()

    def test_worktree_mode_drift(self):
        (self.repo / "src/sink.py").chmod(0o755)
        with self.assertRaises(gate.Invalid):
            self.tree.verify_checkout()

    def test_worktree_symlink_refused(self):
        target = self.directory / "outside"
        target.write_bytes(self.tree.blobs["src/sink.py"])
        source = self.repo / "src/sink.py"
        source.unlink()
        source.symlink_to(target)
        with self.assertRaises((gate.Invalid, OSError)):
            self.tree.verify_checkout()

    def test_hardlink_refused(self):
        os.link(self.repo / "src/sink.py", self.directory / "linked")
        with self.assertRaises(gate.Invalid):
            self.tree.verify_checkout()

    def test_untracked_source_refused(self):
        (self.repo / "untracked.py").write_bytes(b"pass\n")
        with self.assertRaises(gate.Invalid):
            self.tree.verify_checkout()

    def test_commit_symlink_refused(self):
        source = self.repo / "src/sink.py"
        source.unlink()
        source.symlink_to("helper.py")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        with self.assertRaises(gate.Invalid):
            GitTree(self.repo)

    def test_commit_gitlink_refused(self):
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.tree.commit + ",vendor")
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        with self.assertRaises(gate.Invalid):
            GitTree(self.repo)

    def test_changed_commit_rejects_old_receipt(self):
        receipt = self.tree.receipt()
        (self.repo / "README.md").write_bytes(b"new\n")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        with self.assertRaises(gate.Invalid):
            GitTree(self.repo).verify_receipt(receipt)

    def test_missing_source_region_rejected(self):
        with self.assertRaises(gate.Invalid):
            self.tree.bind_region("src/missing.py", {"startLine": 1}, "utf16CodeUnits")

    def test_out_of_bounds_region_rejected(self):
        with self.assertRaises(gate.Invalid):
            self.tree.bind_region("src/sink.py", {"startLine": 99}, "utf16CodeUnits")

    def test_untracked_manifest_not_accepted(self):
        self.git("rm", "--quiet", gate.MANIFEST_PATH)
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        (self.repo / gate.MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / gate.MANIFEST_PATH).write_bytes(b"untracked approval")
        with self.assertRaises(gate.Invalid):
            GitTree(self.repo).verify_checkout()


_CONTRACT = json.loads((FIXTURES / "manifest.json").read_text())["fixtures"]


@pytest.mark.parametrize("row", _CONTRACT, ids=[row["file"] for row in _CONTRACT])
def test_synthetic_sarif_contract(row):
    raw = (FIXTURES / row["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    try:
        count = sum(value.blocking for value in gate.classify_document(gate.load_json(raw)))
        observed = ("block:" if count else "pass:") + str(count)
    except gate.Invalid:
        observed = "reject"
    assert observed == row["expected"] or (
        row["expected"] == "reject-or-unallowable" and observed in {"reject", "block:1"}
    )


class ImplicitSrcrootTests(unittest.TestCase):
    def setUp(self):
        self.tree = MemoryTree()
        self.run = document()["runs"][0]
        self.location = copy.deepcopy(self.run["results"][0]["locations"][0])
        artifact = self.location["physicalLocation"]["artifactLocation"]
        artifact.pop("index")
        artifact["uriBaseId"] = "%SRCROOT%"

    def test_absent_map_matches_explicit_verified_root(self):
        implicit = gate.Canonicalizer(self.run, self.tree).location(self.location)
        self.run["originalUriBaseIds"] = {"%SRCROOT%": {"uri": self.tree.root_uri}}
        self.assertEqual(gate.Canonicalizer(self.run, self.tree).location(self.location), implicit)

    def test_explicit_invalid_or_conflicting_maps_refuse(self):
        invalid = [
            None,
            [],
            {},
            {"OTHER": {"uri": self.tree.root_uri}},
            {"%SRCROOT%": None},
            {"%SRCROOT%": {"uri": "file:///outside/"}},
            {"%SRCROOT%": {"uri": self.tree.root_uri, "uriBaseId": "OTHER"}},
        ]
        for value in invalid:
            self.run["originalUriBaseIds"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(gate.Invalid):
                gate.Canonicalizer(self.run, self.tree).location(self.location)

    def test_unknown_bases_unsafe_paths_and_index_disagreement_refuse(self):
        canon = gate.Canonicalizer(self.run, self.tree)
        for base in [None, 1, "OTHER", "SRCROOT", "%srcroot%"]:
            with self.assertRaises(gate.Invalid):
                canon.uri({"uri": "src/sink.py", "uriBaseId": base})
        for uri in ["../src/sink.py", "/src/sink.py", "file:///src/sink.py", "%2e%2e/src/sink.py"]:
            with self.assertRaises(gate.Invalid):
                canon.uri({"uri": uri, "uriBaseId": "%SRCROOT%"})
        with self.assertRaises(gate.Invalid):
            canon.uri({"index": 0, "uriBaseId": "OTHER"})
        with self.assertRaises(gate.Invalid):
            canon.uri({"index": 0, "uri": "src/helper.py", "uriBaseId": "%SRCROOT%"})

    def test_implicit_map_preserves_file_and_region_binding(self):
        for path, line in [("untracked.py", 1), ("src/sink.py", 999999)]:
            value = copy.deepcopy(self.location)
            value["physicalLocation"]["artifactLocation"]["uri"] = path
            value["physicalLocation"]["region"] = {"startLine": line}
            with self.assertRaises(gate.Invalid):
                gate.Canonicalizer(self.run, self.tree).location(value)


class MetricBaselineTests(unittest.TestCase):
    def setUp(self):
        self.run = document()["runs"][0]
        self.metric = {"rule": {"index": 0}, "ruleId": "py/fixture", "value": 1}

    def canonical(self):
        return gate.canonical_metrics(self.run, [self.metric])

    def test_optional_baseline_presence_and_value_are_hashed(self):
        absent = gate.digest(self.canonical())
        self.metric["baseline"] = 0
        present = gate.digest(self.canonical())
        self.assertNotEqual(absent, present)
        self.metric["baseline"] = 1
        self.assertNotEqual(present, gate.digest(self.canonical()))
        self.metric["baseline"] = 1.5
        self.assertEqual(self.canonical()[0]["baseline"], 1.5)

    def test_invalid_baselines_refuse(self):
        for value in [None, True, False, "1", [], {}, float("inf"), float("-inf"), float("nan")]:
            self.metric["baseline"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(gate.Invalid):
                self.canonical()

    def test_other_metric_keys_remain_closed(self):
        self.metric["unknown"] = 1
        with self.assertRaises(gate.Invalid):
            self.canonical()


class InlineDataflowTaxaTests(unittest.TestCase):
    def setUp(self):
        self.tree = MemoryTree()
        self.doc = document()
        self.run = self.doc["runs"][0]
        self.result = self.run["results"][0]
        self.location = self.result["codeFlows"][0]["threadFlows"][0]["locations"][0]
        self.taxon = {"id": "synthetic-kind", "properties": {"CodeQL/DataflowRole": "step"}}
        self.location["taxa"] = [self.taxon]

    def canonical(self):
        return gate.Canonicalizer(self.run, self.tree).result(self.result)

    def test_inline_shape_preserved_and_changed_identity_stales_proof(self):
        actual = self.canonical()["codeFlows"][0]["threadFlows"][0]["locations"][0]["taxa"]
        self.assertEqual(actual, [self.taxon])
        manifest = approval(self.tree, self.doc)
        self.assertEqual(gate.evaluate([self.doc], self.tree, manifest, "python")["blocking"], 0)
        before = gate.digest(self.canonical())
        self.taxon["id"] = "changed-synthetic-kind"
        self.assertNotEqual(before, gate.digest(self.canonical()))
        with self.assertRaises(gate.Invalid):
            gate.evaluate([self.doc], self.tree, manifest, "python")

    def test_unknown_role_property_and_reference_variants_refuse(self):
        variants = [
            {"id": "fixture", "properties": {"CodeQL/DataflowRole": "source"}},
            {"id": "fixture", "properties": {"CodeQL/DataflowRole": "step", "extra": True}},
            {"id": "fixture"},
            {"id": "../private space", "properties": self.taxon["properties"]},
        ]
        for field, value in [
            ("index", 0),
            ("guid", "00000000-0000-4000-8000-000000000000"),
            ("toolComponent", {"index": 0}),
        ]:
            variant = copy.deepcopy(self.taxon)
            variant[field] = value
            variants.append(variant)
        for variant in variants:
            self.location["taxa"] = [variant]
            with self.assertRaises(gate.Invalid):
                self.canonical()

    def test_ambiguous_taxonomy_duplicates_and_oversized_arrays_refuse(self):
        self.run["taxonomies"] = []
        with self.assertRaises(gate.Invalid):
            self.canonical()
        self.run.pop("taxonomies")
        self.location["taxa"] = [self.taxon, self.taxon]
        with self.assertRaises(gate.Invalid):
            self.canonical()
        self.location["taxa"] = [self.taxon] * 1001
        with self.assertRaises(gate.Invalid):
            self.canonical()
