"""Offline, provider-aware conformance gate: the selector's effort / thinking /
reasoning vocabulary must stay a subset of — and consistent with — the official
docs of the surfaces it describes (Claude Code's model-config docs and Codex's
config-reference docs).

Why this exists: a bundled artifact (``docs/model-selector.txt``) and the
contracts it must honor (Claude Code's documented effort levels, Codex's
documented reasoning-effort values) can drift independently and invisibly until
a release boundary. This check materializes those contracts as a hard CI gate so
the app never recommends an Effort / reasoning level the docs don't sanction. It
reads COMMITTED files and makes NO network call (the per-PR ``test`` job has no
network) — the canonical docs facts come from ``update/claude-code-effort.json``
(refreshed by ``update/extract_claude_code_effort.py``) and
``update/codex-reasoning.json`` (refreshed by
``update/extract_codex_reasoning.py``).

Four hard checks:

  A. Effort-vocabulary subset (Claude Code). Every effort-bearing value the
     selector's ``THINKING`` field can emit (i.e. excluding the control states
     ``Off`` / ``N/A``) must, normalized, be a documented Claude Code effort
     level.
  B. Per-model effort support (Claude Code). Where the selector AFFIRMATIVELY
     ties a specific Claude model to an effort level (within a short span in the
     Claude Code blocks, and not a negation/fallback statement), that level must
     appear in that model's documented row — e.g. ``xhigh`` on Sonnet 4.6 is a
     violation (Sonnet 4.6 supports only low/medium/high/max). The effort-token
     vocabulary is taken from the snapshot, so a docs-added level is covered.
  C. ultracode vs ultrathink not conflated (Claude Code). ``ultracode`` must be
     described as a SESSION setting (sends ``xhigh`` + orchestrates workflows);
     ``ultrathink`` as a PER-TURN prompt keyword that does not change session
     effort. Neither may be described with the other's semantics.
  D. Codex reasoning-effort vocabulary (Codex/OpenAI). The reasoning values the
     selector enumerates for OpenAI/Codex — both on the ``reasoning-effort
     knob`` bullet of ``<thinking-context>`` and in its OpenAI → THINKING output
     mapping — must EQUAL the documented Codex ``model_reasoning_effort`` set
     (``minimal | low | medium | high | xhigh``): no undocumented reasoning
     value (subset) and no documented value left unencoded (completeness). The
     UI synonym ``extra-high`` is treated as ``xhigh``. Codex publishes no
     per-model reasoning matrix, so this is a pure vocabulary check.

Exit codes: 0 PASS, 1 conformance failure, 2 input/config error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

UPDATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = UPDATE_DIR.parent
DEFAULT_SNAPSHOT = UPDATE_DIR / "claude-code-effort.json"
DEFAULT_CODEX_SNAPSHOT = UPDATE_DIR / "codex-reasoning.json"
DEFAULT_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"

# Snapshot keys the gate depends on. A snapshot missing any of these is a
# config error (fail closed) rather than a silent partial check.
REQUIRED_SNAPSHOT_KEYS = ("effort_levels", "per_model_effort", "ultracode", "ultrathink")
# The Codex snapshot key the provider-aware check D depends on.
REQUIRED_CODEX_SNAPSHOT_KEYS = ("reasoning_effort",)

# UI / label synonyms that denote a documented Codex config reasoning value.
# The selector writes "Extra High" / ``extra-high`` for the ``xhigh`` config
# token (the Intelligence "Extra High" tier); normalize it so the vocabulary
# check compares config tokens to config tokens.
CODEX_REASONING_SYNONYMS = {"extra-high": "xhigh", "extrahigh": "xhigh"}

# THINKING values that are NOT effort levels (exempt from the subset check):
# thinking disabled, and surface-does-not-expose.
THINKING_CONTROL_STATES = {"off", "n/a"}

# Fallback effort vocabulary if the snapshot somehow lacks effort_levels.
FALLBACK_EFFORT_TOKENS = ("low", "medium", "high", "xhigh", "max")

# The Claude-Code-relevant blocks of the selector. Effort/thinking decisions,
# the ultracode/ultrathink prose, and the Claude Code access method all live
# here; scoping to these avoids false positives from model-name/price text
# elsewhere in the file.
THINKING_BLOCK = "thinking-context"
ORCHESTRATION_BLOCK = "orchestration-context"

PER_TURN_MARKERS = (
    "per-turn",
    "per turn",
    "that turn",
    "this turn",
    "single turn",
    "one turn",
    "one-off",
    "single prompt",
    "per prompt",
    "per-prompt",
)
EFFORT_NEUTRAL_MARKERS = (
    "does not change",
    "without changing",
    "not change the session",
    "effort level unchanged",
    "does not alter",
    "leaves the session",
    "untouched",
    "unchanged",
    "no effect on",
    "stays the same",
    "remains the same",
)
# Phrasings that affirmatively cast something as a session-scoped SETTING.
# Deliberately excludes "session effort", which appears in the CORRECT negated
# "does not change the session effort level" statement.
CONFLATION_SESSION_PHRASES = (
    "session setting",
    "session-wide",
    "whole session",
    "is a session",
    "session-scoped",
    "for the session",
    "across the session",
    "entire session",
)
# Cues that flip a co-occurrence from an affirmative tie into a
# negation / fallback / contrast — such a span must NOT be flagged.
NEGATION_CUES = (
    " no ",
    " not ",
    "n't",
    "never",
    "unchanged",
    "untouched",
    "without",
    "does not",
    "do not",
    "rather than",
    "instead of",
    "fall back",
    "falls back",
    "fallback",
    "runs as",
    "at or below",
    "below it",
    "unsupported",
    "only the models",
    "documented row",
    "not a ",
)

COOCCUR_WINDOW = 280  # positive-presence proximity (the framing must be mentioned)
NEG_LOOKBEHIND = 45  # chars before a term scanned for a negation cue


class ConfigError(RuntimeError):
    """An input file was missing or malformed."""


def load_snapshot(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(
            f"docs snapshot not found: {path} — run extract_claude_code_effort.py"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"docs snapshot is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"docs snapshot must be a JSON object: {path}")
    missing = [k for k in REQUIRED_SNAPSHOT_KEYS if k not in data]
    if missing:
        raise ConfigError(f"docs snapshot is missing required keys {missing}: {path}")
    return data


def load_codex_snapshot(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(
            f"codex snapshot not found: {path} — run extract_codex_reasoning.py"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"codex snapshot is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"codex snapshot must be a JSON object: {path}")
    missing = [k for k in REQUIRED_CODEX_SNAPSHOT_KEYS if k not in data]
    if missing:
        raise ConfigError(f"codex snapshot is missing required keys {missing}: {path}")
    return data


def read_selector(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError as exc:
        raise ConfigError(f"selector not found: {path}") from exc


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_block(text: str, tag: str) -> str:
    """Inner text of a real ``<tag> ... </tag>`` element.

    The opening tag is anchored to the start of its own line so an inline
    backtick reference like ``(see `<orchestration-context>`)`` is NOT mistaken
    for the element's opening tag.
    """
    m = re.search(
        rf"^[ \t]*<{tag}>[ \t]*\n(.*?)^[ \t]*</{tag}>[ \t]*$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1) if m else ""


def extract_cc_method(text: str) -> str:
    """The ``<method id="claude-code" ... />`` element.

    The close is anchored to ``/>`` at a line end so a stray ``/>`` inside the
    best-for prose does not truncate the capture.
    """
    m = re.search(
        r'<method id="claude-code".*?/>[ \t]*$',
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


def parse_enum(selector: str, field: str) -> set[str]:
    """Collect the bracketed enum values of an output-format field.

    e.g. ``THINKING: [Off/Low/Medium/High/XHigh/N/A]`` -> the six tokens.
    """
    values: set[str] = set()
    for m in re.finditer(rf"{field}:\s*\[([^\]]+)\]", selector):
        # The enum is slash-delimited, but "N/A" is one token that itself
        # contains a slash — protect it (case-insensitively) before splitting.
        content = re.sub(r"(?i)n/a", "NA", m.group(1))
        for part in content.split("/"):
            part = part.strip()
            if part:
                values.add("N/A" if part == "NA" else part)
    return values


def effort_token_re(documented_levels: list[str]) -> re.Pattern[str]:
    """Word-boundaried alternation over the documented effort levels.

    Built from the snapshot (longest-first) so a docs-added level is covered
    rather than silently un-tokenizable.
    """
    toks = sorted(
        {str(lv).lower() for lv in documented_levels} or set(FALLBACK_EFFORT_TOKENS),
        key=len,
        reverse=True,
    )
    return re.compile(r"\b(" + "|".join(map(re.escape, toks)) + r")\b", re.IGNORECASE)


def cooccur(text: str, a: str, b: str, window: int = COOCCUR_WINDOW) -> bool:
    """True if any occurrence of ``a`` is within ``window`` chars of ``b``.

    Whitespace is collapsed first so a phrase split across the selector's
    hard-wrapped lines (e.g. "does not\\n      change") still matches.
    """
    flat = re.sub(r"\s+", " ", text.lower())
    a_pos = [m.start() for m in re.finditer(re.escape(a.lower()), flat)]
    b_pos = [m.start() for m in re.finditer(re.escape(b.lower()), flat)]
    return any(abs(ai - bi) <= window for ai in a_pos for bi in b_pos)


def split_clauses(flat: str) -> list[str]:
    """Split collapsed text into sentence-ish clauses (on ``.`` / ``;`` / ``:``)
    so a negation or fallback qualifier is scoped to the claim it belongs to,
    not a neighbouring sentence."""
    return re.split(r"(?<=[.;:])\s+", flat)


def statement(blocks: str, keyword: str, limit: int = 500) -> str:
    """The defining statement for ``keyword``: from its first mention to the
    next blank line or list bullet (capped at ``limit`` chars)."""
    low = blocks.lower()
    idx = low.find(keyword.lower())
    if idx < 0:
        return ""
    rest = blocks[idx:]
    m = re.search(r"\n\s*\n|\n\s*-\s", rest[1:])
    end = (m.start() + 1) if m else len(rest)
    return rest[: min(end, limit)]


def affirmative_in(stmt: str, term: str) -> bool:
    """True if ``term`` appears in ``stmt`` without a negation cue immediately
    before it (an affirmative, non-negated mention)."""
    low = stmt.lower()
    for m in re.finditer(re.escape(term.lower()), low):
        ctx = low[max(0, m.start() - NEG_LOOKBEHIND) : m.start()]
        if not any(cue in ctx for cue in NEGATION_CUES):
            return True
    return False


def check_thinking_vocab(selector: str, snapshot: dict[str, object]) -> list[str]:
    """Check A — effort-bearing THINKING values must be documented levels."""
    documented = snapshot.get("effort_levels")
    if not isinstance(documented, list):
        return ["snapshot is missing the 'effort_levels' list"]
    documented_set = {str(lv).lower() for lv in documented}

    thinking_values = parse_enum(selector, "THINKING")
    if not thinking_values:
        return ["could not find a THINKING: [...] enum in the selector"]

    failures: list[str] = []
    for value in sorted(thinking_values):
        norm = value.lower()
        if norm in THINKING_CONTROL_STATES:
            continue
        if norm not in documented_set:
            failures.append(
                f"check A (effort vocabulary): THINKING value {value!r} is not a "
                f"documented Claude Code effort level "
                f"(documented: {sorted(documented_set)})"
            )
    return failures


def check_per_model_effort(selector: str, snapshot: dict[str, object]) -> list[str]:
    """Check B — a model affirmatively tied to an unsupported effort → fail.

    Operates clause by clause on the collapsed Claude Code blocks: a clause that
    names a model alongside an effort token its documented row lacks, and that
    carries no negation/fallback cue, is a violation. Clause scoping keeps a
    negation in a neighbouring sentence from masking a real claim, and keeps a
    real fallback statement ("xhigh runs as high on Opus 4.6") from tripping it.
    The effort-token vocabulary comes from the snapshot, so a docs-added level
    is covered rather than silently un-tokenizable.
    """
    per_model = snapshot.get("per_model_effort")
    if not isinstance(per_model, dict):
        return ["snapshot is missing the 'per_model_effort' map"]
    documented = snapshot.get("effort_levels")
    documented_levels = documented if isinstance(documented, list) else list(FALLBACK_EFFORT_TOKENS)
    token_re = effort_token_re(documented_levels)

    blocks = "\n".join(
        (
            extract_block(selector, THINKING_BLOCK),
            extract_block(selector, ORCHESTRATION_BLOCK),
            extract_cc_method(selector),
        )
    )

    failures: list[str] = []
    seen: set[tuple[str, str]] = set()
    for clause in split_clauses(_collapse(blocks).lower()):
        if any(cue in clause for cue in NEGATION_CUES):
            continue  # a negation / fallback statement, not an affirmative tie
        tokens = {t.lower() for t in token_re.findall(clause)}
        if not tokens:
            continue
        for model in per_model:
            if model.lower() not in clause:
                continue
            supported = {str(lv).lower() for lv in per_model[model]}
            for token in sorted(tokens - supported):
                key = (model, token)
                if key in seen:
                    continue
                seen.add(key)
                failures.append(
                    f"check B (per-model effort): the selector ties {model!r} to "
                    f"effort {token!r}, which is not in its documented row "
                    f"{sorted(supported)}"
                )
    return failures


def check_ultracode_ultrathink(selector: str, snapshot: dict[str, object]) -> list[str]:
    """Check C — ultracode (session) vs ultrathink (per-turn) not conflated."""
    thinking = extract_block(selector, THINKING_BLOCK)
    orchestration = extract_block(selector, ORCHESTRATION_BLOCK)
    blocks = thinking + "\n" + orchestration
    flat = _collapse(blocks).lower()

    ucode = snapshot.get("ultracode")
    ucode = ucode if isinstance(ucode, dict) else {}
    uthink = snapshot.get("ultrathink")
    uthink = uthink if isinstance(uthink, dict) else {}
    failures: list[str] = []

    # --- ultracode: must read as a SESSION setting (xhigh + orchestration) ---
    if "ultracode" not in flat:
        failures.append(
            "check C (ultracode): the selector does not mention ultracode in its Claude Code blocks"
        )
    else:
        if ucode.get("session_only") and not cooccur(flat, "ultracode", "session"):
            failures.append(
                "check C (ultracode): ultracode must be described as a SESSION "
                "setting (the docs say it applies to the current session only)"
            )
        if ucode.get("sends_effort") == "xhigh" and not cooccur(flat, "ultracode", "xhigh"):
            failures.append(
                "check C (ultracode): ultracode must be tied to xhigh effort "
                "(the docs say it sends xhigh to the model)"
            )
        ustmt = _collapse(statement(blocks, "ultracode"))
        if any(affirmative_in(ustmt, m) for m in ("per-turn", "per turn", "that turn")):
            failures.append(
                "check C (conflation): ultracode is described as a per-turn "
                "control — it is a SESSION setting, not a per-turn keyword"
            )

    # --- ultrathink: must read as a PER-TURN keyword that is effort-neutral ---
    if "ultrathink" not in flat:
        failures.append(
            "check C (ultrathink): the selector does not document ultrathink — the "
            "per-turn keyword cannot be distinguished from the ultracode session "
            "setting (see docs anchor #use-ultrathink-for-one-off-deep-reasoning)"
        )
    else:
        tstmt = _collapse(statement(blocks, "ultrathink"))
        tlow = tstmt.lower()
        if uthink.get("is_per_turn_keyword") and not any(m in tlow for m in PER_TURN_MARKERS):
            failures.append(
                "check C (ultrathink): ultrathink must be described as a PER-TURN "
                "prompt keyword (the docs say it affects only that turn)"
            )
        if uthink.get("changes_session_effort") is False and not any(
            m in tlow for m in EFFORT_NEUTRAL_MARKERS
        ):
            failures.append(
                "check C (ultrathink): ultrathink must be described as NOT changing "
                "the session effort level"
            )
        conflated = next((p for p in CONFLATION_SESSION_PHRASES if p in tlow), None)
        if conflated:
            failures.append(
                f"check C (conflation): ultrathink is described with session-setting "
                f"language {conflated!r} — it is a per-turn keyword, not a session "
                f"setting like ultracode"
            )
        if affirmative_in(tstmt, "orchestrat"):
            failures.append(
                "check C (conflation): ultrathink is described as orchestrating "
                "workflows — that is ultracode's behavior, not ultrathink's"
            )
        if affirmative_in(tstmt, "xhigh"):
            failures.append(
                "check C (conflation): ultrathink is tied to xhigh effort — that is "
                "ultracode's behavior; ultrathink does not change session effort"
            )
    return failures


def _normalize_codex_token(token: str) -> str:
    norm = token.strip().lower()
    return CODEX_REASONING_SYNONYMS.get(norm, norm)


def openai_bullet_reasoning_tokens(thinking_flat: str) -> set[str]:
    """Reasoning tokens enumerated on the OpenAI ``reasoning-effort knob`` bullet.

    ``thinking_flat`` is the whitespace-collapsed ``<thinking-context>`` block,
    so the enumeration survives the selector's hard-wrapped lines. The bullet
    uses pure config tokens (e.g. ```minimal``, ``low``, ...``), captured up to
    the sentence-ending period after the knob phrase.
    """
    m = re.search(r"reasoning-effort knob\s*[—–\-]+\s*([^.]*)", thinking_flat)
    if not m:
        return set()
    return {_normalize_codex_token(t) for t in re.findall(r"`([^`]+)`", m.group(1))}


def openai_mapping_reasoning_tokens(thinking_flat: str) -> set[str]:
    """Reasoning tokens on the LEFT of each arrow in the OpenAI output mapping.

    The mapping reads ``OpenAI `minimal` -> `Off`; `low` -> `Low`; ... ->
    `XHigh```. The token immediately before each ``->`` is the provider-native
    reasoning value (the token after is the unified THINKING output state).
    Parenthetical asides — e.g. ``(... e.g. `gpt-5.3-codex-high`)`` — are
    stripped first so a model-id example is not mistaken for a reasoning value.
    """
    m = re.search(r"OpenAI\s+`minimal`(.*?→\s*`XHigh`)", thinking_flat)
    if not m:
        return set()
    seg = "OpenAI `minimal`" + re.sub(r"\([^)]*\)", "", m.group(1))
    tokens: set[str] = set()
    parts = seg.split("→")
    # Each part except the last feeds an arrow; its trailing backtick token is
    # the reasoning value. The final part is the last output state (no arrow).
    for part in parts[:-1]:
        backticks = re.findall(r"`([^`]+)`", part)
        if backticks:
            tokens.add(_normalize_codex_token(backticks[-1]))
    return tokens


def check_codex_reasoning_vocab(selector: str, codex_snapshot: dict[str, object]) -> list[str]:
    """Check D — the selector's Codex/OpenAI reasoning vocabulary EQUALS the
    documented Codex ``model_reasoning_effort`` set (subset + completeness).
    """
    documented_raw = codex_snapshot.get("reasoning_effort")
    if not isinstance(documented_raw, list) or not documented_raw:
        return ["check D (codex reasoning): snapshot is missing the 'reasoning_effort' list"]
    documented = {str(lv).lower() for lv in documented_raw}

    thinking_flat = _collapse(extract_block(selector, THINKING_BLOCK))
    bullet = openai_bullet_reasoning_tokens(thinking_flat)
    mapping = openai_mapping_reasoning_tokens(thinking_flat)

    if not bullet:
        return [
            "check D (codex reasoning): could not find the OpenAI 'reasoning-effort "
            "knob' enumeration in <thinking-context>"
        ]
    if not mapping:
        return [
            "check D (codex reasoning): could not find the OpenAI output mapping "
            "('OpenAI `minimal` -> ... -> `XHigh`') in <thinking-context>"
        ]

    failures: list[str] = []
    # Subset: no reasoning token outside the documented set, in bullet OR mapping.
    for token in sorted((bullet | mapping) - documented):
        failures.append(
            f"check D (codex reasoning): the selector ties Codex/OpenAI to reasoning "
            f"value {token!r}, which is not a documented Codex reasoning-effort value "
            f"({sorted(documented)})"
        )
    # Completeness: every documented reasoning level must be enumerated on the
    # bullet AND mapped to a THINKING output state.
    for token in sorted(documented - bullet):
        failures.append(
            f"check D (codex reasoning): documented Codex reasoning value {token!r} is "
            "missing from the selector's OpenAI 'reasoning-effort knob' enumeration"
        )
    for token in sorted(documented - mapping):
        failures.append(
            f"check D (codex reasoning): documented Codex reasoning value {token!r} is "
            "missing from the selector's OpenAI -> THINKING output mapping"
        )
    return failures


def run_checks(
    selector: str,
    snapshot: dict[str, object],
    codex_snapshot: dict[str, object] | None = None,
) -> list[str]:
    failures: list[str] = []
    failures += check_thinking_vocab(selector, snapshot)
    failures += check_per_model_effort(selector, snapshot)
    failures += check_ultracode_ultrathink(selector, snapshot)
    if codex_snapshot is not None:
        failures += check_codex_reasoning_vocab(selector, codex_snapshot)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Conformance gate: selector effort/thinking vocabulary vs docs."
    )
    parser.add_argument("--selector", type=Path, default=DEFAULT_SELECTOR)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--codex-snapshot", type=Path, default=DEFAULT_CODEX_SNAPSHOT)
    args = parser.parse_args()

    try:
        snapshot = load_snapshot(args.snapshot)
        codex_snapshot = load_codex_snapshot(args.codex_snapshot)
        selector = read_selector(args.selector)
    except ConfigError as exc:
        print(f"validate_effort_conformance: config error: {exc}", file=sys.stderr)
        return 2

    failures = run_checks(selector, snapshot, codex_snapshot)
    if failures:
        print(
            f"validate_effort_conformance: {len(failures)} failure(s):",
            file=sys.stderr,
        )
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    print(
        "validate_effort_conformance: PASS (Claude Code effort vocabulary is a "
        "documented subset; no model tied to an unsupported effort level; ultracode "
        "and ultrathink kept distinct; Codex reasoning vocabulary matches the docs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
