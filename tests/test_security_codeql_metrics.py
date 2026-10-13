# ruff: noqa: E402
"""Bind every supported raw metric to its exact value and rule descriptor."""

import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_codeql_sarif as cli
import security_sarif as gate
from check_codeql_sarif import metric_shapes
from security_fixture_support import MemoryTree, metric_document

U1 = "00000000-0000-4000-8000-000000000001"
U2 = "00000000-0000-4000-9000-000000000002"


def config(doc):
    run = doc["runs"][0]
    return gate.canonical_run_configuration(run["properties"], run)


def proof(doc):
    tree = MemoryTree()
    return gate.proof(gate.classify_document(doc)[0], tree, "python", tree.context_digest())


class Metrics(unittest.TestCase):
    def test_official_fixture_shape_resolves_and_preserves_value(self):
        out = config(metric_document())
        row = out["metricResults"][0]
        self.assertEqual(row["value"], 123)
        self.assertEqual(row["descriptor"]["id"], "py/summary/lines-of-code")
        self.assertEqual(row["component"]["name"], "codeql/python-queries")
        self.assertEqual(row["reference"], {"toolComponent": {}})

    def test_raw_input_not_mutated(self):
        doc = metric_document()
        before = copy.deepcopy(doc)
        config(doc)
        self.assertEqual(doc, before)

    def test_valid_two_uuids_same_complete_proof_with_metrics(self):
        a = metric_document()
        b = copy.deepcopy(a)
        b["runs"][0]["properties"]["jobRunUuid"] = U2
        self.assertEqual(proof(a), proof(b))

    def test_metric_count_changes_configuration_proof(self):
        self.assertNotEqual(proof(metric_document(123)), proof(metric_document(124)))

    def test_metric_value_type_remains_bound(self):
        self.assertNotEqual(proof(metric_document(123)), proof(metric_document(123.0)))

    def test_metric_descriptor_change_is_bound(self):
        a = metric_document()
        b = copy.deepcopy(a)
        b["runs"][0]["tool"]["extensions"][0]["rules"][0]["name"] = "Changed"
        self.assertNotEqual(proof(a), proof(b))

    def test_metric_component_version_change_is_bound(self):
        a = metric_document()
        b = copy.deepcopy(a)
        b["runs"][0]["tool"]["extensions"][0]["semanticVersion"] = "9.9.9"
        self.assertNotEqual(proof(a), proof(b))

    def test_index_retarget_same_value_changes_configuration(self):
        a = metric_document()
        b = copy.deepcopy(a)
        b["runs"][0]["tool"]["extensions"][0]["rules"][0]["id"] = "py/summary/other"
        self.assertNotEqual(config(a), config(b))

    def test_adding_duplicate_metric_remains_bound(self):
        a = metric_document()
        b = copy.deepcopy(a)
        b["runs"][0]["properties"]["metricResults"] *= 2
        self.assertNotEqual(proof(a), proof(b))

    def test_empty_metrics_are_supported_and_bound(self):
        a = metric_document()
        a["runs"][0]["properties"]["metricResults"] = []
        self.assertEqual(config(a)["metricResults"], [])

    def test_missing_run_refused(self):
        with self.assertRaises(gate.Invalid):
            gate.canonical_run_configuration(metric_document()["runs"][0]["properties"])

    def test_bad_value_vectors_refused(self):
        for value in [True, False, None, "123", {}, [], math.nan, math.inf, -math.inf]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(gate.Invalid):
                    config(metric_document(value))

    def test_valid_numeric_vectors(self):
        for value in [0, -1, 1.5, 10**100]:
            self.assertEqual(config(metric_document(value))["metricResults"][0]["value"], value)

    def test_unknown_metric_key_refused(self):
        doc = metric_document()
        doc["runs"][0]["properties"]["metricResults"][0]["PRIVATE_KEY_CANARY"] = (
            "PRIVATE_VALUE_CANARY"
        )
        with self.assertRaises(gate.Invalid):
            config(doc)

    def test_location_metric_explicitly_unsupported(self):
        doc = metric_document()
        doc["runs"][0]["properties"]["metricResults"][0]["location"] = {
            "uri": "file:///PRIVATE_PATH_CANARY"
        }
        with self.assertRaises(gate.Invalid):
            config(doc)

    def test_bad_container_vectors_refused(self):
        for value in [None, {}, True, "123", [None], [123], [{}], [{"rule": {}}], [{"value": 1}]]:
            with self.subTest(value_type=type(value).__name__):
                doc = metric_document()
                doc["runs"][0]["properties"]["metricResults"] = value
                with self.assertRaises(gate.Invalid):
                    config(doc)

    def test_bad_reference_vectors_refused(self):
        vectors = [
            {},
            None,
            {"index": True},
            {"index": -1},
            {"index": 999},
            {"index": 0, "toolComponent": {"index": True}},
            {"index": 0, "toolComponent": {"index": 999}},
            {"index": 0, "toolComponent": {"index": 0}, "id": "py/wrong"},
            {"index": 0, "toolComponent": {"index": 0, "name": "wrong"}},
            {
                "index": 0,
                "toolComponent": {"index": 0},
                "PRIVATE_KEY_CANARY": "PRIVATE_VALUE_CANARY",
            },
        ]
        for reference in vectors:
            with self.subTest(reference_type=type(reference).__name__):
                doc = metric_document()
                doc["runs"][0]["properties"]["metricResults"][0]["rule"] = reference
                with self.assertRaises(gate.Invalid):
                    config(doc)

    def test_zero_findings_still_validate_metrics(self):
        doc = metric_document(True)
        doc["runs"][0]["results"] = []
        with self.assertRaises(gate.Invalid):
            cli.language_binding(doc, "python")

    def test_exact_summary_plus_metric_supported(self):
        cli.language_binding(metric_document(), "python")

    def test_diagnostic_never_emits_metric_value_or_unknown_keys(self):
        doc = metric_document("PRIVATE_VALUE_CANARY")
        doc["runs"][0]["properties"]["metricResults"][0]["PRIVATE_KEY_CANARY"] = (
            "PRIVATE_MESSAGE_CANARY"
        )
        output = json.dumps(cli.property_shape(doc))
        self.assertNotIn("PRIVATE_", output)


class Shapes(unittest.TestCase):
    def test_known_row(self):
        self.assertEqual(
            metric_shapes([{"rule": {}, "value": 1}]),
            {
                "type": "array",
                "count": 1,
                "items": [
                    {
                        "type": "object",
                        "known": [
                            {"key": "rule", "type": "object"},
                            {"key": "value", "type": "integer"},
                        ],
                        "unknown_key_sha256": [],
                    }
                ],
            },
        )

    def test_scalar_shapes(self):
        for value, label in [
            (None, "null"),
            (True, "boolean"),
            (1, "integer"),
            (1.5, "number"),
            ("PRIVATE_CANARY", "string"),
            ({}, "object"),
        ]:
            self.assertEqual(metric_shapes(value), {"type": label})

    def test_malformed_item(self):
        self.assertEqual(metric_shapes([None])["items"], [{"type": "null"}])

    def test_unknown_names_values_never_emitted(self):
        value = [
            {
                "rule": {"id": "PRIVATE_RULE_CANARY"},
                "value": "PRIVATE_VALUE_CANARY",
                "PRIVATE_KEY_CANARY": {"uri": "file:///PRIVATE_PATH_CANARY"},
            }
        ]
        result = metric_shapes(value)
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertEqual(
            result["items"][0]["unknown_key_sha256"],
            [hashlib.sha256(b"PRIVATE_KEY_CANARY").hexdigest()],
        )

    def test_rule_and_value_types(self):
        result = metric_shapes([{"rule": "PRIVATE_RULE_CANARY", "value": False}])
        self.assertEqual(
            result["items"][0]["known"],
            [{"key": "rule", "type": "string"}, {"key": "value", "type": "boolean"}],
        )

    def test_items_bound(self):
        result = metric_shapes([{"rule": {}, "value": 1}] * 100)
        self.assertEqual(result["count"], 100)
        self.assertEqual(len(result["items"]), 8)

    def test_unknown_keys_bound(self):
        self.assertEqual(
            len(
                metric_shapes([{str(i): None for i in range(100)}])["items"][0][
                    "unknown_key_sha256"
                ]
            ),
            16,
        )

    def test_surrogate_unknown_key(self):
        self.assertEqual(
            metric_shapes([{"\ud800": "PRIVATE_CANARY"}])["items"][0]["unknown_key_sha256"],
            [hashlib.sha256("\ud800".encode("utf-8", "surrogatepass")).hexdigest()],
        )

    def test_no_input_mutation(self):
        x = [{"rule": {"index": 0}, "value": 1}]
        raw = json.dumps(x)
        metric_shapes(x)
        self.assertEqual(json.dumps(x), raw)


RULE = "py/summary/lines-of-code"


def named():
    doc = metric_document()
    doc["runs"][0]["properties"]["metricResults"][0]["ruleId"] = RULE
    return doc


class RuleId(unittest.TestCase):
    def test_optional_omission_supported(self):
        self.assertNotIn("ruleId", config(metric_document())["metricResults"][0])

    def test_agreeing_id_bound(self):
        self.assertEqual(config(named())["metricResults"][0]["ruleId"], RULE)

    def test_presence_changes_proof(self):
        self.assertNotEqual(proof(named()), proof(metric_document()))

    def test_nonstring_and_empty_refused(self):
        for value in [None, True, False, 0, 1, [], {}, "", 1.5]:
            with self.subTest(kind=type(value).__name__):
                doc = named()
                doc["runs"][0]["properties"]["metricResults"][0]["ruleId"] = value
                with self.assertRaises(gate.Invalid):
                    config(doc)

    def test_index_descriptor_disagreement_refused(self):
        doc = named()
        doc["runs"][0]["properties"]["metricResults"][0]["ruleId"] = "py/other"
        with self.assertRaises(gate.Invalid):
            config(doc)

    def test_explicit_reference_id_disagreement_refused(self):
        doc = named()
        doc["runs"][0]["properties"]["metricResults"][0]["rule"]["id"] = "py/other"
        with self.assertRaises(gate.Invalid):
            config(doc)

    def test_explicit_reference_id_agreement_passes(self):
        doc = named()
        doc["runs"][0]["properties"]["metricResults"][0]["rule"]["id"] = RULE
        config(doc)

    def test_unrecognized_field_still_refused(self):
        doc = named()
        doc["runs"][0]["properties"]["metricResults"][0]["ruleIndex"] = 0
        with self.assertRaises(gate.Invalid):
            config(doc)

    def test_named_zero_result_malformed_still_refused(self):
        doc = named()
        doc["runs"][0]["results"] = []
        doc["runs"][0]["properties"]["metricResults"][0]["ruleId"] = "py/wrong"
        with self.assertRaises(gate.Invalid):
            cli.language_binding(doc, "python")

    def test_rule_id_diagnostic_never_emits_value(self):
        doc = named()
        doc["runs"][0]["properties"]["metricResults"][0]["ruleId"] = "PRIVATE_RULE_CANARY"
        self.assertNotIn("PRIVATE_", json.dumps(cli.property_shape(doc)))


class BaselineShapes(unittest.TestCase):
    def test_all_four_fields_emit_only_fixed_keys_and_types(self):
        metric = {
            "baseline": 731942,
            "rule": {"id": "PRIVATE_RULE_CANARY"},
            "ruleId": "PRIVATE_ID_CANARY",
            "value": "PRIVATE_VALUE_CANARY",
        }
        before = copy.deepcopy(metric)
        output = metric_shapes([metric])
        self.assertEqual(
            output["items"][0],
            {
                "type": "object",
                "known": [
                    {"key": "baseline", "type": "integer"},
                    {"key": "rule", "type": "object"},
                    {"key": "ruleId", "type": "string"},
                    {"key": "value", "type": "string"},
                ],
                "unknown_key_sha256": [],
            },
        )
        self.assertNotIn("PRIVATE_", json.dumps(output))
        self.assertNotIn("731942", json.dumps(output))
        self.assertEqual(metric, before)

    def test_baseline_diagnostic_reports_types_even_for_refused_values(self):
        for value, label in [
            (None, "null"),
            (False, "boolean"),
            (731942, "integer"),
            (731942.5, "number"),
            ("PRIVATE_BASELINE_CANARY", "string"),
            ({"PRIVATE_NESTED_CANARY": 1}, "object"),
            (["PRIVATE_ARRAY_CANARY"], "array"),
        ]:
            with self.subTest(value_type=label):
                output = metric_shapes([{"baseline": value}])
                self.assertEqual(
                    output["items"][0]["known"],
                    [{"key": "baseline", "type": label}],
                )
                self.assertNotIn("PRIVATE_", json.dumps(output))
                self.assertNotIn("731942", json.dumps(output))

    def test_property_diagnostic_keeps_four_key_and_existing_sample_bounds(self):
        doc = named()
        metric = doc["runs"][0]["properties"]["metricResults"][0]
        metric["baseline"] = "PRIVATE_BASELINE_CANARY"
        metric.update({f"PRIVATE_UNKNOWN_{i}": "PRIVATE_VALUE_CANARY" for i in range(32)})
        doc["runs"][0]["properties"]["metricResults"] *= 20
        output = cli.property_shape(doc)
        encoded = json.dumps(output)
        self.assertNotIn("PRIVATE_", encoded)
        rows = output["runs"][0]["metric_shapes"]
        self.assertEqual(rows["count"], 20)
        self.assertEqual(len(rows["items"]), 8)
        for item in rows["items"]:
            self.assertEqual(len(item["known"]), 4)
            self.assertEqual(len(item["unknown_key_sha256"]), 16)


def two_metrics():
    doc = metric_document()
    run = doc["runs"][0]
    descriptor = copy.deepcopy(run["tool"]["extensions"][0]["rules"][0])
    descriptor["id"] = "py/summary/lines-of-user-code"
    run["tool"]["extensions"][0]["rules"].append(descriptor)
    metric = copy.deepcopy(run["properties"]["metricResults"][0])
    metric["rule"]["index"] = 1
    metric["value"] = 7
    metric["baseline"] = 9
    run["properties"]["metricResults"].append(metric)
    return doc


class MetricIdentityTests(unittest.TestCase):
    def test_metric_row_permutation_preserves_complete_proof(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        second["runs"][0]["properties"]["metricResults"].reverse()
        self.assertEqual(proof(first), proof(second))

    def test_descriptor_permutation_with_resolved_indices_preserves_proof(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        run = second["runs"][0]
        run["tool"]["extensions"][0]["rules"].reverse()
        for metric in run["properties"]["metricResults"]:
            metric["rule"]["index"] = 1 - metric["rule"]["index"]
        self.assertEqual(proof(first), proof(second))

    def test_index_retarget_to_different_descriptor_changes_proof(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        second["runs"][0]["properties"]["metricResults"][0]["rule"]["index"] = 1
        self.assertNotEqual(proof(first), proof(second))

    def test_metric_duplicates_are_retained_after_sorting(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        metrics = second["runs"][0]["properties"]["metricResults"]
        metrics.append(copy.deepcopy(metrics[0]))
        metrics.reverse()
        self.assertEqual(len(config(second)["metricResults"]), 3)
        self.assertNotEqual(proof(first), proof(second))

    def test_nonindex_reference_presence_remains_bound(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        second["runs"][0]["properties"]["metricResults"][0]["rule"]["id"] = (
            "py/summary/lines-of-code"
        )
        self.assertNotEqual(proof(first), proof(second))

    def test_empty_component_reference_presence_remains_bound(self):
        first = metric_document()
        first["runs"][0]["properties"]["metricResults"] = [{"rule": {"index": 0}, "value": 1}]
        second = copy.deepcopy(first)
        second["runs"][0]["properties"]["metricResults"][0]["rule"]["toolComponent"] = {}
        self.assertNotEqual(config(first), config(second))

    def test_optional_coverage_baseline_changes_complete_proof(self):
        first = two_metrics()
        for metric in first["runs"][0]["properties"]["metricResults"]:
            metric.pop("baseline", None)
        for value in [0, -1, 1.5, 10**100]:
            second = copy.deepcopy(first)
            second["runs"][0]["properties"]["metricResults"][1]["baseline"] = value
            with self.subTest(value_type=type(value).__name__):
                self.assertNotEqual(proof(first), proof(second))

    def test_query_configuration_remains_bound(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        second["runs"][0]["properties"]["codeqlConfigSummary"]["queries"] = [
            {"uses": "default", "type": "builtinSuite"}
        ]
        self.assertNotEqual(proof(first), proof(second))

    def test_source_bytes_remain_bound_even_with_same_context_argument(self):
        doc = two_metrics()
        first = MemoryTree()
        second = MemoryTree()
        second.change("src/helper.py", b"value = 2\n")
        finding = gate.classify_document(doc)[0]
        self.assertNotEqual(
            gate.proof(finding, first, "python", "a" * 64),
            gate.proof(finding, second, "python", "a" * 64),
        )

    def test_ordered_finding_flow_remains_bound(self):
        first = two_metrics()
        second = copy.deepcopy(first)
        second["runs"][0]["results"][0]["codeFlows"][0]["threadFlows"][0]["locations"].reverse()
        self.assertNotEqual(proof(first), proof(second))

    def test_component_reindex_preserves_metrics_but_tool_inventory_order_is_bound(self):
        first = metric_document()
        first["runs"][0]["tool"]["extensions"].append(
            {"name": "codeql/other-queries", "semanticVersion": "1.0.0+fixture", "rules": []}
        )
        second = copy.deepcopy(first)
        run = second["runs"][0]
        run["tool"]["extensions"].reverse()
        run["properties"]["metricResults"][0]["rule"]["toolComponent"]["index"] = 1
        self.assertEqual(config(first), config(second))
        before, after = proof(first), proof(second)
        self.assertEqual(
            {key for key in before if before[key] != after[key]},
            {"tool_sha256"},
        )
        # The broader tool inventory retains its conservative ordering contract.
        # A different resolved component version must also change metric identity.
        run["tool"]["extensions"][1]["semanticVersion"] = "2.0.0+fixture"
        self.assertNotEqual(config(first), config(second))
        self.assertNotEqual(proof(first), proof(second))
