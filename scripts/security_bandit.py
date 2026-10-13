"""Validate whole-tree Bandit coverage and exact reviewed finding occurrences."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from security_manifest import manifest, selected_context
from security_sarif import HEX, arr, digest, obj, repo_path, require, string

LOCK = ".github/requirements-security.txt"
INPUT = ".github/requirements-security.in"
VERSION = "1.9.4"
PROFILE = {
    "scanner": "bandit",
    "version": VERSION,
    "targets": "all-tracked-py-v1",
    "config": "built-in-defaults",
    "ignore_nosec": True,
    "baseline": False,
    "debug_failures": True,
    "filters": "none",
    "threshold": ["MEDIUM", "HIGH"],
}
RANKS = {"UNDEFINED", "LOW", "MEDIUM", "HIGH"}
METRICS = {"loc", "nosec", "skipped_tests"} | {
    a + "." + b for a in ("SEVERITY", "CONFIDENCE") for b in RANKS
}
RESULT = {
    "code",
    "col_offset",
    "end_col_offset",
    "filename",
    "issue_confidence",
    "issue_cwe",
    "issue_severity",
    "issue_text",
    "line_number",
    "line_range",
    "more_info",
    "test_id",
    "test_name",
}
PROOF = {
    "rule_id",
    "severity",
    "confidence",
    "context_sha256",
    "tool_sha256",
    "profile_sha256",
    "finding_sha256",
    "source",
}
ENTRY = {"id", "rationale", "disposition", "reviewed_revision", "max_occurrences", "proof"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def nonnegative(value):
    require(type(value) is int and 0 <= value <= 100_000_000)
    return value


def normalized_path(value):
    value = string(value)
    # Bandit prefixes explicitly supplied relative targets with exactly './'.
    if value.startswith("./"):
        value = value[2:]
    return repo_path(value)


def inventory(tree):
    paths = sorted(path for path in tree.entries if path.endswith(".py"))
    require(bool(paths))
    return paths


def lock_versions(tree):
    require(LOCK in tree.blobs and INPUT in tree.blobs)
    text = tree.blobs[LOCK].decode("utf-8")
    # This is the reviewed pip-compile profile: only exact pins, two known marker
    # shapes, hash continuations and comments. Never a URL, option or editable.
    pins = {}
    current = None
    hashes = 0

    def finish():
        if current is not None:
            require(hashes > 0)

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(
            r"([a-z0-9][a-z0-9-]*)==([0-9][A-Za-z0-9.!+_-]*)(?: ; (sys_platform == 'win32'|python_full_version < '3.13'))? \\",
            line,
        )
        if match:
            finish()
            current = match[1]
            hashes = 0
            require(current not in pins)
            pins[current] = match[2]
        else:
            require(
                current is not None
                and bool(re.fullmatch(r"    --hash=sha256:[0-9a-f]{64}(?: \\)?", line))
            )
            hashes += 1
    finish()
    require(pins.get("bandit") == VERSION)
    require(f"bandit=={VERSION}" in tree.blobs[INPUT].decode("utf-8").splitlines())
    return pins


def validate_identity(value, tree):
    value = obj(value)
    require(
        set(value)
        == {
            "schema",
            "bandit_version",
            "python",
            "lock_sha256",
            "input_sha256",
            "implementation_sha256",
            "distributions",
            "profile_sha256",
        }
    )
    require(
        type(value["schema"]) is int and value["schema"] == 1 and value["bandit_version"] == VERSION
    )
    require(bool(re.fullmatch(r"3\.(?:1[2-9]|[2-9][0-9])\.[0-9]{1,3}", string(value["python"]))))
    pins = lock_versions(tree)
    require(
        value["lock_sha256"] == sha(tree.blobs[LOCK])
        and value["input_sha256"] == sha(tree.blobs[INPUT])
    )
    require(value["profile_sha256"] == digest(PROFILE))
    require(bool(HEX.fullmatch(string(value["implementation_sha256"]))))
    rows = arr(value["distributions"])
    names = set()
    require(1 <= len(rows) <= 50)
    for row in rows:
        row = obj(row)
        require(set(row) == {"name", "version", "files_sha256"})
        name = row["name"]
        require(name in pins and name not in names)
        names.add(name)
        require(row["version"] == pins[name] and bool(HEX.fullmatch(string(row["files_sha256"]))))
    require({"bandit", "packaging"}.issubset(names))
    require(rows == sorted(rows, key=lambda x: x["name"]))
    return value


def metric(value):
    value = obj(value)
    require(set(value) == METRICS)
    for count in value.values():
        nonnegative(count)
    require(value["nosec"] == 0 and value["skipped_tests"] == 0)
    return value


def loc(data):
    # Exact Bandit 1.9.4 Metrics.count_locs algorithm, including blank files.
    return sum(
        bool(line.strip() and not line.strip().startswith(b"#")) for line in data.splitlines()
    )


def parse_report(document, tree, returncode):
    document = obj(document)
    require(set(document) == {"errors", "generated_at", "metrics", "results"})
    require(arr(document["errors"]) == [])
    require(
        bool(
            re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
                string(document["generated_at"]),
            )
        )
    )
    raw_metrics = obj(document["metrics"])
    require("_totals" in raw_metrics)
    expected = inventory(tree)
    metrics = {}
    for path, values in raw_metrics.items():
        if path == "_totals":
            continue
        path = normalized_path(path)
        require(path not in metrics)
        metrics[path] = metric(values)
    require(set(metrics) == set(expected))
    totals = metric(raw_metrics["_totals"])
    require(totals["loc"] > 0)
    require(totals == {key: sum(item[key] for item in metrics.values()) for key in METRICS})
    for path in expected:
        require(metrics[path]["loc"] == loc(tree.blobs[path]))
    findings = []
    counts = {path: Counter() for path in expected}
    for raw in arr(document["results"]):
        row = obj(raw)
        require(set(row) == RESULT)
        path = normalized_path(row["filename"])
        require(path in metrics)
        severity, confidence = row["issue_severity"], row["issue_confidence"]
        require(severity in RANKS and confidence in RANKS)
        # Unknown ranks must never accidentally become below-threshold findings.
        require(severity != "UNDEFINED" and confidence != "UNDEFINED")
        require(bool(re.fullmatch(r"B[0-9]{3}", string(row["test_id"]))))
        require(bool(re.fullmatch(r"[a-z][a-z0-9_]{0,100}", string(row["test_name"]))))
        for key in ("code", "issue_text", "more_info"):
            require(isinstance(row[key], str))
        cwe = obj(row["issue_cwe"])
        require(not cwe or set(cwe) == {"id", "link"})
        if cwe:
            require(type(cwe["id"]) is int and 1 <= cwe["id"] <= 100000)
            require(cwe["link"] == f"https://cwe.mitre.org/data/definitions/{cwe['id']}.html")
        lines = arr(row["line_range"])
        require(bool(lines))
        require(all(type(x) is int and x > 0 for x in lines) and lines == sorted(set(lines)))
        require(type(row["line_number"]) is int and row["line_number"] in lines)
        source_lines = tree.blobs[path].splitlines(keepends=True)
        require(lines[-1] <= len(source_lines))
        # Bandit offsets are zero-based byte offsets; keep their exact values,
        # including -1 when an issue has no AST start column.
        first, last = row["col_offset"], row["end_col_offset"]
        require(type(first) is int and type(last) is int and first >= -1 and last >= 0)
        require(
            first <= len(source_lines[lines[0] - 1].rstrip(b"\r\n"))
            and last <= len(source_lines[lines[-1] - 1].rstrip(b"\r\n"))
        )
        require(len(lines) > 1 or last == 0 or last >= first)
        binding = tree.bind_region(
            path, {"startLine": lines[0], "endLine": lines[-1]}, "unicodeCodePoints"
        )
        source = {
            "path": path,
            **binding,
            "line_number": row["line_number"],
            "line_range": lines,
            "col_offset": first,
            "end_col_offset": last,
        }
        canonical = {**row, "filename": path}
        findings.append(
            {
                "rule_id": row["test_id"],
                "severity": severity,
                "confidence": confidence,
                "finding_sha256": digest(canonical),
                "source": source,
            }
        )
        counts[path]["SEVERITY." + severity] += 1
        counts[path]["CONFIDENCE." + confidence] += 1
    for path in expected:
        for key in METRICS - {"loc", "nosec", "skipped_tests"}:
            require(metrics[path][key] == counts[path][key])
    require(type(returncode) is int and returncode == (1 if findings else 0))
    return findings, {
        "tracked_python_files": len(expected),
        "covered_files": len(metrics),
        "loc": totals["loc"],
        "errors": 0,
        "inventory_sha256": digest(expected),
        "counts": {rank: totals["SEVERITY." + rank] for rank in sorted(RANKS)},
    }


def proof(finding, tree, identity, context=None):
    return {
        **finding,
        "context_sha256": context or tree.context_digest(),
        "tool_sha256": digest(identity),
        "profile_sha256": digest(PROFILE),
    }


def validate_entries(value, tree, identity, context=None):
    context = context or selected_context(tree, manifest(value)["context_policy"])
    entries = manifest(value)["bandit"]
    signatures = {}
    ids = set()
    for entry in entries:
        require(set(entry) == ENTRY)
        eid = string(entry["id"])
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", eid)) and eid not in ids)
        ids.add(eid)
        require(entry["disposition"] in {"false-positive", "accepted-risk"})
        require(isinstance(entry["rationale"], str) and 1 <= len(entry["rationale"]) <= 1000)
        require(bool(re.fullmatch(r"[0-9a-f]{40}", string(entry["reviewed_revision"]))))
        require(type(entry["max_occurrences"]) is int and entry["max_occurrences"] == 1)
        p = obj(entry["proof"])
        require(set(p) == PROOF)
        require(
            bool(re.fullmatch(r"B[0-9]{3}", string(p["rule_id"])))
            and p["severity"] in {"MEDIUM", "HIGH"}
            and p["confidence"] in RANKS - {"UNDEFINED"}
        )
        for key in ("context_sha256", "tool_sha256", "profile_sha256", "finding_sha256"):
            require(bool(HEX.fullmatch(string(p[key]))))
        require(
            p["context_sha256"] == context
            and p["tool_sha256"] == digest(identity)
            and p["profile_sha256"] == digest(PROFILE)
        )
        source = obj(p["source"])
        require(
            set(source)
            == {
                "path",
                "mode",
                "sha256",
                "line_sha256",
                "line_number",
                "line_range",
                "col_offset",
                "end_col_offset",
            }
        )
        path = repo_path(source["path"])
        require(path.endswith(".py") and path in tree.entries)
        require(
            source["mode"] == tree.entries[path]["mode"]
            and source["sha256"] == tree.entries[path]["sha256"]
        )
        lines = arr(source["line_range"])
        require(
            bool(lines)
            and all(type(x) is int and x > 0 for x in lines)
            and lines == sorted(set(lines))
        )
        require(type(source["line_number"]) is int and source["line_number"] in lines)
        for key in ("col_offset", "end_col_offset"):
            require(type(source[key]) is int)
        bound = tree.bind_region(
            path, {"startLine": lines[0], "endLine": lines[-1]}, "unicodeCodePoints"
        )
        require(source["line_sha256"] == bound["line_sha256"])
        signature = digest(p)
        require(signature not in signatures)
        signatures[signature] = entry
    return signatures


def review(document, tree, identity, returncode, context_policy="whole-tree-v1"):
    context = selected_context(tree, context_policy)
    validate_identity(identity, tree)
    findings, coverage = parse_report(document, tree, returncode)
    candidates = [
        proof(item, tree, identity, context)
        for item in findings
        if item["severity"] in {"MEDIUM", "HIGH"}
    ]
    return {
        "schema": 1,
        "purpose": "review-only",
        "active_allowances": 0,
        "profile": PROFILE,
        "context_sha256": context,
        "context_policy": context_policy,
        "tool_identity": identity,
        "coverage": coverage,
        "raw_results": len(findings),
        "raw_blocking": len(candidates),
        "candidates": [{"occurrence": i + 1, "proof": p} for i, p in enumerate(candidates)],
    }


def evaluate(document, tree, identity, value, returncode):
    context_policy = manifest(value)["context_policy"]
    material = review(document, tree, identity, returncode, context_policy)
    available = validate_entries(value, tree, identity, material["context_sha256"])
    used = set()
    blocked = 0
    for candidate in material["candidates"]:
        signature = digest(candidate["proof"])
        if signature in available and signature not in used:
            used.add(signature)
        else:
            blocked += 1
    require(len(used) == len(available))
    return {
        "raw_results": material["raw_results"],
        "raw_blocking": material["raw_blocking"],
        "blocking": blocked,
        "allowed": len(used),
        "coverage": material["coverage"],
        "rule_ids": sorted({p["proof"]["rule_id"] for p in material["candidates"]}),
    }
