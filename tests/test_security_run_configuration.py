# ruff: noqa: E402
"""Persistent review identity must survive only ephemeral job UUID changes."""

import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import security_sarif as gate
from security_fixture_support import document
from security_source import GitTree

U1 = "00000000-0000-4000-8000-000000000001"
U2 = "00000000-0000-4000-9000-000000000002"


class Tree:
    root_uri = "file:///fixture/"
    bind_region = GitTree.bind_region
    context_digest = GitTree.context_digest

    def __init__(self):
        self.blobs = {
            "src/sink.py": b"def sink(value):\n    print(value)\n",
            "src/helper.py": b"value = 1\n",
        }
        self.entries = {
            p: {"mode": "100644", "sha256": hashlib.sha256(v).hexdigest()}
            for p, v in self.blobs.items()
        }


def proof(module, doc):
    tree = Tree()
    return module.proof(module.classify_document(doc)[0], tree, "python", tree.context_digest())


def report(uuid=U1):
    doc = document()
    doc["runs"][0]["properties"]["jobRunUuid"] = uuid
    return doc


class CanonicalRunConfigurationTests(unittest.TestCase):
    def test_two_valid_job_uuids_produce_same_entire_proof(self):
        self.assertEqual(proof(gate, report(U1)), proof(gate, report(U2)))

    def test_valid_uuid_and_absence_produce_same_semantic_proof(self):
        self.assertEqual(proof(gate, report()), proof(gate, document()))

    def synthetic_manifest(self):
        return {
            "schema": 1,
            "context_policy": "whole-tree-v1",
            "entries": [
                {
                    "id": "fixture-only",
                    "disposition": "false-positive",
                    "rationale": "Synthetic regression only",
                    "reviewed_revision": "a" * 40,
                    "max_occurrences": 1,
                    "proof": proof(gate, report(U1)),
                }
            ],
        }

    def test_synthetic_review_reuses_exact_proof_across_uuids(self):
        result = gate.evaluate([report(U2)], Tree(), self.synthetic_manifest(), "python")
        self.assertEqual((result["allowed"], result["blocking"]), (1, 0))

    def test_synthetic_review_stales_on_config_change(self):
        changed = report(U2)
        changed["runs"][0]["properties"]["codeqlConfigSummary"]["paths"] = ["src"]
        with self.assertRaises(gate.Invalid):
            gate.evaluate([changed], Tree(), self.synthetic_manifest(), "python")

    def test_original_run_properties_are_not_mutated(self):
        doc = report()
        before = copy.deepcopy(doc)
        proof(gate, doc)
        self.assertEqual(doc, before)

    def test_suite_change_stales_proof(self):
        doc = report()
        doc["runs"][0]["properties"]["codeqlConfigSummary"]["queries"][0]["uses"] = (
            "security-and-quality"
        )
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_filter_change_stales_proof(self):
        doc = report()
        doc["runs"][0]["properties"]["codeqlConfigSummary"]["query-filters"] = [
            {"exclude": {"id": "py/fixture"}}
        ]
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_incremental_mode_is_preserved_in_hash(self):
        doc = report()
        doc["runs"][0]["properties"]["incrementalMode"] = "diff-informed"
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_unknown_real_property_is_not_silently_dropped(self):
        doc = report()
        doc["runs"][0]["properties"]["newConfiguration"] = "changed"
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_nested_job_uuid_is_not_stripped(self):
        doc = report()
        doc["runs"][0]["properties"]["nested"] = {"jobRunUuid": U1}
        other = copy.deepcopy(doc)
        other["runs"][0]["properties"]["nested"]["jobRunUuid"] = U2
        self.assertNotEqual(proof(gate, doc), proof(gate, other))

    def test_format_property_is_not_stripped(self):
        doc = report()
        doc["runs"][0]["properties"]["semmle.formatSpecifier"] = "sarif-latest"
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_source_language_property_is_not_stripped(self):
        doc = report()
        doc["runs"][0]["properties"]["semmle.sourceLanguage"] = "python"
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_rule_descriptor_change_stales_proof(self):
        doc = report()
        doc["runs"][0]["tool"]["driver"]["rules"][0]["shortDescription"] = {"text": "changed"}
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_message_change_stales_proof(self):
        doc = report()
        doc["runs"][0]["results"][0]["message"]["text"] = "changed"
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_flow_change_stales_proof(self):
        doc = report()
        doc["runs"][0]["results"][0]["codeFlows"][0]["message"] = {"text": "changed"}
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_tool_version_change_stales_proof(self):
        doc = report()
        doc["runs"][0]["tool"]["driver"]["semanticVersion"] = "2.27.3"
        self.assertNotEqual(proof(gate, report()), proof(gate, doc))

    def test_null_bag_refused(self):
        with self.assertRaises(gate.Invalid):
            gate.canonical_run_configuration(None)

    def test_malformed_uuid_values_refused_by_real_proof(self):
        bad = [
            None,
            True,
            1,
            {},
            [],
            "",
            U1.upper().replace("00000001", "0000000A"),
            U1.replace("-4000-", "-1000-"),
            U1.replace("-8000-", "-0000-"),
            "urn:uuid:" + U1,
            "{" + U1 + "}",
            U1 + " ",
            U1 + "x",
        ]
        for value in bad:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(gate.Unallowable):
                    proof(gate, report(value))
