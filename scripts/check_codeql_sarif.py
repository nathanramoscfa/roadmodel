#!/usr/bin/env python3
"""Fail CI on CodeQL high/critical security findings or error-level results."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path


def check(directory: Path) -> int:
    files = list(directory.glob("*.sarif"))
    if not files:
        raise ValueError("CodeQL produced no SARIF files")
    count = 0
    for path in files:
        data = json.loads(path.read_text())
        if data["version"] != "2.1.0" or not data["runs"]:
            raise ValueError("Invalid SARIF document")
        for run in data["runs"]:
            tool = run["tool"]
            components = [tool["driver"], *tool.get("extensions", [])]
            # A valid empty analysis can omit the rule catalog entirely.
            # CodeQL packs can also carry rules in extension components.
            by_id = {}
            for component in components:
                for rule in component.get("rules", []):
                    if rule["id"] in by_id:
                        raise ValueError("Ambiguous rule identifier")
                    by_id[rule["id"]] = rule
            for result in run["results"]:
                reference = result.get("rule", {})
                rule_id = result.get("ruleId", reference.get("id"))
                if rule_id is not None:
                    rule = by_id[rule_id]
                else:
                    index = result.get("ruleIndex", reference.get("index"))
                    if not isinstance(index, int) or index < 0:
                        raise ValueError("Invalid rule index")
                    component_index = reference.get("toolComponent", {}).get("index")
                    component = tool["driver"]
                    if component_index is not None:
                        if not isinstance(component_index, int) or component_index < 0:
                            raise ValueError("Invalid tool component index")
                        component = tool["extensions"][component_index]
                    rules = component["rules"]
                    rule = rules[index]
                score = float(rule.get("properties", {}).get("security-severity", 0))
                if not math.isfinite(score) or not 0 <= score <= 10:
                    raise ValueError("Invalid security severity")
                level = result.get(
                    "level", rule.get("defaultConfiguration", {}).get("level", "warning")
                )
                if score >= 7 or level == "error":
                    # Rule IDs are public scanner metadata; never print source,
                    # result messages, or data-flow snippets in CI diagnostics.
                    identifier = rule["id"]
                    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", identifier):
                        raise ValueError("Invalid rule identifier")
                    print(f"Blocking rule: {identifier}; severity={score}; level={level}")
                    count += 1
    return count


if __name__ == "__main__":
    try:
        findings = check(Path(sys.argv[1]))
        print(f"CodeQL blocking findings: {findings}")
        raise SystemExit(1 if findings else 0)
    except (ValueError, KeyError, IndexError, TypeError, OSError):
        print("CodeQL results are missing or invalid; refusing to pass the scan.")
        raise SystemExit(1) from None
