# ruff: noqa: E402
"""Accept pinned raw metadata without admitting filtered CodeQL configurations."""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_codeql_sarif import EXPECTED_SUMMARY, property_shape, raw_run_properties
from security_sarif import Invalid

U = "00000000-0000-4000-8000-000000000001"


class Properties(unittest.TestCase):
    def valid(self, props, language="python"):
        if isinstance(props, dict):
            props = {"codeqlConfigSummary": copy.deepcopy(EXPECTED_SUMMARY), **props}
        raw_run_properties({"properties": props}, language)

    def bad(self, props, language="python"):
        with self.assertRaises((Invalid, TypeError)):
            self.valid(props, language)

    def test_summary_absent_raw_job_metadata_refused(self):
        with self.assertRaises(Invalid):
            raw_run_properties({"properties": {"jobRunUuid": U}}, "python")

    def test_summary_absent_properties_absent_refused(self):
        with self.assertRaises(Invalid):
            raw_run_properties({}, "python")

    def test_summary_exact_raw_shape(self):
        self.valid({"codeqlConfigSummary": copy.deepcopy(EXPECTED_SUMMARY)})

    def test_summary_exact_plus_raw_metadata(self):
        self.valid({"codeqlConfigSummary": copy.deepcopy(EXPECTED_SUMMARY), "jobRunUuid": U})

    def test_source_python(self):
        self.valid({"semmle.sourceLanguage": "python"})

    def test_source_javascript(self):
        self.valid({"semmle.sourceLanguage": "javascript"}, "javascript-typescript")

    def test_fixture_format_210(self):
        self.valid({"semmle.formatSpecifier": "2.1.0"})

    def test_unsupported_matrix_language(self):
        self.bad({}, "java")

    def test_diagnostic_surrogate_key_is_only_digest(self):
        text = json.dumps(
            property_shape({"runs": [{"properties": {"\ud800": "PRIVATE_VALUE_CANARY"}}]})
        )
        self.assertNotIn("PRIVATE_", text)

    def test_wrong_language(self):
        self.bad({"semmle.sourceLanguage": "javascript"})

    def test_unknown_format(self):
        self.bad({"semmle.formatSpecifier": "other"})

    def test_incremental_rejected(self):
        self.bad({"incrementalMode": "diff-informed"})

    def test_overlay_rejected(self):
        self.bad({"incrementalMode": "overlay"})

    def test_empty_incremental_rejected(self):
        self.bad({"incrementalMode": ""})

    def test_unknown_property_rejected(self):
        self.bad({"PRIVATE_PROPERTY_CANARY": "PRIVATE_VALUE_CANARY"})

    def test_null_properties_rejected(self):
        self.bad(None)

    def test_summary_null_rejected(self):
        self.bad({"codeqlConfigSummary": None})

    def test_summary_string_rejected(self):
        self.bad({"codeqlConfigSummary": json.dumps(EXPECTED_SUMMARY)})

    def test_summary_filter_rejected(self):
        self.bad(
            {
                "codeqlConfigSummary": EXPECTED_SUMMARY
                | {"query-filters": [{"exclude": {"id": "x"}}]}
            }
        )

    def test_summary_paths_rejected(self):
        self.bad({"codeqlConfigSummary": EXPECTED_SUMMARY | {"paths": ["src"]}})

    def test_summary_default_suite_rejected(self):
        self.bad(
            {"codeqlConfigSummary": {"queries": [{"type": "builtinSuite", "uses": "default"}]}}
        )

    def test_summary_disabled_defaults_rejected(self):
        self.bad({"codeqlConfigSummary": EXPECTED_SUMMARY | {"disable-default-queries": True}})

    def test_raw_summary_disabled_defaults_rejected(self):
        self.bad({"codeqlConfigSummary": EXPECTED_SUMMARY | {"disableDefaultQueries": True}})

    def test_raw_summary_default_flag_missing_rejected(self):
        self.bad({"codeqlConfigSummary": {"queries": EXPECTED_SUMMARY["queries"]}})

    def test_raw_summary_default_flag_integer_rejected(self):
        self.bad({"codeqlConfigSummary": EXPECTED_SUMMARY | {"disableDefaultQueries": 0}})

    def test_uuid_malformed_rejected(self):
        self.bad({"jobRunUuid": "PRIVATE_UUID_CANARY"})

    def test_uuid_bool_rejected(self):
        self.bad({"jobRunUuid": True})

    def test_uuid_non_v4_rejected(self):
        self.bad({"jobRunUuid": U.replace("-4000-", "-1000-")})

    def test_diagnostic_does_not_print_unknown_keys_or_values(self):
        text = json.dumps(
            property_shape(
                {
                    "runs": [
                        {
                            "properties": {
                                "PRIVATE_KEY_CANARY": "PRIVATE_VALUE_CANARY",
                                "jobRunUuid": "PRIVATE_UUID_CANARY",
                                "codeqlConfigSummary": {
                                    "queries": [{"uses": "PRIVATE_SUITE_CANARY"}]
                                },
                            }
                        }
                    ]
                }
            )
        )
        self.assertNotIn("PRIVATE_", text)
        self.assertIn("unknown_key_sha256", text)

    def test_diagnostic_types_and_known_flags(self):
        out = property_shape(
            {
                "runs": [
                    {
                        "properties": {
                            "incrementalMode": "diff-informed",
                            "jobRunUuid": U,
                            "codeqlConfigSummary": EXPECTED_SUMMARY,
                        }
                    }
                ]
            }
        )
        self.assertTrue(out["runs"][0]["summary_exact_expected"])
        self.assertTrue(out["runs"][0]["job_uuid_canonical_v4"])
        self.assertEqual(out["runs"][0]["incrementalMode_known_value"], "diff-informed")

    def test_diagnostic_invalid_shape(self):
        self.assertEqual(property_shape({"runs": None}), {"runs_shape": "invalid"})
