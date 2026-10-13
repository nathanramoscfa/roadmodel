# ruff: noqa: E402
"""Native CLI/source-boundary fixtures only; no analyzer, network or real repo writes."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Integration layout: repository scripts/ and tests/; no scratch or cwd dependency.
S = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(S))
import security_sarif as gate
from security_fixture_support import MemoryTree, approval, document
from security_manifest import EMPTY, MANIFEST_PATH
from security_manifest import SharedGitTree as GitTree
from security_source import bounded_command


def shared_approval(tree, doc):
    old = approval(tree, doc)
    return {
        "schema": 1,
        "context_policy": old["context_policy"],
        "codeql": old["entries"],
        "bandit": [],
    }


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codeql-cli-fixture-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.output = self.root / "sarif"
        self.output.mkdir()
        self.receipt = self.root / "snapshot.json"
        self.review_output = self.root / "review.json"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Fixture",
            GIT_COMMITTER_NAME="Fixture",
            GIT_AUTHOR_EMAIL="fixture" + "@example.invalid",
            GIT_COMMITTER_EMAIL="fixture" + "@example.invalid",
            CODEQL_ACTION_DIFF_INFORMED_QUERIES="false",
            CODEQL_OVERLAY_DATABASE_MODE="none",
            CODEQL_ANALYZE_OUTCOME="success",
        )
        self.git("init", "--quiet")
        for path, raw in MemoryTree().blobs.items():
            if path == gate.MANIFEST_PATH:
                continue
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.commit()
        self.env.update(
            GITHUB_EVENT_NAME="push",
            GITHUB_REF="refs/heads/main",
            GITHUB_SHA=self.git("rev-parse", "HEAD").decode().strip(),
            GITHUB_RUN_ID="123",
            GITHUB_RUN_ATTEMPT="1",
            CODEQL_PR_HEAD_SHA="",
            CODEQL_PR_BASE_SHA="",
        )
        self.doc = document()
        self.doc["runs"][0]["results"] = []
        self.write_doc()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        r = subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(self.repo), *args],
            env=self.env,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(r.returncode, 0, "Synthetic Git setup refused")
        return r.stdout

    def commit(self):
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        self.env["GITHUB_SHA"] = self.git("rev-parse", "HEAD").decode().strip()

    def write_doc(self):
        (self.output / "python.sarif").write_text(json.dumps(self.doc))

    def invoke(self, command, expect=0):
        args = [
            sys.executable,
            "-B",
            "-I",
            str(S / "check_codeql_sarif.py"),
            command,
            "--repo",
            str(self.repo),
        ]
        if command == "snapshot":
            args += ["--output", str(self.receipt)]
        else:
            args += [
                "--snapshot",
                str(self.receipt),
                "--directory",
                str(self.output),
                "--language",
                "python",
            ]
        if command == "review":
            args += ["--output", str(self.review_output)]
        r = subprocess.run(args, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(r.returncode, expect, "CLI outcome differed from fixture expectation")
        self.assertEqual(r.stderr, b"", "CLI disclosed unexpected error details")
        self.assertNotIn(str(self.root).encode(), r.stdout, "CLI disclosed fixture paths")
        return r.stdout

    def test_review_writes_unapproved_proof_for_raw_blocker(self):
        self.doc = document()
        self.write_doc()
        self.invoke("snapshot")
        self.invoke("review")
        data = json.loads(self.review_output.read_bytes())
        self.assertEqual(
            (data["purpose"], data["active_allowances"], data["raw_blocking"]),
            ("review-only", 0, 1),
        )
        self.assertEqual(len(data["candidates"]), 1)
        self.assertEqual(self.review_output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b"fixture message", self.review_output.read_bytes())
        self.invoke("check", 1)

    def test_review_preserves_ordered_typed_graph_without_flow_values(self):
        self.doc = document()
        self.write_doc()
        self.invoke("snapshot")
        self.invoke("review")
        candidate = json.loads(self.review_output.read_bytes())["candidates"][0]
        graph = candidate["typed_graph"]
        nodes = graph["flows"][0]["threads"][0]["nodes"]
        self.assertEqual([x["location"]["path"] for x in nodes], ["src/helper.py", "src/sink.py"])
        self.assertEqual(graph["primary"][0]["region"]["startLine"], 2)
        self.assertTrue(all(len(x["node_sha256"]) == 64 for x in nodes))

    def test_review_zero_results_still_writes_valid_metadata(self):
        self.invoke("snapshot")
        self.invoke("review")
        data = json.loads(self.review_output.read_bytes())
        self.assertEqual(data["candidates"], [])

    def test_review_message_snippet_flow_state_not_persisted(self):
        self.doc = document()
        result = self.doc["runs"][0]["results"][0]
        result["message"]["text"] = "SYNTHETIC_PRIVATE_MESSAGE"
        result["locations"][0]["physicalLocation"]["region"]["snippet"] = {
            "text": "SYNTHETIC_PRIVATE_SNIPPET"
        }
        result["codeFlows"][0]["threadFlows"][0]["locations"][0]["state"] = {
            "key": {"text": "SYNTHETIC_PRIVATE_STATE"}
        }
        self.write_doc()
        self.invoke("snapshot")
        self.invoke("review")
        raw = self.review_output.read_bytes()
        for forbidden in [
            b"SYNTHETIC_PRIVATE_",
            b'"snippet":',
            b'"message":',
            b"threadFlows",
            str(self.repo).encode(),
        ]:
            self.assertNotIn(forbidden, raw)

    def test_review_malformed_scan_writes_nothing(self):
        self.invoke("snapshot")
        (self.output / "python.sarif").write_bytes(b"{}")
        self.invoke("review", 1)
        self.assertFalse(self.review_output.exists())

    def test_review_contradictory_artifact_reference_writes_nothing(self):
        self.doc = document()
        self.doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"][
            "index"
        ] = 1
        self.write_doc()
        self.invoke("snapshot")
        self.invoke("review", 1)
        self.assertFalse(self.review_output.exists())

    def test_review_source_change_writes_nothing(self):
        self.invoke("snapshot")
        (self.repo / "src/helper.py").write_text("changed\n")
        self.invoke("review", 1)
        self.assertFalse(self.review_output.exists())

    def test_review_wrong_run_sha_refuses(self):
        self.env["GITHUB_SHA"] = "a" * 40
        self.invoke("snapshot")
        self.invoke("review", 1)
        self.assertFalse(self.review_output.exists())

    def test_review_missing_run_identifier_refuses(self):
        self.env.pop("GITHUB_RUN_ID")
        self.invoke("snapshot")
        self.invoke("review", 1)

    def test_review_malformed_run_identifier_refuses(self):
        self.env["GITHUB_RUN_ID"] = "SYNTHETIC_PRIVATE_RUN"
        self.invoke("snapshot")
        self.invoke("review", 1)

    def test_review_symlink_output_refuses_without_changing_target(self):
        target = self.root / "sentinel"
        target.write_bytes(b"synthetic sentinel")
        self.review_output.symlink_to(target)
        self.invoke("snapshot")
        self.invoke("review", 1)
        self.assertEqual(target.read_bytes(), b"synthetic sentinel")

    def test_review_existing_output_refuses(self):
        self.review_output.write_bytes(b"synthetic sentinel")
        self.invoke("snapshot")
        self.invoke("review", 1)
        self.assertEqual(self.review_output.read_bytes(), b"synthetic sentinel")

    def test_review_does_not_need_matching_active_allowance(self):
        self.doc = document()
        self.write_doc()
        manifest = shared_approval(GitTree(self.repo), self.doc)
        manifest["codeql"][0]["proof"]["finding_sha256"] = "0" * 64
        path = self.repo / MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(manifest))
        self.commit()
        self.env["GITHUB_SHA"] = self.git("rev-parse", "HEAD").decode().strip()
        self.invoke("snapshot")
        self.invoke("review")
        self.invoke("check", 1)

    def test_review_merge_commit_checks_both_parent_hashes(self):
        self.git("checkout", "--quiet", "-b", "fixture-feature")
        (self.repo / "feature.txt").write_text("feature\n")
        self.commit()
        head = self.git("rev-parse", "HEAD").decode().strip()
        self.git("checkout", "--quiet", "-b", "fixture-base", "HEAD~1")
        (self.repo / "base.txt").write_text("base\n")
        self.commit()
        base = self.git("rev-parse", "HEAD").decode().strip()
        self.git(
            "-c",
            "commit.gpgsign=false",
            "merge",
            "--quiet",
            "--no-ff",
            "fixture-feature",
            "-m",
            "fixture merge",
        )
        self.env.update(
            GITHUB_EVENT_NAME="pull_request",
            GITHUB_REF="refs/pull/1/merge",
            GITHUB_SHA=self.git("rev-parse", "HEAD").decode().strip(),
            CODEQL_PR_HEAD_SHA=head,
            CODEQL_PR_BASE_SHA=base,
        )
        self.invoke("snapshot")
        self.invoke("review")
        data = json.loads(self.review_output.read_bytes())
        self.assertEqual(data["execution"]["reviewed_head"], head)
        self.assertNotEqual(data["execution"]["analyzed_commit"], head)
        self.review_output.unlink()
        self.env["CODEQL_PR_HEAD_SHA"] = base
        self.invoke("review", 1)

    def test_clean_snapshot_and_zero_findings(self):
        self.invoke("snapshot")
        data = json.loads(self.invoke("check"))
        self.assertEqual(data["raw_blocking"], 0)

    def test_missing_diff_disable_refuses(self):
        self.invoke("snapshot")
        self.env.pop("CODEQL_ACTION_DIFF_INFORMED_QUERIES")
        self.invoke("check", 1)

    def test_snapshot_without_full_query_policy_refuses(self):
        self.env.pop("CODEQL_ACTION_DIFF_INFORMED_QUERIES")
        self.invoke("snapshot", 1)

    def test_raw_action_job_metadata_keeps_exact_suite(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["properties"].update(jobRunUuid="00000000-0000-4000-8000-000000000001")
        self.doc["runs"][0]["properties"]["semmle.formatSpecifier"] = "sarif-latest"
        self.doc["runs"][0]["properties"]["semmle.sourceLanguage"] = "python"
        self.write_doc()
        self.assertEqual(json.loads(self.invoke("check"))["raw_blocking"], 0)

    def test_raw_property_refusal_diagnostic_omits_values(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["properties"]["PRIVATE_PROPERTY_CANARY"] = "PRIVATE_VALUE_CANARY"
        self.write_doc()
        output = self.invoke("check", 1)
        self.assertNotIn(b"PRIVATE_", output)
        shape = json.loads(output.splitlines()[-1])["property_shape"]
        self.assertEqual(shape["runs"][0]["property_count"], 2)
        self.assertEqual(len(shape["runs"][0]["unknown_key_sha256"]), 1)

    def test_missing_config_summary_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0].pop("properties")
        self.write_doc()
        self.invoke("check", 1)

    def test_extra_query_filter_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["properties"]["codeqlConfigSummary"]["query-filters"] = [
            {"exclude": {"id": "py/fixture"}}
        ]
        self.write_doc()
        self.invoke("check", 1)

    def test_changed_suite_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["properties"]["codeqlConfigSummary"]["queries"][0]["uses"] = "default"
        self.write_doc()
        self.invoke("check", 1)

    def test_missing_analyzer_version_refuses_zero_results(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["tool"]["driver"].pop("semanticVersion")
        self.write_doc()
        self.invoke("check", 1)

    def test_wrong_pack_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["tool"]["extensions"][0]["name"] = "codeql/javascript-queries"
        self.write_doc()
        self.invoke("check", 1)

    def test_missing_pack_refuses_even_empty(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["tool"]["extensions"] = []
        self.write_doc()
        self.invoke("check", 1)

    def test_unsuccessful_zero_findings_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["invocations"] = [{"executionSuccessful": False}]
        self.write_doc()
        self.invoke("check", 1)

    def test_error_notification_zero_findings_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["invocations"] = [
            {
                "executionSuccessful": True,
                "toolExecutionNotifications": [{"level": "error", "message": {"text": "fixture"}}],
            }
        ]
        self.write_doc()
        self.invoke("check", 1)

    def test_raw_blocker_cannot_disappear(self):
        self.invoke("snapshot")
        self.doc = document()
        self.write_doc()
        data = json.loads(self.invoke("check", 1))
        self.assertEqual((data["raw_blocking"], data["blocking"], data["allowed"]), (1, 1, 0))

    def test_stale_receipt_source_change_refuses(self):
        self.invoke("snapshot")
        (self.repo / "src/helper.py").write_bytes(b"changed = 1\n")
        self.invoke("check", 1)

    def test_ignored_source_refuses_snapshot(self):
        (self.repo / ".gitignore").write_text("ignored.py\n")
        self.commit()
        (self.repo / "ignored.py").write_text("pass\n")
        self.invoke("snapshot", 1)

    def test_symlink_sarif_refuses(self):
        self.invoke("snapshot")
        target = self.root / "elsewhere"
        (self.output / "python.sarif").rename(target)
        (self.output / "python.sarif").symlink_to(target)
        self.invoke("check", 1)

    def test_hardlink_sarif_refuses(self):
        self.invoke("snapshot")
        os.link(self.output / "python.sarif", self.root / "linked")
        self.invoke("check", 1)

    def test_empty_sarif_directory_refuses(self):
        self.invoke("snapshot")
        (self.output / "python.sarif").unlink()
        self.invoke("check", 1)

    def test_duplicate_json_key_refuses(self):
        self.invoke("snapshot")
        (self.output / "python.sarif").write_bytes(b'{"version":"2.1.0","runs":[],"runs":[]}')
        self.invoke("check", 1)

    def test_symlink_snapshot_refuses(self):
        self.invoke("snapshot")
        target = self.root / "elsewhere"
        self.receipt.rename(target)
        self.receipt.symlink_to(target)
        self.invoke("check", 1)

    def test_exact_synthetic_allowance_from_tracked_blob(self):
        self.doc = document()
        self.write_doc()
        manifest = shared_approval(GitTree(self.repo), self.doc)
        path = self.repo / MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(manifest))
        self.commit()
        self.invoke("snapshot")
        data = json.loads(self.invoke("check"))
        self.assertEqual((data["raw_blocking"], data["blocking"], data["allowed"]), (1, 0, 1))

    def test_synthetic_allowance_duplicate_across_runs_stays_blocking(self):
        self.doc = document()
        manifest = shared_approval(GitTree(self.repo), self.doc)
        path = self.repo / MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(manifest))
        self.commit()
        self.doc["runs"].append(copy.deepcopy(self.doc["runs"][0]))
        self.write_doc()
        self.invoke("snapshot")
        data = json.loads(self.invoke("check", 1))
        self.assertEqual((data["raw_blocking"], data["blocking"], data["allowed"]), (2, 1, 1))

    def test_snapshot_requires_overlay_none(self):
        for value in [None, "overlay", "overlay-base", "NONE", ""]:
            if value is None:
                self.env.pop("CODEQL_OVERLAY_DATABASE_MODE", None)
            else:
                self.env["CODEQL_OVERLAY_DATABASE_MODE"] = value
            self.invoke("snapshot", 1)
        self.assertFalse(self.receipt.exists())

    def test_snapshot_contains_preinit_analysis_profile(self):
        self.invoke("snapshot")
        value = json.loads(self.receipt.read_bytes())
        self.assertEqual(
            value["analysis_profile"],
            {
                "schema": 1,
                "suite": "security-extended",
                "diff_informed": False,
                "overlay_mode": "none",
            },
        )
        self.assertEqual(value["source"]["commit"], self.env["GITHUB_SHA"])

    def test_snapshot_rejects_tampered_profile(self):
        self.invoke("snapshot")
        value = json.loads(self.receipt.read_bytes())
        value["analysis_profile"]["diff_informed"] = True
        self.receipt.write_text(json.dumps(value))
        self.invoke("review", 1)
        self.invoke("check", 1)

    def test_snapshot_rejects_boolean_schema_and_integer_false(self):
        self.invoke("snapshot")
        original = json.loads(self.receipt.read_bytes())
        for key, changed in [("schema", True), ("diff_informed", 0)]:
            value = copy.deepcopy(original)
            value["analysis_profile"][key] = changed
            self.receipt.write_text(json.dumps(value))
            self.invoke("review", 1)
        self.assertFalse(self.review_output.exists())

    def test_snapshot_rejects_old_unbound_receipt(self):
        self.invoke("snapshot")
        value = json.loads(self.receipt.read_bytes())
        self.receipt.write_text(json.dumps(value["source"]))
        self.invoke("review", 1)

    def test_review_and_check_refuse_each_failed_analyze_outcome(self):
        self.invoke("snapshot")
        for outcome in [None, "failure", "cancelled", "skipped", "", "SUCCESS"]:
            if outcome is None:
                self.env.pop("CODEQL_ANALYZE_OUTCOME", None)
            else:
                self.env["CODEQL_ANALYZE_OUTCOME"] = outcome
            self.invoke("review", 1)
            self.invoke("check", 1)
            self.assertFalse(self.review_output.exists())

    def test_failed_analyze_with_blockers_does_not_emit_usable_proof(self):
        self.doc = document()
        self.write_doc()
        self.invoke("snapshot")
        self.env["CODEQL_ANALYZE_OUTCOME"] = "failure"
        self.invoke("review", 1)
        self.assertFalse(self.review_output.exists())

    def test_review_and_check_refuse_changed_overlay_policy(self):
        self.invoke("snapshot")
        self.env["CODEQL_OVERLAY_DATABASE_MODE"] = "overlay"
        self.invoke("review", 1)
        self.invoke("check", 1)

    def test_incremental_sarif_property_refuses(self):
        self.invoke("snapshot")
        self.doc["runs"][0]["properties"]["incrementalMode"] = "diff-informed"
        self.write_doc()
        self.invoke("review", 1)
        self.invoke("check", 1)

    def test_check_wrong_run_sha_refuses(self):
        self.invoke("snapshot")
        self.env["GITHUB_SHA"] = "a" * 40
        self.invoke("check", 1)

    def test_check_missing_run_identifier_refuses(self):
        self.invoke("snapshot")
        self.env.pop("GITHUB_RUN_ID")
        self.invoke("check", 1)

    def test_old_manifest_does_not_approve_blocker(self):
        self.doc = document()
        self.write_doc()
        old = approval(GitTree(self.repo), self.doc)
        path = self.repo / gate.MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(old))
        self.commit()
        self.invoke("snapshot")
        self.invoke("review")
        data = json.loads(self.invoke("check", 1))
        self.assertEqual(data["allowed"], 0)

    def test_closed_combined_manifest_rejects_extra_key(self):
        value = dict(EMPTY, entries=[])
        path = self.repo / MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value))
        self.commit()
        self.invoke("snapshot")
        self.invoke("review", 1)
        self.invoke("check", 1)

    def test_combined_manifest_rejects_wrong_namespace_shape(self):
        value = dict(EMPTY, bandit="bad")
        path = self.repo / MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value))
        self.commit()
        self.invoke("snapshot")
        self.invoke("review", 1)

    def test_stale_bandit_entry_does_not_block_codeql_proof_capture(self):
        value = dict(EMPTY, bandit=[{"incomplete": "owned by separate Bandit enforcement"}])
        path = self.repo / MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value))
        self.commit()
        self.invoke("snapshot")
        self.invoke("review")
        self.invoke("check")
        # The required Bandit gate rejects malformed/stale Bandit-owned entries.

    def test_no_bytecode_in_source_after_review_and_check(self):
        self.invoke("snapshot")
        self.invoke("review")
        self.invoke("check")
        self.assertEqual(list(self.repo.rglob("*.pyc")), [])


class BoundsTests(unittest.TestCase):
    def test_numeric_overflow_rejected(self):
        with self.assertRaises(gate.Invalid):
            gate.load_json(b'{"value":1e999}')

    def test_deep_json_rejected(self):
        with self.assertRaises(gate.Invalid):
            gate.load_json(b'{"v":' + b"[" * 66 + b"0" + b"]" * 66 + b"}")

    def test_long_string_rejected(self):
        with self.assertRaises(gate.Invalid):
            gate.load_json(json.dumps({"v": "x" * (1024 * 1024 + 1)}).encode())

    def test_capture_within_bound(self):
        self.assertEqual(
            bounded_command([sys.executable, "-I", "-c", "print('fixture')"], dict(os.environ), 32),
            b"fixture\n",
        )

    def test_capture_overflow_refuses(self):
        with self.assertRaises(gate.Invalid):
            bounded_command(
                [sys.executable, "-I", "-c", "import os; os.write(1,b'x'*1000000)"],
                dict(os.environ),
                32,
            )

    def test_capture_timeout_refuses(self):
        with self.assertRaises(gate.Invalid):
            bounded_command(
                [sys.executable, "-I", "-c", "import time; time.sleep(5)"],
                dict(os.environ),
                32,
                timeout=0.1,
            )

    def test_capture_nonzero_refuses(self):
        with self.assertRaises(gate.Invalid):
            bounded_command(
                [sys.executable, "-I", "-c", "raise SystemExit(3)"], dict(os.environ), 32
            )


def test_contract_diagnostics_contain_only_public_components_and_lines():
    from check_codeql_sarif import contract_failure_locations

    canary = "synthetic-private-diagnostic-canary"
    try:
        gate.require(False)
    except gate.Invalid as error:
        error.args = (canary,)
        locations = contract_failure_locations(error)
    assert locations
    assert all(set(item) == {"component", "line"} for item in locations)
    assert all(
        item["component"] == "security_sarif.py" and type(item["line"]) is int for item in locations
    )
    assert canary not in json.dumps(locations)
