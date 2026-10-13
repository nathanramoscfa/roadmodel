"""Validate the supported CodeQL SARIF profile and exact reviewed findings.

Raw scanner prose and source snippets are hashed in memory, never printed."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

MAX_JSON = 64 * 1024 * 1024
MAX_NODES = 1_000_000
MAX_DEPTH = 64
LEVELS = {"none", "note", "warning", "error"}
LANGUAGES = {"python", "javascript-typescript"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_./-]{1,200}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST_PATH = ".github/codeql-allowances.json"


class Invalid(ValueError):
    """Fixed category only; callers never print an underlying exception."""


class Unallowable(Invalid):
    """The result stays blocking outside the exact-allowance location profile."""


def require(condition: bool) -> None:
    if not condition:
        raise Invalid("CodeQL contract refused")


def obj(value: Any) -> dict:
    require(isinstance(value, dict))
    return value


def arr(value: Any) -> list:
    require(isinstance(value, list))
    return value


def idx(value: Any, length: int) -> int:
    require(type(value) is int and 0 <= value < length)
    return value


def string(value: Any) -> str:
    require(isinstance(value, str) and bool(value))
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def load_json(raw: bytes) -> dict:
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_JSON)

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result

    def constant(_):
        raise Invalid("Nonfinite JSON constant")

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise Invalid("Invalid CodeQL JSON") from None
    count = 0

    def bounded(value, depth=0):
        nonlocal count
        count += 1
        require(count <= MAX_NODES and depth <= MAX_DEPTH)
        if isinstance(value, dict):
            for key, child in value.items():
                require(len(key) <= 2048)
                bounded(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                bounded(child, depth + 1)
        elif isinstance(value, str):
            require(len(value) <= 1024 * 1024)
        elif isinstance(value, float):
            require(math.isfinite(value))

    bounded(data)
    return obj(data)


def agreed(a: dict, ka: str, b: dict, kb: str):
    if ka in a and kb in b:
        require(type(a[ka]) is type(b[kb]) and a[ka] == b[kb])
    return a.get(ka, b.get(kb))


def resolve_rule(run: dict, result: dict) -> tuple[dict, dict]:
    tool = obj(run["tool"])
    driver = obj(tool["driver"])
    extensions = [obj(x) for x in arr(tool.get("extensions", []))]
    reference = obj(result.get("rule", {}))
    require(not (set(reference) - {"id", "index", "guid", "toolComponent"}))
    component_reference = obj(reference.get("toolComponent", {}))
    require(not (set(component_reference) - {"name", "index", "guid"}))
    component = driver
    if "index" in component_reference:
        component = extensions[idx(component_reference["index"], len(extensions))]
    if "guid" in component_reference:
        guid = string(component_reference["guid"])
        matches = [x for x in [driver, *extensions] if x.get("guid") == guid]
        require(len(matches) == 1)
        if "index" in component_reference:
            require(matches[0] is component)
        component = matches[0]
    if "name" in component_reference:
        require(string(component_reference["name"]) == component.get("name"))
    rules = [obj(x) for x in arr(component.get("rules", []))]
    identifier = agreed(result, "ruleId", reference, "id")
    index = agreed(result, "ruleIndex", reference, "index")
    if "ruleId" in result or "id" in reference:
        string(identifier)
    if "ruleIndex" in result or "index" in reference:
        require(type(index) is int)
    rule = None
    if index is not None:
        rule = rules[idx(index, len(rules))]
    if "guid" in reference:
        guid = string(reference["guid"])
        matches = [x for x in rules if x.get("guid") == guid]
        require(len(matches) == 1)
        if rule is not None:
            require(matches[0] is rule)
        rule = matches[0]
    if identifier is not None:
        require(bool(IDENTIFIER.fullmatch(string(identifier))))
        if rule is None:
            matches = [x for x in rules if x.get("id") == identifier]
            require(len(matches) == 1)
            rule = matches[0]
        require(rule.get("id") == identifier)
    require(rule is not None and bool(IDENTIFIER.fullmatch(string(rule.get("id")))))
    return component, rule


def invocation(value: Any) -> None:
    value = obj(value)
    require(type(value.get("executionSuccessful")) is bool and value["executionSuccessful"])
    for field in ["toolExecutionNotifications", "toolConfigurationNotifications"]:
        for notification in arr(value.get(field, [])):
            level = obj(notification).get("level", "warning")
            require(isinstance(level, str) and level in LEVELS and level != "error")


@dataclass
class Finding:
    run: dict
    result: dict
    component: dict
    rule: dict
    score: float
    level: str
    blocking: bool


def classify_document(data: dict) -> list[Finding]:
    require(data.get("version") == "2.1.0")
    runs = arr(data.get("runs"))
    require(bool(runs))
    findings = []
    for run in runs:
        run = obj(run)
        tool = obj(run.get("tool"))
        driver = obj(tool.get("driver"))
        require(driver.get("name") == "CodeQL")
        for component in [driver, *arr(tool.get("extensions", []))]:
            component = obj(component)
            string(component.get("name"))
            for rule in arr(component.get("rules", [])):
                obj(rule)
        for item in arr(run.get("invocations", [])):
            invocation(item)
        conversion = obj(run.get("conversion", {}))
        if "invocation" in conversion:
            invocation(conversion["invocation"])
        for result in arr(run.get("results")):
            result = obj(result)
            component, rule = resolve_rule(run, result)
            properties = obj(rule.get("properties", {}))
            tags = arr(properties.get("tags", []))
            require(all(isinstance(x, str) for x in tags))
            require("security" not in tags or "security-severity" in properties)
            raw_score = properties.get("security-severity", 0)
            require(type(raw_score) in {str, int, float})
            try:
                score = float(raw_score)
            except (ValueError, OverflowError):
                raise Invalid("Invalid score") from None
            require(math.isfinite(score) and 0 <= score <= 10)
            default = obj(rule.get("defaultConfiguration", {})).get("level", "warning")
            require(isinstance(default, str) and default in LEVELS)
            level = result.get("level", default)
            require(isinstance(level, str) and level in LEVELS)
            findings.append(
                Finding(run, result, component, rule, score, level, score >= 7 or level == "error")
            )
    return findings


def repo_path(value: Any) -> str:
    value = string(value)
    path = PurePosixPath(value)
    require(not path.is_absolute() and value == path.as_posix())
    require(not any(part in {"", ".", ".."} for part in value.split("/")))
    require(
        not any(c in value for c in "\\%:#?\x00")
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )
    return value


def identity(component: dict) -> dict:
    version = component.get("semanticVersion", component.get("version"))
    string(version)
    for key in ["name", "version", "semanticVersion", "guid"]:
        if key in component:
            string(component[key])
    return {
        key: component[key]
        for key in ["name", "version", "semanticVersion", "guid"]
        if key in component
    }


class Canonicalizer:
    """Only the CodeQL location shapes exercised by real saved outputs are supported."""

    def __init__(self, run: dict, tree):
        self.run, self.tree = run, tree
        self.sources: dict[str, dict] = {}

    def uri(self, value: dict, resolving=False) -> str:
        value = obj(value)
        require(not (set(value) - {"uri", "uriBaseId", "index", "description"}))
        path = None
        if "uri" in value:
            uri = string(value["uri"])
            if "uriBaseId" in value:
                require(value["uriBaseId"] == "%SRCROOT%")
                base = obj(obj(self.run.get("originalUriBaseIds", {})).get("%SRCROOT%"))
                require(base == {"uri": self.tree.root_uri})
            path = repo_path(uri)
        if "index" in value:
            require(not resolving)
            artifacts = arr(self.run.get("artifacts", []))
            location = dict(
                obj(obj(artifacts[idx(value["index"], len(artifacts))]).get("location"))
            )
            if "index" in location:
                require(type(location["index"]) is int and location["index"] == value["index"])
                location.pop("index")
            indexed = self.uri(location, resolving=True)
            if path is not None:
                require(path == indexed)
            path = indexed
        require(path is not None)
        return path

    def region(self, path: str, value: dict) -> dict:
        value = obj(value)
        require(
            not (
                set(value)
                - {"startLine", "endLine", "startColumn", "endColumn", "snippet", "message"}
            )
        )
        binding = self.tree.bind_region(path, value, self.run.get("columnKind", "utf16CodeUnits"))
        source = self.sources.setdefault(
            path, {"path": path, "mode": binding["mode"], "sha256": binding["sha256"], "spans": []}
        )
        span = {
            "column_kind": self.run.get("columnKind", "utf16CodeUnits"),
            "region": {k: v for k, v in value.items() if k not in {"snippet", "message"}},
            "line_sha256": binding["line_sha256"],
        }
        if span not in source["spans"]:
            source["spans"].append(span)
        return dict(value)  # The whole region, including snippet/message, is hashed only.

    def location(self, value: dict) -> dict:
        value = obj(value)
        require(not (set(value) - {"id", "message", "physicalLocation"}))
        physical = obj(value.get("physicalLocation"))
        require(not (set(physical) - {"artifactLocation", "region", "contextRegion"}))
        path = self.uri(physical.get("artifactLocation"))
        output = {key: child for key, child in value.items() if key != "physicalLocation"}
        output["physicalLocation"] = {
            "path": path,
            "region": self.region(path, physical.get("region")),
        }
        if "contextRegion" in physical:
            output["physicalLocation"]["contextRegion"] = self.region(
                path, physical["contextRegion"]
            )
        return output

    def thread_location(self, value: dict) -> dict:
        value = obj(value)
        require(
            not (
                set(value)
                - {
                    "index",
                    "location",
                    "state",
                    "executionOrder",
                    "importance",
                    "nestingLevel",
                    "kinds",
                }
            )
        )
        output = dict(value)
        if "index" in value:
            records = arr(self.run.get("threadFlowLocations", []))
            referenced = dict(obj(records[idx(value["index"], len(records))]))
            require("index" not in referenced)
            referenced = self.thread_location(referenced)
            direct = dict(value)
            direct.pop("index")
            if direct:
                direct = self.thread_location(direct)
                require(
                    all(
                        key in referenced and referenced[key] == child
                        for key, child in direct.items()
                    )
                )
            return referenced
        output["location"] = self.location(value.get("location"))
        return output

    def result(self, value: dict) -> dict:
        allowed = {
            "rule",
            "ruleId",
            "ruleIndex",
            "level",
            "kind",
            "message",
            "locations",
            "relatedLocations",
            "codeFlows",
            "partialFingerprints",
            "fingerprints",
            "properties",
            "correlationGuid",
            "suppressions",
            "baselineState",
        }
        require(not (set(value) - allowed))
        props = obj(value.get("properties", {}))
        require(not (set(props) - {"github/alertNumber", "github/alertUrl"}))
        output = {
            key: child
            for key, child in value.items()
            if key
            not in {
                "rule",
                "ruleId",
                "ruleIndex",
                "locations",
                "relatedLocations",
                "codeFlows",
                "correlationGuid",
                "properties",
            }
        }
        primary = arr(value.get("locations"))
        require(len(primary) == 1)
        output["locations"] = [self.location(x) for x in primary]
        output["relatedLocations"] = [
            self.location(x) for x in arr(value.get("relatedLocations", []))
        ]
        flows = []
        for flow in arr(value.get("codeFlows", [])):
            flow = obj(flow)
            require(not (set(flow) - {"threadFlows", "message"}))
            copy = dict(flow)
            threads = []
            for thread in arr(flow.get("threadFlows")):
                thread = obj(thread)
                require(
                    not (
                        set(thread)
                        - {"id", "locations", "message", "initialState", "immutableState"}
                    )
                )
                item = dict(thread)
                item["locations"] = [self.thread_location(x) for x in arr(thread.get("locations"))]
                threads.append(item)
            copy["threadFlows"] = threads
            flows.append(copy)
        output["codeFlows"] = flows
        return output


def proof(finding: Finding, tree, language: str, context: str) -> dict:
    """Build inactive review material only; this never creates an approval."""
    require(language in LANGUAGES and finding.blocking)
    require(finding.rule["id"].startswith("py/" if language == "python" else "js/"))
    canonicalizer = Canonicalizer(finding.run, tree)
    try:
        canonical = canonicalizer.result(finding.result)
        tool = obj(finding.run["tool"])
        tool_identity = {
            "driver": identity(obj(tool["driver"])),
            "extensions": [identity(obj(x)) for x in arr(tool.get("extensions", []))],
        }
        sources = sorted(canonicalizer.sources.values(), key=lambda x: x["path"])
        for source in sources:
            source["spans"].sort(key=lambda x: json.dumps(x, sort_keys=True))
        return {
            "language": language,
            "rule_id": finding.rule["id"],
            "context_sha256": context,
            "tool_sha256": digest(tool_identity),
            "run_configuration_sha256": digest(finding.run.get("properties", {})),
            "rule_sha256": digest(
                {
                    "component": identity(finding.component),
                    "descriptor": finding.rule,
                    "score": finding.score,
                    "level": finding.level,
                }
            ),
            "finding_sha256": digest(canonical),
            "sources": sources,
        }
    except (Invalid, KeyError, TypeError, UnicodeError, OSError):
        raise Unallowable("Unsupported exact-allowance source profile") from None


PROOF_KEYS = {
    "language",
    "rule_id",
    "context_sha256",
    "tool_sha256",
    "run_configuration_sha256",
    "rule_sha256",
    "finding_sha256",
    "sources",
}
ENTRY_KEYS = {"id", "rationale", "disposition", "reviewed_revision", "max_occurrences", "proof"}


def validate_entries(manifest: dict, tree, language: str, context: str) -> list[dict]:
    require(
        set(manifest) == {"schema", "context_policy", "entries"}
        and type(manifest["schema"]) is int
        and manifest["schema"] == 1
    )
    require(
        manifest["context_policy"] == "whole-tree-v1"
        or isinstance(manifest["context_policy"], dict)
        and manifest["context_policy"].get("mode") == "typed-catalog-v1"
    )
    entries = arr(manifest["entries"])
    ids, signatures, selected = set(), set(), []
    for entry in entries:
        entry = obj(entry)
        require(set(entry) == ENTRY_KEYS)
        eid = string(entry["id"])
        require(bool(IDENTIFIER.fullmatch(eid)) and eid not in ids)
        ids.add(eid)
        require(entry["disposition"] in {"false-positive", "accepted-risk"})
        require(isinstance(entry["rationale"], str) and 1 <= len(entry["rationale"]) <= 1000)
        require(
            isinstance(entry["reviewed_revision"], str)
            and re.fullmatch(r"[0-9a-f]{40}", entry["reviewed_revision"])
        )
        require(type(entry["max_occurrences"]) is int and entry["max_occurrences"] == 1)
        candidate = obj(entry["proof"])
        require(set(candidate) == PROOF_KEYS)
        require(
            candidate["language"] in LANGUAGES
            and bool(IDENTIFIER.fullmatch(string(candidate["rule_id"])))
        )
        for key in PROOF_KEYS - {"language", "rule_id", "sources"}:
            require(bool(HEX.fullmatch(string(candidate[key]))))
        signature = digest(candidate)
        require(signature not in signatures)
        signatures.add(signature)
        if candidate["language"] != language:
            continue
        require(candidate["context_sha256"] == context)
        paths = set()
        for source in arr(candidate["sources"]):
            source = obj(source)
            require(set(source) == {"path", "mode", "sha256", "spans"})
            path = repo_path(source["path"])
            require(path not in paths)
            paths.add(path)
            require(
                source["mode"] in {"100644", "100755"}
                and bool(HEX.fullmatch(string(source["sha256"])))
            )
            spans = arr(source["spans"])
            require(bool(spans))
            for span in spans:
                span = obj(span)
                require(set(span) == {"region", "line_sha256", "column_kind"})
                binding = tree.bind_region(path, obj(span["region"]), span["column_kind"])
                require(
                    binding["mode"] == source["mode"]
                    and binding["sha256"] == source["sha256"]
                    and binding["line_sha256"] == span["line_sha256"]
                )
        require(bool(paths))
        selected.append(entry)
    return selected


def evaluate(documents: list[dict], tree, manifest: dict, language: str) -> dict:
    require(language in LANGUAGES and bool(documents))
    if manifest.get("context_policy") == "whole-tree-v1":
        context = tree.context_digest(MANIFEST_PATH)
    else:
        from security_catalog import context_digest

        context = context_digest(tree, manifest.get("context_policy"))
    entries = validate_entries(manifest, tree, language, context)
    available = {digest(row["proof"]): row for row in entries}
    used = set()
    blocked = allowed = raw_results = 0
    rules = set()
    for document in documents:
        for finding in classify_document(document):
            raw_results += 1
            if not finding.blocking:
                continue
            rules.add(finding.rule["id"])
            try:
                signature = digest(proof(finding, tree, language, context))
            except Unallowable:
                blocked += 1
                continue
            if signature in available and signature not in used:
                used.add(signature)
                allowed += 1
            else:
                blocked += 1
    require(len(used) == len(available))  # Stale/unused entries for this language fail closed.
    return {
        "raw_results": raw_results,
        "blocking": blocked,
        "allowed": allowed,
        "raw_blocking": blocked + allowed,
        "rule_ids": sorted(rules),
        "context_sha256": context,
    }
