# ruff: noqa: E402
"""Synthetic strict Bandit contracts, immutable source and shared-manifest tests."""

from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

S = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(S))
import security_bandit as gate
import security_sarif as codeql
from security_fixture_support import document as sarif_document
from security_manifest import EMPTY, MANIFEST_PATH, SharedGitTree, codeql_namespace
from security_source import GitTree


class MemoryTree:
    context_digest = SharedGitTree.context_digest
    bind_region = GitTree.bind_region

    def __init__(self):
        self.root_uri = "file:///fixture/"
        self.blobs = {}
        self.entries = {}
        self.put("src/sink.py", b"def sink(value):\n    print(value)\n")
        self.put("src/helper.py", b"value = 1\n")
        self.put("README.md", b"fixture\n")
        self.put(
            gate.LOCK,
            (
                "bandit==1.9.4 \\\n    --hash=sha256:"
                + "a" * 64
                + "\npackaging==26.3 \\\n    --hash=sha256:"
                + "b" * 64
                + "\n"
            ).encode(),
        )
        self.put(gate.INPUT, b"bandit==1.9.4\n")
        self.put(MANIFEST_PATH, json.dumps(EMPTY).encode())

    def put(self, path, data):
        self.blobs[path] = data
        self.entries[path] = {"mode": "100644", "sha256": gate.sha(data)}


def identity(tree):
    return {
        "schema": 1,
        "bandit_version": gate.VERSION,
        "python": "3.12.1",
        "lock_sha256": gate.sha(tree.blobs[gate.LOCK]),
        "input_sha256": gate.sha(tree.blobs[gate.INPUT]),
        "implementation_sha256": "b" * 64,
        "profile_sha256": gate.digest(gate.PROFILE),
        "distributions": [
            {"name": "bandit", "version": gate.VERSION, "files_sha256": "c" * 64},
            {"name": "packaging", "version": "26.3", "files_sha256": "d" * 64},
        ],
    }


def finding(path="src/sink.py", severity="HIGH", line=2):
    return {
        "filename": "./" + path,
        "code": "PRIVATE_DIAGNOSTIC_MARKER\n",
        "col_offset": 4,
        "end_col_offset": 9,
        "issue_confidence": "HIGH",
        "issue_cwe": {"id": 20, "link": "https://cwe.mitre.org/data/definitions/20.html"},
        "issue_severity": severity,
        "issue_text": "PRIVATE_MESSAGE_MARKER",
        "line_number": line,
        "line_range": [line],
        "more_info": "https://example.invalid/rule",
        "test_id": "B102",
        "test_name": "exec_used",
    }


def report(tree, findings=None):
    findings = [finding()] if findings is None else findings
    metrics = {
        "./" + path: {
            key: (gate.loc(tree.blobs[path]) if key == "loc" else 0) for key in gate.METRICS
        }
        for path in gate.inventory(tree)
    }
    for row in findings:
        path = "./" + gate.normalized_path(row["filename"])
        metrics[path]["SEVERITY." + row["issue_severity"]] += 1
        metrics[path]["CONFIDENCE." + row["issue_confidence"]] += 1
    metrics["_totals"] = {
        key: sum(value[key] for value in metrics.values()) for key in gate.METRICS
    }
    return {
        "errors": [],
        "generated_at": "2026-01-01T00:00:00Z",
        "metrics": metrics,
        "results": findings,
    }


def entry(tree, doc, tool):
    p = gate.review(doc, tree, tool, int(bool(doc["results"])))["candidates"][0]["proof"]
    return {
        "id": "synthetic-one-site",
        "rationale": "Synthetic fixture only, never an actual approval",
        "disposition": "false-positive",
        "reviewed_revision": "a" * 40,
        "max_occurrences": 1,
        "proof": p,
    }


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tree = MemoryTree()
        self.tool = identity(self.tree)
        self.doc = report(self.tree)

    def parse(self, code=None):
        return gate.parse_report(
            self.doc, self.tree, int(bool(self.doc["results"])) if code is None else code
        )

    def bad(self):
        with self.assertRaises((codeql.Invalid, KeyError, TypeError, ValueError)):
            self.parse()

    def test_internal_scanner_error_is_not_clean(self):
        from check_bandit import reject_scanner_errors

        with self.assertRaises(codeql.Invalid):
            with reject_scanner_errors():
                logging.getLogger("bandit.fixture").error("PRIVATE_SCANNER_EVENT")

    def test_scanner_warning_is_not_formatted(self):
        from check_bandit import reject_scanner_errors

        with reject_scanner_errors():
            logging.getLogger("bandit.fixture").warning("PRIVATE_WARNING_EVENT")

    def test_full_dynamic_inventory(self):
        _, c = self.parse()
        self.assertEqual((c["tracked_python_files"], c["covered_files"], c["loc"]), (2, 2, 3))

    def test_empty_file_is_covered(self):
        self.tree.put("empty.py", b"")
        self.doc = report(self.tree)
        self.assertEqual(self.parse()[1]["covered_files"], 3)

    def test_normalize_dot_prefix(self):
        before = gate.review(self.doc, self.tree, self.tool, 1)
        self.doc["results"][0]["filename"] = "src/sink.py"
        self.doc["metrics"]["src/sink.py"] = self.doc["metrics"].pop("./src/sink.py")
        self.assertEqual(before, gate.review(self.doc, self.tree, self.tool, 1))

    def test_duplicate_normalized_path(self):
        self.doc["metrics"]["src/sink.py"] = self.doc["metrics"]["./src/sink.py"]
        self.bad()

    def test_missing_file(self):
        del self.doc["metrics"]["./src/helper.py"]
        self.bad()

    def test_extra_file(self):
        self.doc["metrics"]["./extra.py"] = self.doc["metrics"]["./src/helper.py"]
        self.bad()

    def test_new_tracked_file_requires_coverage(self):
        self.tree.put("added.py", b"value=2\n")
        self.bad()

    def test_nonpython_finding(self):
        self.doc["results"][0]["filename"] = "README.md"
        self.bad()

    def test_absolute_path(self):
        self.doc["results"][0]["filename"] = "/fixture/src/sink.py"
        self.bad()

    def test_traversal_path(self):
        self.doc["results"][0]["filename"] = "./../src/sink.py"
        self.bad()

    def test_backslash_path(self):
        self.doc["results"][0]["filename"] = "src\\sink.py"
        self.bad()

    def test_double_prefix(self):
        self.doc["results"][0]["filename"] = "././src/sink.py"
        self.bad()

    def test_errors_even_with_zero_results(self):
        self.doc = report(self.tree, [])
        self.doc["errors"] = [{"reason": "private"}]
        self.bad()

    def test_missing_root_field(self):
        del self.doc["errors"]
        self.bad()

    def test_unknown_root_field(self):
        self.doc["new_schema"] = True
        self.bad()

    def test_unknown_result_field(self):
        self.doc["results"][0]["candidates"] = []
        self.bad()

    def test_empty_document(self):
        self.doc = {}
        self.bad()

    def test_zero_loc(self):
        for values in self.doc["metrics"].values():
            values["loc"] = 0
        self.bad()

    def test_forged_loc(self):
        self.doc["metrics"]["./src/sink.py"]["loc"] += 1
        self.doc["metrics"]["_totals"]["loc"] += 1
        self.bad()

    def test_boolean_count(self):
        self.doc["metrics"]["./src/sink.py"]["loc"] = True
        self.bad()

    def test_negative_count(self):
        self.doc["metrics"]["_totals"]["loc"] = -1
        self.bad()

    def test_metric_unknown_field(self):
        self.doc["metrics"]["_totals"]["future"] = 1
        self.bad()

    def test_total_sum(self):
        self.doc["metrics"]["_totals"]["SEVERITY.HIGH"] = 2
        self.bad()

    def test_filtered_result_omission(self):
        self.doc["results"] = []
        self.bad()

    def test_low_filter_omission(self):
        self.doc = report(self.tree, [finding(severity="LOW")])
        self.doc["results"] = []
        self.bad()

    def test_confidence_filter_omission(self):
        self.doc["results"][0]["issue_confidence"] = "LOW"
        self.bad()

    def test_skipped_tests(self):
        self.doc["metrics"]["./src/sink.py"]["skipped_tests"] = 1
        self.doc["metrics"]["_totals"]["skipped_tests"] = 1
        self.bad()

    def test_nosec(self):
        self.doc["metrics"]["./src/sink.py"]["nosec"] = 1
        self.doc["metrics"]["_totals"]["nosec"] = 1
        self.bad()

    def test_unknown_severity(self):
        self.doc["results"][0]["issue_severity"] = "UNKNOWN"
        self.bad()

    def test_undefined_severity(self):
        self.doc["results"][0]["issue_severity"] = "UNDEFINED"
        self.bad()

    def test_undefined_confidence(self):
        self.doc["results"][0]["issue_confidence"] = "UNDEFINED"
        self.bad()

    def test_rule_shape(self):
        self.doc["results"][0]["test_id"] = "B.*"
        self.bad()

    def test_boolean_line(self):
        self.doc["results"][0]["line_number"] = True
        self.bad()

    def test_line_out_of_bounds(self):
        self.doc["results"][0]["line_range"] = [99]
        self.doc["results"][0]["line_number"] = 99
        self.bad()

    def test_duplicate_line(self):
        self.doc["results"][0]["line_range"] = [2, 2]
        self.bad()

    def test_empty_line_range(self):
        self.doc["results"][0]["line_range"] = []
        self.bad()

    def test_offset_out_of_bounds(self):
        self.doc["results"][0]["end_col_offset"] = 999
        self.bad()

    def test_bad_cwe(self):
        self.doc["results"][0]["issue_cwe"]["link"] = "https://example.invalid"
        self.bad()

    def test_exit_zero_with_findings(self):
        with self.assertRaises(codeql.Invalid):
            self.parse(0)

    def test_exit_one_empty(self):
        self.doc = report(self.tree, [])
        with self.assertRaises(codeql.Invalid):
            self.parse(1)

    def test_exit_two(self):
        with self.assertRaises(codeql.Invalid):
            self.parse(2)

    def test_exit_boolean(self):
        with self.assertRaises(codeql.Invalid):
            self.parse(True)

    def test_empty_success_still_has_coverage(self):
        self.doc = report(self.tree, [])
        self.assertEqual(self.parse()[0], [])

    def test_low_visible_not_blocking(self):
        self.doc = report(self.tree, [finding(severity="LOW")])
        value = gate.evaluate(self.doc, self.tree, self.tool, copy.deepcopy(EMPTY), 1)
        self.assertEqual(
            (value["blocking"], value["raw_results"], value["coverage"]["counts"]["LOW"]), (0, 1, 1)
        )

    def test_duplicate_json_key(self):
        with self.assertRaises(codeql.Invalid):
            codeql.load_json(b'{"errors":[],"errors":[]}')

    def test_nonfinite_json(self):
        for value in [b"NaN", b"Infinity", b"1e999"]:
            with self.assertRaises(codeql.Invalid):
                codeql.load_json(b'{"x":' + value + b"}")

    def test_review_does_not_emit_prose(self):
        text = json.dumps(gate.review(self.doc, self.tree, self.tool, 1))
        self.assertNotIn("PRIVATE_DIAGNOSTIC_MARKER", text)
        self.assertNotIn("PRIVATE_MESSAGE_MARKER", text)


class AllowanceTests(unittest.TestCase):
    def setUp(self):
        self.tree = MemoryTree()
        self.tool = identity(self.tree)
        self.doc = report(self.tree)
        self.manifest = copy.deepcopy(EMPTY)
        self.manifest["bandit"] = [entry(self.tree, self.doc, self.tool)]

    def check(self):
        return gate.evaluate(
            self.doc, self.tree, self.tool, self.manifest, int(bool(self.doc["results"]))
        )

    def refused(self):
        with self.assertRaises((codeql.Invalid, ValueError, KeyError, TypeError)):
            self.check()

    def test_exact_once(self):
        self.assertEqual((self.check()["allowed"], self.check()["blocking"]), (1, 0))

    def test_no_approval(self):
        self.manifest["bandit"] = []
        self.assertEqual(self.check()["blocking"], 1)

    def test_same_site_duplicate(self):
        self.doc = report(self.tree, [finding(), finding()])
        self.assertEqual((self.check()["allowed"], self.check()["blocking"]), (1, 1))

    def test_same_rule_new_site(self):
        other = finding("src/helper.py", line=1)
        other["col_offset"] = 0
        other["end_col_offset"] = 5
        self.doc = report(self.tree, [finding(), other])
        self.assertEqual(self.check()["blocking"], 1)

    def test_stale_unused(self):
        self.doc = report(self.tree, [])
        self.refused()

    def test_renamed_path(self):
        self.tree.put("renamed.py", self.tree.blobs["src/sink.py"])
        self.doc = report(self.tree)
        self.refused()

    def test_source_outside_span(self):
        self.tree.put("src/sink.py", self.tree.blobs["src/sink.py"] + b"outside=1\n")
        self.doc = report(self.tree)
        self.refused()

    def test_helper_change(self):
        self.tree.put("src/helper.py", b"value=2\n")
        self.doc = report(self.tree)
        self.refused()

    def test_docs_change(self):
        self.tree.put("README.md", b"changed\n")
        self.refused()

    def test_mode_change(self):
        self.tree.entries["src/sink.py"]["mode"] = "100755"
        self.refused()

    def test_tool_changes(self):
        self.tool["distributions"][0]["files_sha256"] = "e" * 64
        self.refused()

    def test_interpreter_changes(self):
        self.tool["python"] = "3.12.2"
        self.refused()

    def test_runner_changes(self):
        self.tool["implementation_sha256"] = "e" * 64
        self.refused()

    def test_lock_changes(self):
        self.tree.put(gate.LOCK, self.tree.blobs[gate.LOCK] + b"# revised\n")
        self.refused()

    def test_pinned_input_changes(self):
        self.tree.put(gate.INPUT, b"bandit==1.9.3\n")
        self.refused()

    def test_wrong_version(self):
        self.tool["bandit_version"] = "1.9.3"
        self.refused()

    def test_wrong_package_version(self):
        self.tool["distributions"][0]["version"] = "1.9.3"
        self.refused()

    def test_duplicate_distribution(self):
        self.tool["distributions"].append(self.tool["distributions"][0])
        self.refused()

    def test_tool_unknown_field(self):
        self.tool["untrusted"] = True
        self.refused()

    def test_missing_tool_closure(self):
        self.tool["distributions"] = []
        self.refused()

    def test_message_change(self):
        self.doc["results"][0]["issue_text"] = "changed"
        self.refused()

    def test_snippet_change(self):
        self.doc["results"][0]["code"] = "changed"
        self.refused()

    def test_confidence_change(self):
        row = finding()
        row["issue_confidence"] = "LOW"
        self.doc = report(self.tree, [row])
        self.refused()

    def test_severity_change(self):
        self.doc = report(self.tree, [finding(severity="MEDIUM")])
        self.refused()

    def test_max_occurrences(self):
        self.manifest["bandit"][0]["max_occurrences"] = 2
        self.refused()

    def test_boolean_occurrences(self):
        self.manifest["bandit"][0]["max_occurrences"] = True
        self.refused()

    def test_duplicate_proof(self):
        other = copy.deepcopy(self.manifest["bandit"][0])
        other["id"] = "other"
        self.manifest["bandit"].append(other)
        self.refused()

    def test_duplicate_id(self):
        self.manifest["bandit"].append(copy.deepcopy(self.manifest["bandit"][0]))
        self.refused()

    def test_proof_unknown_field(self):
        self.manifest["bandit"][0]["proof"]["new"] = True
        self.refused()

    def test_stale_full_hash(self):
        self.manifest["bandit"][0]["proof"]["source"]["sha256"] = "f" * 64
        self.refused()

    def test_stale_span_hash(self):
        self.manifest["bandit"][0]["proof"]["source"]["line_sha256"] = "f" * 64
        self.refused()

    def test_no_cross_manifest_cycle(self):
        before = self.tree.context_digest()
        self.tree.put(MANIFEST_PATH, json.dumps(self.manifest).encode())
        self.assertEqual(before, self.tree.context_digest())
        self.assertEqual(self.check()["allowed"], 1)
        doc = sarif_document()
        p = codeql.proof(
            codeql.classify_document(doc)[0], self.tree, "python", self.tree.context_digest()
        )
        self.manifest["codeql"] = [
            {
                "id": "codeql-fixture",
                "rationale": "Synthetic review",
                "disposition": "false-positive",
                "reviewed_revision": "a" * 40,
                "max_occurrences": 1,
                "proof": p,
            }
        ]
        self.tree.put(MANIFEST_PATH, json.dumps(self.manifest).encode())
        self.assertEqual(before, self.tree.context_digest())
        self.assertEqual(
            codeql.evaluate([doc], self.tree, codeql_namespace(self.manifest), "python")["allowed"],
            1,
        )
        self.assertEqual(self.check()["allowed"], 1)

    def test_legacy_manifest_not_excluded(self):
        self.tree.put(codeql.MANIFEST_PATH, b"{}")
        self.refused()

    def test_other_manifest_not_excluded(self):
        self.tree.put(".github/bandit-allowances.json", b"{}")
        self.refused()

    def test_unknown_context_policy(self):
        self.manifest["context_policy"] = "skip-data"
        self.refused()

    def test_foreign_namespace_type(self):
        self.manifest["codeql"] = {}
        self.refused()

    def test_missing_namespace(self):
        del self.manifest["codeql"]
        self.refused()

    def test_review_survives_stale_policy(self):
        self.manifest["bandit"][0]["proof"]["source"]["sha256"] = "f" * 64
        self.assertEqual(gate.review(self.doc, self.tree, self.tool, 1)["active_allowances"], 0)
        self.refused()

    def test_lock_url_injection(self):
        self.tree.put(
            gate.LOCK, self.tree.blobs[gate.LOCK] + b"--extra-index-url https://example.invalid\n"
        )
        self.refused()

    def test_lock_missing_hash(self):
        self.tree.put(
            gate.LOCK,
            b"bandit==1.9.4 \\\npackaging==26.3 \\\n    --hash=sha256:" + b"a" * 64 + b"\n",
        )
        self.refused()


class LoadedQueryTests(unittest.TestCase):
    def setUp(self):
        self.rule = lambda: None
        self.rule._test_id = "B100"
        self.formatter = lambda: None
        self.manager = SimpleNamespace(
            plugins=[SimpleNamespace(name="rule", plugin=self.rule)],
            blacklists_mgr=[SimpleNamespace(name="blacklist")],
            formatters=[SimpleNamespace(name="json", plugin=self.formatter)],
        )
        self.expected = {
            "bandit.plugins": [SimpleNamespace(name="rule")],
            "bandit.blacklists": [SimpleNamespace(name="blacklist")],
        }

    def check(self):
        from check_bandit import validate_query_inventory

        with patch(
            "check_bandit.metadata.entry_points", side_effect=lambda group: self.expected[group]
        ):
            return validate_query_inventory(self.manager, self.formatter)

    def test_complete_loaded_inventory(self):
        self.assertEqual(self.check(), {"B100", "B001"})

    def test_failed_rule_load(self):
        self.manager.plugins = []
        with self.assertRaises(codeql.Invalid):
            self.check()

    def test_failed_blacklist_load(self):
        self.manager.blacklists_mgr = []
        with self.assertRaises(codeql.Invalid):
            self.check()

    def test_extra_loaded_rule(self):
        self.manager.plugins.append(SimpleNamespace(name="extra", plugin=self.rule))
        with self.assertRaises(codeql.Invalid):
            self.check()

    def test_duplicate_rule_identifier(self):
        self.manager.plugins.append(SimpleNamespace(name="other", plugin=self.rule))
        self.expected["bandit.plugins"].append(SimpleNamespace(name="other"))
        with self.assertRaises(codeql.Invalid):
            self.check()

    def test_selected_formatter_mismatch(self):
        self.manager.formatters[0].plugin = lambda: None
        with self.assertRaises(codeql.Invalid):
            self.check()


class GitSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "source.py").write_text("value=1\n")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.tree = SharedGitTree(self.root)
        self.receipt = self.tree.receipt()

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def test_snapshot_roundtrip(self):
        self.tree.verify_receipt(self.receipt)

    def test_tracked_source_mutation(self):
        (self.root / "source.py").write_text("value=2\n")
        with self.assertRaises(codeql.Invalid):
            self.tree.verify_receipt(self.receipt)

    def test_untracked_source(self):
        (self.root / "extra.py").write_text("value=2\n")
        with self.assertRaises(codeql.Invalid):
            self.tree.verify_receipt(self.receipt)

    def test_ignored_source(self):
        (self.root / ".git/info/exclude").write_text("extra.py\n")
        (self.root / "extra.py").write_text("value=2\n")
        with self.assertRaises(codeql.Invalid):
            self.tree.verify_receipt(self.receipt)

    def test_source_symlink(self):
        (self.root / "source.py").unlink()
        (self.root / "source.py").symlink_to("missing")
        with self.assertRaises((codeql.Invalid, OSError)):
            self.tree.verify_receipt(self.receipt)

    def test_source_hardlink(self):
        os.link(self.root / "source.py", Path(self.tmp.name) / "link")
        with self.assertRaises(codeql.Invalid):
            self.tree.verify_receipt(self.receipt)

    def test_source_head_changes(self):
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "next")
        with self.assertRaises(codeql.Invalid):
            self.tree.verify_receipt(self.receipt)


class EntryPointCacheTests(unittest.TestCase):
    def check_bypass(self, inject_failure=False):
        from check_bandit import uncached_entrypoints

        stale = {"synthetic": "ambient cache must not be used"}

        def original(*args, **kwargs):
            self.fail("Ambient entry-point cache was accessed")

        cache = SimpleNamespace(get_group_all=original)
        extension = SimpleNamespace(ExtensionManager=SimpleNamespace(ENTRY_POINT_CACHE=stale))
        package = SimpleNamespace(_cache=cache, extension=extension)
        with patch.dict(sys.modules, {"stevedore": package}):
            with patch("check_bandit.metadata.entry_points", return_value=["fixture-entry"]):
                try:
                    with uncached_entrypoints():
                        self.assertIsNot(extension.ExtensionManager.ENTRY_POINT_CACHE, stale)
                        self.assertEqual(cache.get_group_all("bandit.plugins"), ["fixture-entry"])
                        with self.assertRaises(codeql.Invalid):
                            cache.get_group_all("bandit.plugins", path=["unbound"])
                        if inject_failure:
                            raise RuntimeError("synthetic")
                except RuntimeError:
                    if not inject_failure:
                        raise
                self.assertIs(cache.get_group_all, original)
                self.assertIs(extension.ExtensionManager.ENTRY_POINT_CACHE, stale)

    def test_direct_metadata_bypasses_ambient_disk_cache(self):
        self.check_bypass()

    def test_cache_bindings_restored_after_exception(self):
        self.check_bypass(True)
