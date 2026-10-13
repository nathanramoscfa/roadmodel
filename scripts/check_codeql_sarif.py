# ruff: noqa: E402
"""Require complete CodeQL analysis and enforce exact reviewed finding allowances."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# -I excludes ambient import paths; only the reviewed sibling implementation is added.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_manifest import (
    EMPTY,
    MANIFEST_PATH,
    codeql_namespace,
    selected_context,
)
from security_manifest import (
    SharedGitTree as GitTree,
)
from security_manifest import (
    manifest as shared_manifest,
)
from security_sarif import (
    LANGUAGES,
    MAX_JSON,
    Canonicalizer,
    arr,
    canonical_run_configuration,
    classify_document,
    digest,
    evaluate,
    identity,
    load_json,
    obj,
    proof,
    require,
)
from security_source import bounded_regular

ANALYSIS_PROFILE = {
    "schema": 1,
    "suite": "security-extended",
    "diff_informed": False,
    "overlay_mode": "none",
}


def contract_failure_locations(error: Exception) -> list[dict]:
    """Report only public validator line numbers; never exception text or locals."""
    components = {
        "check_codeql_sarif.py",
        "check_bandit.py",
        "security_sarif.py",
        "security_source.py",
        "security_catalog.py",
        "security_manifest.py",
        "security_bandit.py",
    }
    directory = Path(__file__).resolve().parent
    locations = []
    trace = error.__traceback__
    while trace is not None:
        path = Path(trace.tb_frame.f_code.co_filename)
        if path.parent == directory and path.name in components:
            locations.append({"component": path.name, "line": trace.tb_lineno})
        trace = trace.tb_next
    return locations[-12:]


def require_full_profile() -> None:
    require(sys.flags.isolated == 1 and sys.dont_write_bytecode)
    require(os.environ.get("CODEQL_ACTION_DIFF_INFORMED_QUERIES") == "false")
    require(os.environ.get("CODEQL_OVERLAY_DATABASE_MODE") == "none")


def snapshot_material(tree: GitTree) -> dict:
    return {
        "schema": 1,
        "scanner": "codeql",
        "analysis_profile": ANALYSIS_PROFILE,
        "source": tree.receipt(),
    }


def verify_snapshot(tree: GitTree, value: dict) -> None:
    value = obj(value)
    require(set(value) == {"schema", "scanner", "analysis_profile", "source"})
    require(type(value["schema"]) is int and value["schema"] == 1)
    require(value["scanner"] == "codeql")
    require(digest(obj(value["analysis_profile"])) == digest(ANALYSIS_PROFILE))
    tree.verify_receipt(value["source"])


def read(path: Path, limit=MAX_JSON) -> bytes:
    require(not path.is_symlink())
    return bounded_regular(path.parent.resolve(strict=True), path.name, limit)[0]


def write_receipt(path: Path, value: dict) -> None:
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    require(len(data) <= MAX_JSON)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        written = os.write(descriptor, data)
        require(written == len(data))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


EXPECTED_SUMMARY = {
    "disableDefaultQueries": False,
    "queries": [{"type": "builtinSuite", "uses": "security-extended"}],
}
SUPPORTED_KEYS = {
    "codeqlConfigSummary",
    "jobRunUuid",
    "semmle.formatSpecifier",
    "semmle.sourceLanguage",
    "metricResults",
}
DIAGNOSTIC_KEYS = SUPPORTED_KEYS | {"incrementalMode"}
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def raw_run_properties(run, language):
    require(language in {"python", "javascript-typescript"})
    # Match raw metadata from the pinned Action without ignoring query policy.
    # Keep the exact suite summary and all independent workflow/pack checks.
    properties = obj(obj(run).get("properties", {}))
    require(not set(properties) - SUPPORTED_KEYS)
    require("codeqlConfigSummary" in properties)
    require(digest(obj(properties["codeqlConfigSummary"])) == digest(EXPECTED_SUMMARY))
    if "jobRunUuid" in properties:
        value = properties["jobRunUuid"]
        require(isinstance(value, str) and UUID4.fullmatch(value) is not None)
    if "semmle.formatSpecifier" in properties:
        require(properties["semmle.formatSpecifier"] in ("sarif-latest", "2.1.0"))
    if "semmle.sourceLanguage" in properties:
        expected = "python" if language == "python" else "javascript"
        require(properties["semmle.sourceLanguage"] == expected)
    # Validate metric references and values even when the run has no findings.
    canonical_run_configuration(properties, run)


def metric_shapes(metrics):
    types = {
        dict: "object",
        list: "array",
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        type(None): "null",
    }
    output = {"type": types.get(type(metrics), "other")}
    if not isinstance(metrics, list):
        return output
    output["count"] = len(metrics)
    output["items"] = []
    for metric in metrics[:8]:
        row = {"type": types.get(type(metric), "other")}
        if isinstance(metric, dict):
            row["known"] = [
                {"key": key, "type": types.get(type(metric[key]), "other")}
                for key in sorted(set(metric) & {"rule", "value"})
            ]
            row["unknown_key_sha256"] = sorted(
                hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()
                for key in metric
                if key not in {"rule", "value"}
            )[:16]
        output["items"].append(row)
    return output


def property_shape(document):
    """Only approved key/type/enums or digests; never dump a property value."""
    runs = document.get("runs") if isinstance(document, dict) else None
    if not isinstance(runs, list):
        return {"runs_shape": "invalid"}
    output = []
    types = {
        dict: "object",
        list: "array",
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        type(None): "null",
    }
    for run in runs[:8]:
        props = run.get("properties", {}) if isinstance(run, dict) else None
        row = {"properties_type": types.get(type(props), "other")}
        if isinstance(props, dict):
            row["property_count"] = len(props)
            row["known"] = [
                {"key": key, "type": types.get(type(props[key]), "other")}
                for key in sorted(set(props) & DIAGNOSTIC_KEYS)
            ]
            row["unknown_key_sha256"] = sorted(
                hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()
                for key in props
                if key not in DIAGNOSTIC_KEYS
            )[:16]
            if "metricResults" in props:
                row["metric_shapes"] = metric_shapes(props["metricResults"])
            summary = props.get("codeqlConfigSummary")
            if isinstance(summary, dict):
                row["summary_exact_expected"] = digest(summary) == digest(EXPECTED_SUMMARY)
                row["summary_known_keys"] = sorted(
                    set(summary)
                    & {
                        "queries",
                        "packs",
                        "paths",
                        "paths-ignore",
                        "query-filters",
                        "disable-default-queries",
                        "disableDefaultQueries",
                    }
                )
                row["summary_other_key_count"] = len(
                    set(summary)
                    - {
                        "queries",
                        "packs",
                        "paths",
                        "paths-ignore",
                        "query-filters",
                        "disable-default-queries",
                        "disableDefaultQueries",
                    }
                )
            if "jobRunUuid" in props:
                v = props["jobRunUuid"]
                row["job_uuid_canonical_v4"] = isinstance(v, str) and UUID4.fullmatch(v) is not None
            for key, allowed in [
                ("semmle.formatSpecifier", {"sarif-latest", "2.1.0"}),
                ("semmle.sourceLanguage", {"python", "javascript"}),
                ("incrementalMode", {"diff-informed", "overlay", "diff-informed,overlay"}),
            ]:
                if key in props:
                    v = props[key]
                    row[key + "_known_value"] = (
                        v if isinstance(v, str) and v in allowed else "unrecognized"
                    )
        output.append(row)
    return {"runs_count": len(runs), "runs": output}


def language_binding(document: dict, language: str) -> None:
    expected = "codeql/python-queries" if language == "python" else "codeql/javascript-queries"
    for run in arr(document.get("runs")):
        try:
            raw_run_properties(run, language)
        except Exception as error:
            error.property_shape = property_shape({"runs": [run]})
            raise
        tool = obj(obj(run).get("tool"))
        identity(obj(tool.get("driver")))
        extensions = arr(tool.get("extensions", []))
        for component in extensions:
            identity(obj(component))
        names = [obj(component).get("name") for component in extensions]
        require(names.count(expected) == 1)
        require(
            not any(
                name in {"codeql/python-queries", "codeql/javascript-queries"} and name != expected
                for name in names
            )
        )


def execution_binding(tree: GitTree, language: str) -> dict:
    """Only fixed enums, numeric run identifiers and verified commit hashes leave memory."""
    event, ref = os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_REF", "")
    require(os.environ.get("GITHUB_SHA") == tree.commit)
    values = {}
    for key in ["GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"]:
        value = os.environ.get(key, "")
        require(bool(re.fullmatch(r"[1-9][0-9]{0,19}", value)))
        values[key.lower()] = int(value)
    values.update(
        language=language, analyzed_commit=tree.commit, query_policy="full-security-extended-v1"
    )
    head, base = os.environ.get("CODEQL_PR_HEAD_SHA", ""), os.environ.get("CODEQL_PR_BASE_SHA", "")
    if event == "pull_request":
        matched = re.fullmatch(r"refs/pull/([1-9][0-9]{0,9})/merge", ref)
        require(matched is not None)
        require(
            bool(re.fullmatch(r"[0-9a-f]{40}", head)) and bool(re.fullmatch(r"[0-9a-f]{40}", base))
        )
        # cat-file preserves parents even in the default shallow checkout.
        header = tree.git("cat-file", "-p", tree.commit).split(b"\n\n", 1)[0]
        parents = [
            line[7:].decode("ascii") for line in header.splitlines() if line.startswith(b"parent ")
        ]
        require(parents == [base, head])
        values.update(
            event="pull_request",
            pull_request=int(matched[1]),
            reviewed_head=head,
            reviewed_base=base,
        )
    else:
        require(event == "push" and ref == "refs/heads/main" and not head and not base)
        values.update(event="push_main")
    return values


def typed_graph(canonical: dict) -> dict:
    """Project ordered source geometry; hash all scanner prose/state instead of copying it."""

    def location(value):
        physical = value["physicalLocation"]
        projected = {
            "path": physical["path"],
            "region": {
                key: item
                for key, item in physical["region"].items()
                if key in {"startLine", "endLine", "startColumn", "endColumn"}
            },
            "location_sha256": digest(value),
        }
        if "contextRegion" in physical:
            projected["context_region"] = {
                key: item
                for key, item in physical["contextRegion"].items()
                if key in {"startLine", "endLine", "startColumn", "endColumn"}
            }
        return projected

    flows = []
    for flow in canonical["codeFlows"]:
        threads = []
        for thread in flow["threadFlows"]:
            nodes = [
                {"location": location(node["location"]), "node_sha256": digest(node)}
                for node in thread["locations"]
            ]
            threads.append({"thread_sha256": digest(thread), "nodes": nodes})
        flows.append({"flow_sha256": digest(flow), "threads": threads})
    return {
        "primary": [location(x) for x in canonical["locations"]],
        "related": [location(x) for x in canonical["relatedLocations"]],
        "flows": flows,
        "message_sha256": digest(canonical.get("message", {})),
    }


def review_material(
    documents: list[dict], raw_hashes: list[str], tree: GitTree, language: str, context_policy
) -> dict:
    context = selected_context(tree, context_policy)
    execution = execution_binding(tree, language)
    candidates = []
    total = 0
    for document_index, document in enumerate(documents):
        findings = classify_document(document)
        for finding in findings:
            total += 1
            # Even below-threshold results must have coherent supported references.
            canonical = Canonicalizer(finding.run, tree).result(finding.result)
            if finding.blocking:
                candidates.append(
                    {
                        "occurrence": len(candidates) + 1,
                        "document_index": document_index,
                        "proof": proof(finding, tree, language, context),
                        "typed_graph": typed_graph(canonical),
                    }
                )
    return {
        "schema": 1,
        "purpose": "review-only",
        "active_allowances": 0,
        "execution": execution,
        "analysis_profile": ANALYSIS_PROFILE,
        "context_policy": context_policy,
        "source_snapshot": tree.receipt(),
        "raw_sarif_sha256": raw_hashes,
        "raw_results": total,
        "raw_blocking": len(candidates),
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--repo", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    for name in ["check", "review"]:
        command = sub.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--directory", type=Path, required=True)
        command.add_argument("--language", choices=sorted(LANGUAGES), required=True)
        if name == "review":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_full_profile()
    tree = GitTree(args.repo)
    if args.command == "snapshot":
        tree.verify_checkout()
        write_receipt(args.output, snapshot_material(tree))
        print("CodeQL source snapshot verified.")
        return 0
    # An action can fail after writing partial or zero-result SARIF. Never turn
    # that output into an accepted clean proof, even if invocations are absent.
    require(os.environ.get("CODEQL_ANALYZE_OUTCOME") == "success")
    execution_binding(tree, args.language)
    verify_snapshot(tree, load_json(read(args.snapshot)))
    require(not args.directory.is_symlink() and args.directory.is_dir())
    directory = args.directory.resolve(strict=True)
    names = sorted(os.listdir(directory))
    require(0 < len(names) <= 8)
    documents = []
    raw_hashes = []
    total = 0
    for name in names:
        require(name.lower().endswith(".sarif"))
        raw = bounded_regular(directory, name, MAX_JSON)[0]
        total += len(raw)
        require(total <= 128 * 1024 * 1024)
        document = load_json(raw)
        language_binding(document, args.language)
        documents.append(document)
        raw_hashes.append(hashlib.sha256(raw).hexdigest())
    combined = shared_manifest(
        load_json(tree.blobs[MANIFEST_PATH]) if MANIFEST_PATH in tree.blobs else EMPTY
    )
    manifest = codeql_namespace(combined)
    if args.command == "review":
        material = review_material(
            documents, raw_hashes, tree, args.language, manifest.get("context_policy")
        )
        verify_snapshot(tree, load_json(read(args.snapshot)))
        write_receipt(args.output, material)
        print("CodeQL review-only proof artifact created; no finding approved.")
        return 0
    result = evaluate(documents, tree, manifest, args.language)
    verify_snapshot(tree, load_json(read(args.snapshot)))
    print(
        json.dumps(
            {
                key: result[key]
                for key in ["raw_results", "raw_blocking", "blocking", "allowed", "rule_ids"]
            },
            sort_keys=True,
        )
    )
    return 1 if result["blocking"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("CodeQL analysis or reviewed allowance is missing, stale or invalid; gate refused.")
        print(json.dumps({"contract_locations": contract_failure_locations(error)}))
        if getattr(error, "property_shape", None) is not None:
            print(json.dumps({"property_shape": error.property_shape}))
        raise SystemExit(1) from None
