#!/usr/bin/env python3
"""Fail CI on CodeQL high/critical security findings or error-level results."""

from __future__ import annotations

import json
import math
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
            rules = run["tool"]["driver"]["rules"]
            by_id = {rule["id"]: rule for rule in rules}
            for result in run["results"]:
                if "ruleId" in result:
                    rule = by_id[result["ruleId"]]
                else:
                    index = result["ruleIndex"]
                    if not isinstance(index, int) or index < 0:
                        raise ValueError("Invalid rule index")
                    rule = rules[index]
                score = float(rule.get("properties", {}).get("security-severity", 0))
                if not math.isfinite(score) or not 0 <= score <= 10:
                    raise ValueError("Invalid security severity")
                level = result.get(
                    "level", rule.get("defaultConfiguration", {}).get("level", "warning")
                )
                if score >= 7 or level == "error":
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
