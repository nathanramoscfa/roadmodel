"""Deterministically extract Codex's reasoning-effort vocabulary from the
official Codex configuration-reference docs.

This is the Codex analog of ``update/extract_claude_code_effort.py``. It is the
*docs* half of the Codex surface-parameter tracker. It fetches the clean
Markdown endpoint ``https://developers.openai.com/codex/config-reference.md``,
isolates ONLY the four in-scope reasoning/verbosity config keys, and parses out
the canonical vocabularies with plain string/regex parsing — **no LLM call**.

Unlike Claude Code's model-config docs, the Codex config keys live inside a
JSX/MDX ``<ConfigTable options={[ {key,type,description}, ... ]}>`` component
(NOT a Markdown table), so the parser walks the JS object literals rather than
table rows. The four in-scope keys (everything else in the ConfigTable — model
catalogs, providers, hooks, telemetry — is OUT OF SCOPE):

- ``model_reasoning_effort``     : ``minimal | low | medium | high | xhigh``
- ``plan_mode_reasoning_effort`` : ``none | minimal | low | medium | high | xhigh``
- ``model_reasoning_summary``    : ``auto | concise | detailed | none``
- ``model_verbosity``            : ``low | medium | high``

There is NO clean per-model reasoning matrix in the Codex docs (unlike Claude
Code's per-model effort table); the docs only state that ``xhigh`` is
"model-dependent". So the snapshot records the VOCABULARY, and the offline
conformance gate verifies a vocabulary subset, not a per-model support matrix.

The result is written as a JSON snapshot. The committed copy
(``update/codex-reasoning.json``) is the OFFLINE source of truth for
``update/validate_effort_conformance.py``'s Codex check — it lets the per-PR
conformance gate run with no network. The recorded ``section_sha256`` over the
in-scope span drives the docs-freshness cron's change detection (T2), and an
ephemeral mirror under ``update/.cache/codex-reasoning.json`` (gitignored) is
written for that hash comparison.

Exit codes: 0 ok, 3 fetch/read failure, 4 extraction failure (the docs were
restructured so the deterministic parse no longer finds what it expects —
intentionally loud so the cron surfaces it rather than shipping a silently
wrong snapshot).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "codex-reasoning.json"
# The exact span of the docs the snapshot was parsed from, committed beside it
# so a test can re-derive the snapshot offline. A hand-cut fixture cannot play
# that role: it goes stale the first time the docs change, and every Codex
# refresh PR then fails the check until someone re-cuts it by hand (#693).
DEFAULT_SLICE = UPDATE_DIR / "codex-reasoning-source.md"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "codex-reasoning.json"

DOCS_URL = "https://developers.openai.com/codex/config-reference.md"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# The in-scope span is the contiguous block of the four reasoning/verbosity
# config-key objects inside the ``## config.toml`` ConfigTable, delimited by the
# first key (model_reasoning_effort) and the last key (model_verbosity). Hashing
# / parsing only this span — not the whole 67 KB page — lets the docs-freshness
# cron detect reasoning-vocabulary changes (via section_sha256) without firing
# on unrelated config-key edits.
SPAN_START_KEY = "model_reasoning_effort"
SPAN_END_KEY = "model_verbosity"

# The four in-scope config keys whose ``type`` enumerations this tracker owns.
# A snapshot is only emitted when all four parse; a missing key means the docs
# were restructured (fail loud rather than ship a partial snapshot).
REASONING_EFFORT_KEY = "model_reasoning_effort"
PLAN_MODE_KEY = "plan_mode_reasoning_effort"
SUMMARY_KEY = "model_reasoning_summary"
VERBOSITY_KEY = "model_verbosity"
IN_SCOPE_KEYS = (REASONING_EFFORT_KEY, PLAN_MODE_KEY, SUMMARY_KEY, VERBOSITY_KEY)

# Sentinel substrings that MUST survive in the in-scope span. Their absence
# means the docs were restructured and the deterministic parse can no longer be
# trusted — fail loudly instead of emitting a partial snapshot.
REQUIRED_ANCHORS = (
    "model_reasoning_effort",
    "plan_mode_reasoning_effort",
    "model_reasoning_summary",
    "model_verbosity",
)

# The reasoning-effort enumeration this tracker has seen. A documented value
# outside this baseline is FLAGGED (recorded in ``unexpected_effort_values``)
# so a docs-added reasoning tier surfaces rather than being silently absorbed.
# `max` and `ultra` joined on 2026-09-23 (#693), once the selector mapped them
# and check D enforced it; `minimal` stays so an older docs slice still parses.
KNOWN_EFFORT_VALUES = frozenset({"minimal", "low", "medium", "high", "xhigh", "max", "ultra"})


class ExtractError(RuntimeError):
    """The docs no longer match the structure this parser expects."""


def fetch_markdown(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain, text/markdown, */*",
        },
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def isolate_in_scope(markdown: str) -> str:
    """Return only the contiguous span of the four in-scope config-key objects.

    The span runs from the ``{`` that opens the ``model_reasoning_effort`` entry
    through the ``}`` that closes the ``model_verbosity`` entry. Reused by the
    docs-freshness cron so the gate and the snapshot agree on exactly which span
    counts.
    """
    start_key = f'key: "{SPAN_START_KEY}"'
    end_key = f'key: "{SPAN_END_KEY}"'
    start_key_idx = markdown.find(start_key)
    if start_key_idx < 0:
        raise ExtractError(f"in-scope start key not found: {start_key!r}")
    end_key_idx = markdown.find(end_key)
    if end_key_idx < 0:
        raise ExtractError(f"in-scope end key not found: {end_key!r}")
    if end_key_idx < start_key_idx:
        raise ExtractError(
            "in-scope keys are out of order (docs reordered the config table?): "
            f"{SPAN_END_KEY!r} precedes {SPAN_START_KEY!r}"
        )
    open_brace = markdown.rfind("{", 0, start_key_idx)
    if open_brace < 0:
        raise ExtractError(f"object opening brace before {start_key!r} not found")
    close_brace = markdown.find("}", end_key_idx)
    if close_brace < 0:
        raise ExtractError(f"object closing brace after {end_key!r} not found")
    return markdown[open_brace : close_brace + 1]


def verify_anchors(in_scope: str) -> None:
    missing = [a for a in REQUIRED_ANCHORS if a not in in_scope]
    if missing:
        raise ExtractError(f"expected docs anchors missing (restructure?): {missing}")


# A lowercase single-word value, as the docs write them in backticks.
_VALUE_TOKEN_RE = re.compile(r"`([a-z]+)`")


def parse_type_enum(in_scope: str, key: str, *, inherit: list[str] | None = None) -> list[str]:
    """Parse a config key's vocabulary into a token list.

    Two shapes are in the wild, and the docs moved between them without notice:

    - ``type: "a | b | c"`` — the vocabulary IS the type (the original shape,
      still used by ``model_reasoning_summary`` / ``model_verbosity``).
    - ``type: "string"`` — the vocabulary moved into the description's prose.
      OpenAI switched ``model_reasoning_effort`` to this on 2026-09-22: its
      description now reads *"such as `low`, `medium`, `high`, `xhigh`, `max`,
      or `ultra`"*. Reading the bare ``type`` there yields ``["string"]`` —
      a type name, not a value — which is what broke the daily cron.

    A ``string`` key whose description names no values at all
    (``plan_mode_reasoning_effort``: *"using a level supported by the selected
    model"*) defers to another key's vocabulary; pass that as ``inherit``.
    Anything else still fails loud — never guess a vocabulary.
    """
    m = re.search(
        rf'key:\s*"{re.escape(key)}"\s*,\s*type:\s*"([^"]*)"'
        rf'(?:\s*,\s*description:\s*"((?:[^"\\]|\\.)*)")?',
        in_scope,
        re.DOTALL,
    )
    if not m:
        raise ExtractError(f"could not parse type enumeration for key {key!r}")
    type_str, description = m.group(1).strip(), m.group(2) or ""

    if type_str.lower() == "string":
        tokens = list(dict.fromkeys(_VALUE_TOKEN_RE.findall(description)))
        if tokens:
            return tokens
        if inherit:
            return list(inherit)
        raise ExtractError(
            f"key {key!r} is typed `string` and its description names no values "
            f"(and no vocabulary to inherit) — the docs changed shape again"
        )

    tokens = [tok.strip().lower() for tok in type_str.split("|")]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise ExtractError(f"type enumeration for key {key!r} parsed empty")
    return tokens


def section_sha256(in_scope: str) -> str:
    return hashlib.sha256(in_scope.encode("utf-8")).hexdigest()


def build_snapshot(markdown: str, *, source_url: str) -> dict[str, object]:
    in_scope = isolate_in_scope(markdown)
    verify_anchors(in_scope)

    reasoning_effort = parse_type_enum(in_scope, REASONING_EFFORT_KEY)
    # Plan mode takes "a level supported by the selected model" — the same set.
    plan_mode = parse_type_enum(in_scope, PLAN_MODE_KEY, inherit=reasoning_effort)
    summary = parse_type_enum(in_scope, SUMMARY_KEY)
    verbosity = parse_type_enum(in_scope, VERBOSITY_KEY)

    # FLAG (never act on) a reasoning value the docs introduce that this tracker
    # hasn't seen — a new reasoning tier is worth a maintainer's eyes (and may
    # need a new THINKING-field mapping in the selector).
    unexpected = sorted(set(reasoning_effort) - KNOWN_EFFORT_VALUES)
    if unexpected:
        print(
            f"extract_codex_reasoning: NOTE unexpected reasoning-effort value(s) "
            f"not in the known baseline: {unexpected}. A new reasoning tier may "
            f"need a THINKING-field mapping in the selector — flag for review.",
            file=sys.stderr,
        )

    # The docs note "xhigh is model-dependent" on model_reasoning_effort; record
    # it so a future per-model gate (if the docs ever publish a matrix) can pick
    # it up. Today it is informational only.
    xhigh_model_dependent = "xhigh` is model-dependent" in in_scope or (
        "xhigh" in in_scope and "model-dependent" in in_scope
    )

    return {
        "_comment": (
            "Canonical Codex reasoning-effort vocabulary extracted from the "
            "official Codex config-reference docs. Generated by "
            "update/extract_codex_reasoning.py — do not hand-edit; refresh by "
            "running that script. Consumed OFFLINE by "
            "update/validate_effort_conformance.py (Codex check)."
        ),
        "source_url": source_url,
        "in_scope_keys": list(IN_SCOPE_KEYS),
        "reasoning_effort": reasoning_effort,
        "plan_mode_reasoning_effort": plan_mode,
        "model_reasoning_summary": summary,
        "model_verbosity": verbosity,
        "xhigh_model_dependent": xhigh_model_dependent,
        "unexpected_effort_values": unexpected,
        "section_sha256": section_sha256(in_scope),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Codex reasoning-effort vocabulary from the docs."
    )
    parser.add_argument("--url", default=DOCS_URL, help="docs .md endpoint to fetch")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read Markdown from a local file instead of fetching (for tests)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="where to write the JSON snapshot (default: committed canonical copy)",
    )
    parser.add_argument(
        "--slice-output",
        type=Path,
        default=None,
        help=(
            "where to write the docs span the snapshot was parsed from "
            f"(default: {DEFAULT_SLICE.name} beside the canonical snapshot; "
            "none for any other --output)"
        ),
    )
    args = parser.parse_args()
    slice_out = args.slice_output
    if slice_out is None and args.output.resolve() == DEFAULT_OUTPUT.resolve():
        slice_out = DEFAULT_SLICE

    try:
        markdown = args.input.read_text() if args.input else fetch_markdown(args.url)
    except Exception as exc:
        print(f"extract_codex_reasoning: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(markdown, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_codex_reasoning: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if slice_out is not None:
        # isolate_in_scope() of this span is the span itself, so the snapshot
        # (hash included) re-derives from it byte for byte.
        slice_out.parent.mkdir(parents=True, exist_ok=True)
        slice_out.write_text(isolate_in_scope(markdown) + "\n")
    # Mirror an ephemeral copy for the cron's hash comparison (gitignored).
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    effort = snapshot["reasoning_effort"]
    summary = ", ".join(effort) if isinstance(effort, list) else str(effort)
    print(f"extract_codex_reasoning: wrote {args.output} (reasoning_effort: {summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
