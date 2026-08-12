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

Six hard checks:

  A. Effort-vocabulary subset + THINKING-is-a-toggle (Claude Code). Output
     contract v2 SPLIT the old ``THINKING`` field in two: ``EFFORT`` carries the
     reasoning LEVEL and ``THINKING`` is a two-position On/Off toggle. The gate
     follows the split.
       A1: every effort-bearing value the selector's ``EFFORT`` field can emit
       (i.e. excluding the legacy control states ``Off`` / ``N/A``) must,
       normalized, be a documented Claude Code effort level — plus
       ``Ultracode``, which is licensed ONLY by the snapshot's own ultracode
       facts (see ``ultracode_licensed_as_effort``), never by a hardcoded
       allowance.
       A2: every value the ``THINKING`` field can emit must be control
       vocabulary (``On`` / ``Off``, with ``N/A`` tolerated for v1 blocks). An
       EFFORT WORD in ``THINKING`` is reported by name — ``THINKING: Max`` is
       the exact v1 regression the split exists to prevent, and a cron that
       re-merges the two fields must go red rather than silently ship a
       setting no operator can apply.
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
     selector enumerates for OpenAI/Codex — both on the OpenAI dial bullet of
     ``<thinking-context>`` and in its OpenAI → THINKING output
     mapping — must EQUAL the documented Codex ``model_reasoning_effort`` set
     (``minimal | low | medium | high | xhigh``): no undocumented reasoning
     value (subset) and no documented value left unencoded (completeness). The
     UI synonym ``extra-high`` is treated as ``xhigh``. Codex publishes no
     per-model reasoning matrix, so this is a pure vocabulary check.
  E. Gemini thinking surface (Gemini/Google). Gemini unified its reasoning
     surface onto ONE discrete thinking-level vocabulary (2026-06), spanning the
     3.x and 2.5 generations; the numeric 2.5 ``thinkingBudget`` is no longer
     documented or tracked. E1: the ``thinking-level`` vocabulary the selector
     enumerates must EQUAL the documented ``thinking_levels`` set
     (``low | medium | high``). E2: where the selector affirmatively ties a
     Gemini model to a level its documented row lacks (clause-scoped,
     negation-aware), that is a violation — e.g. Gemini 3 Pro is low/high only.
  F. DeepSeek thinking surface (DeepSeek). DeepSeek exposes ONE reasoning
     surface: a thinking toggle plus a reasoning-effort enum. F1: the effort
     vocabulary the selector enumerates must EQUAL the documented
     ``reasoning_effort`` set (``high | max``) AND the toggle vocabulary must
     EQUAL the documented ``thinking_toggle`` set (``enabled | disabled``) — both
     subset + completeness. F-mapping: the DeepSeek output mapping must hold —
     thinking ``disabled`` -> Off, effort ``high`` -> High, effort ``max`` ->
     XHigh (scoped to the DeepSeek mapping clause, so the OpenAI mapping's own
     ``high`` -> High is not mistaken for it). DeepSeek publishes no per-model
     reasoning matrix, so there is no per-model sub-check.

Locating the provider enumerations (D/E/F): each provider's levels are found by
first isolating its ``- <Provider> ...`` BULLET in ``<thinking-context>``, then
reading the enumeration inside it. Checks D/E/F previously grepped prose phrases
("reasoning-effort knob", "thinking-level knob", "reasoning-effort enum") out of
the whole block — prose written by the same cron Opus pass these checks gate. A
Codex run renamed its bullet to the documented ``reasoning_effort`` spelling, the
anchor stopped matching, and check D failed "could not find the enumeration"
fatally and BEFORE the PR-open step, so every later run retried the same edit and
failed identically (issue #517). Bullet scoping also removes the old need to tell
OpenAI's and DeepSeek's enumerations apart by "knob" vs "enum", which one reword
on either side would have silently collided.

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
DEFAULT_GEMINI_SNAPSHOT = UPDATE_DIR / "gemini-thinking.json"
DEFAULT_DEEPSEEK_SNAPSHOT = UPDATE_DIR / "deepseek-thinking.json"
DEFAULT_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"

# Snapshot keys the gate depends on. A snapshot missing any of these is a
# config error (fail closed) rather than a silent partial check.
REQUIRED_SNAPSHOT_KEYS = ("effort_levels", "per_model_effort", "ultracode", "ultrathink")
# The Codex snapshot key the provider-aware check D depends on.
REQUIRED_CODEX_SNAPSHOT_KEYS = ("reasoning_effort",)
# The Gemini snapshot keys the provider-aware check E depends on.
REQUIRED_GEMINI_SNAPSHOT_KEYS = ("thinking_levels", "per_model_levels")
# The DeepSeek snapshot keys the provider-aware check F depends on.
REQUIRED_DEEPSEEK_SNAPSHOT_KEYS = ("reasoning_effort", "thinking_toggle")

# UI / label synonyms that denote a documented Codex config reasoning value.
# The selector writes "Extra High" / ``extra-high`` for the ``xhigh`` config
# token (the Intelligence "Extra High" tier); normalize it so the vocabulary
# check compares config tokens to config tokens.
CODEX_REASONING_SYNONYMS = {"extra-high": "xhigh", "extrahigh": "xhigh"}

# EFFORT values that are NOT effort levels (exempt from the subset check):
# thinking disabled, and surface-does-not-expose. Output contract v2 carries
# levels ONLY in EFFORT, but a v1-shaped selector folded these two control
# states into the same field, so they stay exempt rather than being reported as
# undocumented effort levels (dual-accept during the v1 -> v2 migration).
EFFORT_CONTROL_STATES = {"off", "n/a"}

# THINKING is a two-position TOGGLE under v2 — these are the ONLY values it may
# carry. ``n/a`` is tolerated because a pre-split (v1) selector spelled
# "this surface exposes no dial" as `N/A` in this same field.
THINKING_TOGGLE_STATES = {"on", "off", "n/a"}

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


def load_gemini_snapshot(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(
            f"gemini snapshot not found: {path} — run extract_gemini_thinking.py"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"gemini snapshot is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"gemini snapshot must be a JSON object: {path}")
    missing = [k for k in REQUIRED_GEMINI_SNAPSHOT_KEYS if k not in data]
    if missing:
        raise ConfigError(f"gemini snapshot is missing required keys {missing}: {path}")
    return data


def load_deepseek_snapshot(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(
            f"deepseek snapshot not found: {path} — run extract_deepseek_thinking.py"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"deepseek snapshot is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"deepseek snapshot must be a JSON object: {path}")
    missing = [k for k in REQUIRED_DEEPSEEK_SNAPSHOT_KEYS if k not in data]
    if missing:
        raise ConfigError(f"deepseek snapshot is missing required keys {missing}: {path}")
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

    e.g. ``THINKING: [Off/Low/Medium/High/XHigh/Max/N/A]`` -> the seven tokens.
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


def ultracode_licensed_as_effort(snapshot: dict[str, object], documented_set: set[str]) -> bool:
    """True when the docs snapshot licenses ``Ultracode`` as an EFFORT value.

    ``Ultracode`` is the TOP value of the v2 EFFORT field, but it is NOT a row
    in the docs' effort-level table — it is the session SETTING set through the
    SAME ``/effort`` command as every level, which is precisely why the output
    contract folds it into EFFORT instead of giving it a control of its own.

    So the acceptance is EVIDENCE-BASED, not a blanket allowance: it holds only
    while the snapshot still records ultracode as a real setting
    (``is_setting``) whose ``sends_effort`` is itself a documented level. If a
    docs change retires ultracode, demotes it from a setting, or reworks what it
    sends, this goes False and an ``Ultracode`` value in the EFFORT enum fails
    check A like any other undocumented token.
    """
    ucode = snapshot.get("ultracode")
    if not isinstance(ucode, dict):
        return False
    if not ucode.get("is_setting"):
        return False
    sends = ucode.get("sends_effort")
    return isinstance(sends, str) and sends.strip().lower() in documented_set


def check_thinking_vocab(selector: str, snapshot: dict[str, object]) -> list[str]:
    """Check A — EFFORT carries documented levels; THINKING carries a toggle.

    A1 validates the EFFORT enum against the documented Claude Code effort
    levels (the field the v1 gate never looked at, so undocumented effort values
    used to pass unseen). A2 validates that THINKING stayed a two-position
    toggle — re-merging an effort word into it is the regression this check
    exists to catch.
    """
    documented = snapshot.get("effort_levels")
    if not isinstance(documented, list):
        return ["snapshot is missing the 'effort_levels' list"]
    documented_set = {str(lv).lower() for lv in documented}
    allowed_effort = set(documented_set)
    if ultracode_licensed_as_effort(snapshot, documented_set):
        allowed_effort.add("ultracode")

    failures: list[str] = []

    # --- A1: the EFFORT enum is the reasoning-level vocabulary ---------------
    effort_values = parse_enum(selector, "EFFORT")
    if not effort_values:
        # Fail closed: a selector with no EFFORT enum is unparseable by this
        # gate, and silently passing it is how a contract regression ships.
        return ["could not find an EFFORT: [...] enum in the selector"]
    for value in sorted(effort_values):
        norm = value.lower()
        if norm in EFFORT_CONTROL_STATES:
            continue
        if norm not in allowed_effort:
            failures.append(
                f"check A (effort vocabulary): EFFORT value {value!r} is not a "
                f"documented Claude Code effort level "
                f"(documented: {sorted(allowed_effort)})"
            )

    # --- A2: THINKING is a toggle, and never carries an effort word ----------
    thinking_values = parse_enum(selector, "THINKING")
    if not thinking_values:
        failures.append("could not find a THINKING: [...] enum in the selector")
        return failures
    for value in sorted(thinking_values):
        norm = value.lower()
        if norm in THINKING_TOGGLE_STATES:
            continue
        if norm in allowed_effort:
            failures.append(
                f"check A (thinking toggle): THINKING value {value!r} is an EFFORT "
                f"level, but THINKING is a two-position toggle "
                f"({sorted(THINKING_TOGGLE_STATES)}) — an effort level belongs in "
                f"EFFORT, and no surface's thinking toggle has a {value!r} position"
            )
        else:
            failures.append(
                f"check A (thinking toggle): THINKING value {value!r} is not a "
                f"documented thinking-toggle state "
                f"(expected one of {sorted(THINKING_TOGGLE_STATES)})"
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


# --------------------------------------------------------------------------- #
# Provider-bullet locators
#
# Checks D/E/F used to find each provider's level enumeration by grepping a
# PROSE PHRASE out of the whole <thinking-context> block — "reasoning-effort
# knob", "thinking-level knob", "reasoning-effort enum". That prose is written
# by the same cron Opus pass these checks gate, so the checks were anchored on
# text their own subject is licensed to rewrite. It happened: the Codex tracker
# renamed its bullet to the documented `reasoning_effort` spelling, the anchor
# stopped matching, and check D failed "could not find the enumeration" —
# fatally, BEFORE the PR-open step, so every subsequent run retried the same
# edit and failed identically. The lane deadlocked (issue #517).
#
# Whole-block phrase matching was also why OpenAI's and DeepSeek's enumerations
# had to be told apart by "knob" vs "enum": a single reword on either side
# would have made them collide silently.
#
# Both problems go away by locating the PROVIDER BULLET structurally first —
# list items in <thinking-context> are `- <Provider> (<surfaces>): ...` — and
# only then looking for the enumeration inside that one bullet. Phrase matching
# is kept as the precise path but widened to a family, and a structural
# fallback takes over when no phrase matches, so a future reword degrades to
# "slightly less precise" instead of "lane stops".
# --------------------------------------------------------------------------- #

# Noun the provider bullets have used, or plausibly will, for the dial itself.
_DIAL_NOUN = r"(?:knob|enum|control|dial|setting|parameter|selector|values?|levels?|tiers?)"

# "reasoning-effort knob", "`reasoning_effort` knob", "reasoning effort values"...
# The optional backticks matter: the reword that deadlocked the lane wrapped the
# dial name in them, and consuming the closing backtick keeps the enumeration's
# own backtick pairs aligned. Without it the parser reads the CLOSING backtick of
# the dial as an OPENING one and every token after it is off by one.
REASONING_DIAL_RE = rf"`?reasoning[-_ ]effort`?(?:\s+{_DIAL_NOUN})?"
# "thinking-level knob", "thinking levels", "`thinking_level` setting", ...
THINKING_DIAL_RE = rf"`?thinking[-_ ]level(?:s)?`?(?:\s+{_DIAL_NOUN})?"

# A level token is a short lowercase identifier — `minimal`, `xhigh`, `max`.
# Used by the structural fallback to tell an enumeration apart from incidental
# backticked prose like `MAX_THINKING_TOKENS=0` or `gpt-5.3-codex-high`.
_LEVEL_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{1,12}$")


def provider_bullets(thinking_flat: str, provider: str) -> list[str]:
    """Every ``- <Provider> ...`` bullet in ``<thinking-context>``.

    ``thinking_flat`` is the whitespace-collapsed block, so bullets read
    ``- OpenAI (Codex, ...): ...`` separated by ``" - "``. A provider appears in
    TWO lists — the dial descriptions and the output mappings — so this returns
    all of them and the callers pick by shape.
    """
    parts = re.split(r"(?:^|\s)-\s+(?=[A-Z])", thinking_flat)
    out: list[str] = []
    for part in parts:
        # The provider name leads the bullet, before the surface list or the
        # first mapped value; cap the window so a later mention of another
        # provider inside the prose cannot claim the bullet.
        head = re.split(r"[:`]", part, maxsplit=1)[0][:80].lower()
        if re.search(rf"\b{re.escape(provider.lower())}\b", head):
            out.append(part)
    return out


def provider_bullet(thinking_flat: str, provider: str) -> str:
    """The provider's DIAL bullet — the one describing its levels, not mapping them.

    Returns "" when the provider has no bullet, which callers report as a real
    failure: a missing provider bullet IS a conformance problem, unlike a
    reworded phrase inside one.
    """
    bullets = provider_bullets(thinking_flat, provider)
    # The mapping bullets are the ones carrying arrows; the dial bullet is not.
    for bullet in bullets:
        if "→" not in bullet and "->" not in bullet:
            return bullet
    return bullets[0] if bullets else ""


def mapping_bullet(thinking_flat: str, provider: str) -> str:
    """The provider's OUTPUT-MAPPING bullet — the one carrying ``native → EFFORT``.

    Identified structurally by the presence of arrows rather than by the old
    literal anchor (``OpenAI `minimal` ... → `XHigh```), which hardcoded the
    vocabulary's two endpoints and so broke the moment either end moved.
    """
    for bullet in provider_bullets(thinking_flat, provider):
        if "→" in bullet or "->" in bullet:
            return bullet
    return ""


def _tokens_after(segment: str, stop: str = ".") -> set[str]:
    """Backtick tokens in ``segment`` up to the first ``stop`` character."""
    cut = re.split(rf"[{re.escape(stop)}]", segment, maxsplit=1)[0]
    return {t.strip().lower() for t in re.findall(r"`([^`]+)`", cut)}


def _fallback_enumeration(bullet: str) -> set[str]:
    """First run of >=2 plausible level tokens in a bullet.

    The structural safety net for when no dial phrase matches. Requires at
    least two adjacent level-shaped tokens so a lone backticked word (a default
    value, a config key, a model id) is never mistaken for an enumeration.
    """
    run: list[str] = []
    for tok in re.findall(r"`([^`]+)`", bullet):
        norm = tok.strip().lower()
        if _LEVEL_TOKEN_RE.match(norm):
            run.append(norm)
        elif len(run) >= 2:
            break
        else:
            run = []
    return set(run) if len(run) >= 2 else set()


def enumeration_in_bullet(bullet: str, dial_re: str, stop: str = ".(") -> set[str]:
    """Level tokens enumerated on a provider bullet.

    Precise path: the tokens following the dial phrase, up to the sentence end
    or the first parenthetical caveat. Fallback: the first run of level-shaped
    tokens anywhere in the bullet. Returns an empty set only when the bullet
    carries no enumeration at all.
    """
    if not bullet:
        return set()
    m = re.search(rf"{dial_re}\s*[—–\-:]*\s*(.*)", bullet, re.IGNORECASE)
    if m:
        tokens = _tokens_after(m.group(1), stop)
        if tokens:
            return tokens
    return _fallback_enumeration(bullet)


def openai_bullet_reasoning_tokens(thinking_flat: str) -> set[str]:
    """Reasoning tokens enumerated on the OpenAI ``reasoning-effort knob`` bullet.

    ``thinking_flat`` is the whitespace-collapsed ``<thinking-context>`` block,
    so the enumeration survives the selector's hard-wrapped lines. The bullet
    uses pure config tokens (e.g. ```minimal``, ``low``, ...``), captured up to
    the sentence-ending period after the knob phrase.
    """
    bullet = provider_bullet(thinking_flat, "OpenAI")
    return {
        _normalize_codex_token(t) for t in enumeration_in_bullet(bullet, REASONING_DIAL_RE, ".")
    }


def openai_mapping_reasoning_tokens(thinking_flat: str) -> set[str]:
    """Reasoning tokens on the LEFT of each arrow in the OpenAI output mapping.

    The mapping reads ``OpenAI `minimal` -> `Off`; `low` -> `Low`; ... ->
    `XHigh```. The token immediately before each ``->`` is the provider-native
    reasoning value (the token after is the unified THINKING output state).
    Parenthetical asides — e.g. ``(... e.g. `gpt-5.3-codex-high`)`` — are
    stripped first so a model-id example is not mistaken for a reasoning value.

    The bullet is located structurally (see :func:`mapping_bullet`). The old
    anchor pinned both ends of the vocabulary (``OpenAI `minimal` ... `XHigh```),
    so adding a tier at either end silently emptied this set and the check
    reported "could not find the mapping" instead of the real disagreement.
    """
    seg = mapping_bullet(thinking_flat, "OpenAI")
    if not seg:
        return set()
    seg = re.sub(r"\([^)]*\)", "", seg)
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
            "check D (codex reasoning): no level enumeration found on the OpenAI bullet "
            "in <thinking-context>. The bullet itself is missing or carries no "
            "backticked levels — the dial's WORDING no longer matters (the locator "
            "is the `- OpenAI ...` bullet), so this means real content is absent."
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
            "missing from the selector's OpenAI level enumeration"
        )
    for token in sorted(documented - mapping):
        failures.append(
            f"check D (codex reasoning): documented Codex reasoning value {token!r} is "
            "missing from the selector's OpenAI -> THINKING output mapping"
        )
    return failures


def gemini_level_tokens(thinking_flat: str) -> set[str]:
    """Gemini 3.x thinking-level tokens enumerated on the Gemini bullet.

    The bullet reads "... thinking-level knob - ``minimal``, ``low``, ...";
    capture the backtick tokens up to the first ``.`` or ``(`` (the per-model
    caveat that follows is a parenthetical / new sentence).
    """
    bullet = provider_bullet(thinking_flat, "Gemini")
    return enumeration_in_bullet(bullet, THINKING_DIAL_RE, ".(")


def check_gemini_thinking(selector: str, gemini_snapshot: dict[str, object]) -> list[str]:
    """Check E — the selector's Gemini reasoning description must match the docs.

    Gemini unified its reasoning surface onto discrete levels (2026-06); the
    numeric 2.5 ``thinkingBudget`` is no longer documented, so there is no
    sentinel sub-check.

    E1 (vocabulary): the Gemini thinking-level vocabulary the selector
        enumerates must EQUAL the documented ``thinking_levels`` set.
    E2 (per-model): where the selector affirmatively ties a Gemini model to a
        thinking level its documented row lacks (clause-scoped, negation-aware,
        mirroring check B), that is a violation — e.g. tying Gemini 3 Pro to
        ``medium`` (its row is low/high).
    """
    levels_raw = gemini_snapshot.get("thinking_levels")
    per_model_raw = gemini_snapshot.get("per_model_levels")
    if not isinstance(levels_raw, list) or not levels_raw:
        return ["check E (gemini): snapshot is missing the 'thinking_levels' list"]
    if not isinstance(per_model_raw, dict):
        return ["check E (gemini): snapshot is missing the 'per_model_levels' map"]
    documented = {str(lv).lower() for lv in levels_raw}

    thinking = extract_block(selector, THINKING_BLOCK)
    flat = _collapse(thinking)
    flat_low = flat.lower()
    failures: list[str] = []

    # E1 — vocabulary equality (subset + completeness).
    vocab = gemini_level_tokens(flat)
    if not vocab:
        failures.append(
            "check E (gemini levels): no level enumeration found on the Gemini bullet "
            "in <thinking-context>. The bullet itself is missing or carries no "
            "backticked levels — the dial's WORDING no longer matters (the locator "
            "is the `- Gemini ...` bullet), so this means real content is absent."
        )
    else:
        for token in sorted(vocab - documented):
            failures.append(
                f"check E (gemini levels): the selector ties Gemini to thinking level "
                f"{token!r}, which is not a documented Gemini 3.x level "
                f"({sorted(documented)})"
            )
        for token in sorted(documented - vocab):
            failures.append(
                f"check E (gemini levels): documented Gemini 3.x level {token!r} is "
                "missing from the selector's Gemini level enumeration"
            )

    # E2 — per-model support (clause-scoped, negation-aware).
    token_re = effort_token_re(list(documented))
    seen: set[tuple[str, str]] = set()
    for clause in split_clauses(flat_low):
        if any(cue in clause for cue in NEGATION_CUES):
            continue
        tokens = {t.lower() for t in token_re.findall(clause)}
        if not tokens:
            continue
        for model, levels in per_model_raw.items():
            if model.lower() not in clause:
                continue
            supported = {str(lv).lower() for lv in levels} if isinstance(levels, list) else set()
            for token in sorted(tokens - supported):
                key = (model, token)
                if key in seen:
                    continue
                seen.add(key)
                failures.append(
                    f"check E (gemini per-model): the selector ties {model!r} to "
                    f"thinking level {token!r}, which is not in its documented row "
                    f"{sorted(supported)}"
                )

    return failures


def deepseek_effort_tokens(thinking_flat: str) -> set[str]:
    """DeepSeek reasoning-effort tokens enumerated on the DeepSeek bullet.

    The bullet reads "... a reasoning-effort enum — ``high``, ``max`` (default
    ...)"; capture the backtick tokens up to the first ``.`` or ``(`` (the
    default / compatibility caveat that follows is parenthetical). The anchor is
    "reasoning-effort **enum**", distinct from OpenAI's "reasoning-effort **knob**"
    (check D), so the two never collide.
    """
    bullet = provider_bullet(thinking_flat, "DeepSeek")
    return enumeration_in_bullet(bullet, REASONING_DIAL_RE, ".(")


def deepseek_toggle_tokens(thinking_flat: str) -> set[str]:
    """DeepSeek thinking-toggle tokens enumerated on the DeepSeek bullet.

    The bullet reads "... a thinking toggle (``enabled`` / ``disabled``, default
    ``enabled``) ..."; capture the backtick tokens inside that first parenthetical.
    """
    bullet = provider_bullet(thinking_flat, "DeepSeek")
    m = re.search(r"thinking[- ]toggle\s*\(([^)]*)\)", bullet, re.IGNORECASE)
    if not m:
        return set()
    return {t.strip().lower() for t in re.findall(r"`([^`]+)`", m.group(1))}


def deepseek_mapping_segment(thinking_flat_low: str) -> str:
    """The DeepSeek output-mapping clause (lowercased).

    From the anchor "deepseek: thinking" to the next list bullet (" - ") or end.
    Scoping the arrow checks to this clause keeps the OpenAI mapping's own
    ``high`` -> ``High`` from satisfying DeepSeek's ``high`` -> ``High`` check.
    """
    m = re.search(r"deepseek: thinking(.*?)(?: - |$)", thinking_flat_low, re.DOTALL)
    return m.group(1) if m else ""


def check_deepseek_thinking(selector: str, deepseek_snapshot: dict[str, object]) -> list[str]:
    """Check F — the selector's DeepSeek reasoning description must match the docs.

    F1 (vocabulary): the DeepSeek reasoning-effort vocabulary the selector
        enumerates must EQUAL the documented ``reasoning_effort`` set
        (``high``/``max``), and the toggle vocabulary must EQUAL the documented
        ``thinking_toggle`` set (``enabled``/``disabled``) — subset + completeness.
    F-mapping: the DeepSeek output mapping must hold — thinking ``disabled`` ->
        Off, effort ``high`` -> High, effort ``max`` -> XHigh — scoped to the
        DeepSeek mapping clause.
    """
    effort_raw = deepseek_snapshot.get("reasoning_effort")
    toggle_raw = deepseek_snapshot.get("thinking_toggle")
    if not isinstance(effort_raw, list) or not effort_raw:
        return ["check F (deepseek): snapshot is missing the 'reasoning_effort' list"]
    if not isinstance(toggle_raw, list) or not toggle_raw:
        return ["check F (deepseek): snapshot is missing the 'thinking_toggle' list"]
    documented_effort = {str(v).lower() for v in effort_raw}
    documented_toggle = {str(v).lower() for v in toggle_raw}

    thinking = extract_block(selector, THINKING_BLOCK)
    flat = _collapse(thinking)
    flat_low = flat.lower()
    failures: list[str] = []

    # F1 — reasoning-effort vocabulary equality (subset + completeness).
    effort_vocab = deepseek_effort_tokens(flat)
    if not effort_vocab:
        failures.append(
            "check F (deepseek effort): no level enumeration found on the DeepSeek "
            "bullet in <thinking-context>. The bullet itself is missing or carries "
            "no backticked levels — the dial's WORDING no longer matters (the "
            "locator is the `- DeepSeek ...` bullet), so this means real content "
            "is absent."
        )
    else:
        for token in sorted(effort_vocab - documented_effort):
            failures.append(
                f"check F (deepseek effort): the selector ties DeepSeek to reasoning "
                f"value {token!r}, which is not a documented DeepSeek reasoning-effort "
                f"value ({sorted(documented_effort)})"
            )
        for token in sorted(documented_effort - effort_vocab):
            failures.append(
                f"check F (deepseek effort): documented DeepSeek reasoning value "
                f"{token!r} is missing from the selector's reasoning-effort enumeration"
            )

    # F1 — thinking-toggle vocabulary equality.
    toggle_vocab = deepseek_toggle_tokens(flat)
    if not toggle_vocab:
        failures.append(
            "check F (deepseek toggle): could not find the DeepSeek thinking-toggle "
            "enumeration in <thinking-context>"
        )
    else:
        for token in sorted(toggle_vocab - documented_toggle):
            failures.append(
                f"check F (deepseek toggle): the selector ties DeepSeek to toggle value "
                f"{token!r}, which is not a documented DeepSeek toggle value "
                f"({sorted(documented_toggle)})"
            )
        for token in sorted(documented_toggle - toggle_vocab):
            failures.append(
                f"check F (deepseek toggle): documented DeepSeek toggle value {token!r} "
                "is missing from the selector's thinking-toggle enumeration"
            )

    # F-mapping — disabled->Off, high->High, max->XHigh, scoped to the clause.
    segment = deepseek_mapping_segment(flat_low)
    if not segment:
        failures.append(
            "check F (deepseek mapping): could not find the DeepSeek output mapping "
            "('DeepSeek: thinking `disabled` -> ...') in <thinking-context>"
        )
    else:
        if not re.search(r"`disabled`\s*(?:→|->)\s*`off`", segment):
            failures.append(
                "check F (deepseek mapping): the selector must map DeepSeek thinking "
                "`disabled` to `Off`"
            )
        if not re.search(r"`high`\s*(?:→|->)\s*`high`", segment):
            failures.append(
                "check F (deepseek mapping): the selector must map DeepSeek effort `high` to `High`"
            )
        if not re.search(r"`max`\s*(?:→|->)\s*`xhigh`", segment):
            failures.append(
                "check F (deepseek mapping): the selector must map DeepSeek effort `max` to `XHigh`"
            )
    return failures


def run_checks(
    selector: str,
    snapshot: dict[str, object],
    codex_snapshot: dict[str, object] | None = None,
    gemini_snapshot: dict[str, object] | None = None,
    deepseek_snapshot: dict[str, object] | None = None,
) -> list[str]:
    failures: list[str] = []
    failures += check_thinking_vocab(selector, snapshot)
    failures += check_per_model_effort(selector, snapshot)
    failures += check_ultracode_ultrathink(selector, snapshot)
    if codex_snapshot is not None:
        failures += check_codex_reasoning_vocab(selector, codex_snapshot)
    if gemini_snapshot is not None:
        failures += check_gemini_thinking(selector, gemini_snapshot)
    if deepseek_snapshot is not None:
        failures += check_deepseek_thinking(selector, deepseek_snapshot)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Conformance gate: selector effort/thinking vocabulary vs docs."
    )
    parser.add_argument("--selector", type=Path, default=DEFAULT_SELECTOR)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--codex-snapshot", type=Path, default=DEFAULT_CODEX_SNAPSHOT)
    parser.add_argument("--gemini-snapshot", type=Path, default=DEFAULT_GEMINI_SNAPSHOT)
    parser.add_argument("--deepseek-snapshot", type=Path, default=DEFAULT_DEEPSEEK_SNAPSHOT)
    args = parser.parse_args()

    try:
        snapshot = load_snapshot(args.snapshot)
        codex_snapshot = load_codex_snapshot(args.codex_snapshot)
        gemini_snapshot = load_gemini_snapshot(args.gemini_snapshot)
        deepseek_snapshot = load_deepseek_snapshot(args.deepseek_snapshot)
        selector = read_selector(args.selector)
    except ConfigError as exc:
        print(f"validate_effort_conformance: config error: {exc}", file=sys.stderr)
        return 2

    failures = run_checks(selector, snapshot, codex_snapshot, gemini_snapshot, deepseek_snapshot)
    if failures:
        print(
            f"validate_effort_conformance: {len(failures)} failure(s):",
            file=sys.stderr,
        )
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    print(
        "validate_effort_conformance: PASS (the EFFORT vocabulary is a documented "
        "Claude Code subset and THINKING stayed a two-position toggle; no model "
        "tied to an unsupported effort level; ultracode "
        "and ultrathink kept distinct; Codex reasoning vocabulary matches the docs; "
        "Gemini thinking levels match the docs; DeepSeek "
        "thinking toggle + reasoning-effort vocabulary and mapping match the docs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
