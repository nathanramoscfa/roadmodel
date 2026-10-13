"""Synthetic SARIF fixtures; no analyzer execution or repository state."""

import hashlib

import security_sarif as gate
from security_source import GitTree


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


def metric_document(value=123):
    doc = document()
    run = doc["runs"][0]
    component = run["tool"]["extensions"][0]
    component.setdefault("rules", []).append(
        {
            "id": "py/summary/lines-of-code",
            "name": "Synthetic metric",
            "properties": {"kind": "metric", "tags": ["summary", "lines-of-code"]},
        }
    )
    index = len(component["rules"]) - 1
    run["properties"].update(
        {
            "jobRunUuid": "00000000-0000-4000-8000-000000000001",
            "semmle.formatSpecifier": "sarif-latest",
            "metricResults": [
                {"rule": {"index": index, "toolComponent": {"index": 0}}, "value": value}
            ],
        }
    )
    return doc
