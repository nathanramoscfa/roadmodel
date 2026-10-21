"""Deterministically extract Claude Code's effort / thinking facts from the
official model-config docs.

This is the *docs* half of the Claude Code surface-parameter tracker (the
CHANGELOG half lives in ``update/update_claude_code.py``). It fetches the
clean Markdown endpoint
``https://code.claude.com/docs/en/model-config.md``, isolates ONLY the four
in-scope effort/thinking sections, and parses out the canonical facts with
plain Markdown-table parsing — **no LLM call**:

- the per-model effort-level matrix (``### Adjust effort level`` table),
- the ``ultracode`` semantics (a session setting, not a model effort level),
- the ``ultrathink`` per-turn keyword rule, and
- the extended-thinking on/off controls.

The result is written as a JSON snapshot. The committed copy
(``update/claude-code-effort.json``) is the OFFLINE source of truth for
``update/validate_effort_conformance.py`` — it lets the per-PR conformance
gate run with no network. Today that committed copy is refreshed by running
this script (``--output``); a scheduled docs-freshness loop that re-runs the
extractor and opens a PR when the docs change is a later step (T2), at which
point the recorded ``section_sha256`` and the ephemeral mirror under
``update/.cache/claude-code-effort.json`` (gitignored) drive change detection.

The four in-scope doc anchors (everything else on the page — model aliases,
env vars, fallback chains, 1M context, prompt caching — is OUT OF SCOPE):

- ``#adjust-effort-level``
- ``#choose-an-effort-level``
- ``#use-ultrathink-for-one-off-deep-reasoning``
- ``#extended-thinking``

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
from collections.abc import Iterable, Mapping
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "claude-code-effort.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "claude-code-effort.json"

DOCS_URL = "https://code.claude.com/docs/en/model-config.md"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# The in-scope span is the contiguous region from the effort heading through
# the end of the extended-thinking heading (i.e. everything before the next
# unrelated "### Extended context" heading). Hashing/parsing only this span —
# not the whole page — lets a future docs-freshness cron detect effort/thinking
# changes (via section_sha256) without firing on unrelated docs edits.
IN_SCOPE_START_HEADING = "### Adjust effort level"
IN_SCOPE_END_HEADING = "### Extended context"

# Canonical display order for the union of documented effort levels.
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")

# Models this tracker has seen in the effort table. A row outside this set is
# FLAGGED (a new model is the catalog cron's lane), never acted on here.
# "Sonnet 5" was added 2026-07-14: Claude Code now documents it (default model,
# full low..max effort range) and the catalog cron is adding claude-sonnet-5 to
# <model-options>, so the effort tracker acknowledges it here.
# "Opus 5" added 2026-09-04: it has been in <model-options> as claude-opus-5
# since the 2026-08 catalog refresh, so flagging it daily was noise. Models the
# catalog does NOT carry yet (Fable 5.1, as of this commit) stay unlisted on
# purpose — that flag is the handoff to the catalog cron.
# "Haiku 5.5" added 2026-10-20: the catalog carries it as claude-haiku-5-5 since
# 0.2.87 (#1151), so flagging it daily had become noise.
KNOWN_MODELS = frozenset(
    {
        "Haiku 5.5",
        "Fable 5.1",
        "Fable 5",
        "Opus 5.5",
        "Opus 5",
        "Sonnet 5.5",
        "Sonnet 5",
        "Opus 4.8",
        "Opus 4.7",
        "Opus 4.6",
        "Sonnet 4.6",
    }
)

# A model as the docs name it in prose: a word, then a version ("Opus 5.5").
_MODEL_NAME_RE = re.compile(r"[A-Z][A-Za-z]*(?: \d[\w.]*)+")

# Every wording the docs have used for "ultracode puts the session at xhigh".
# Anchored on the fact (ultracode <-> xhigh), not one sentence: Claude Code
# 2.1.284 reworded it when ultracode became a toggle that keeps the current
# effort, with only the `--effort ultracode` launch flag also setting xhigh,
# and the one-phrase anchor failed the tracker (2026-09-29).
_ULTRACODE_XHIGH_RES = (
    re.compile(r"sends\s+\W{0,3}xhigh"),  # to 2.1.283: "it sends `xhigh` to the model"
    re.compile(r"set\s+the\s+(?:session(?:'s)?\s+)?level\s+to\s+\W{0,3}xhigh"),  # 2.1.284 flag
    re.compile(r"starts\s+the\s+session\s+at\s+\W{0,3}xhigh"),  # 2.1.284 flag, bullet form
)

# Sentinel substrings that MUST survive in the in-scope span. Their absence
# means the docs were restructured and the deterministic parse can no longer
# be trusted — fail loudly instead of emitting a partial snapshot.
#
# Anchor on the FACTS this file extracts, not on the sentence grammar that
# happens to carry them. "not recognized as keywords" was a prose fragment,
# and when the docs reworded the same fact to "doesn't recognize them as
# keywords" the extractor failed for 24 straight days (2026-08-12 onward)
# over a rewrite that changed nothing it parses. `"think hard"` is the
# pass-through keyword list itself — it moves only when the fact moves.
REQUIRED_ANCHORS = (
    "Adjust effort level",
    "Ultracode is a Claude Code setting",
    "ultrathink",
    '"think hard"',
    "Extended thinking",
)


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
    """Return only the effort/thinking section span of the docs page."""
    lines = markdown.splitlines(keepends=True)
    start = end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None and stripped == IN_SCOPE_START_HEADING:
            start = i
        elif start is not None and stripped == IN_SCOPE_END_HEADING:
            end = i
            break
    if start is None:
        raise ExtractError(f"in-scope start heading not found: {IN_SCOPE_START_HEADING!r}")
    if end is None:
        raise ExtractError(f"in-scope end heading not found: {IN_SCOPE_END_HEADING!r}")
    return "".join(lines[start:end])


def verify_anchors(in_scope: str) -> None:
    missing = [a for a in REQUIRED_ANCHORS if a not in in_scope]
    if missing:
        raise ExtractError(f"expected docs anchors missing (restructure?): {missing}")


def parse_effort_table(in_scope: str) -> dict[str, list[str]]:
    """Parse the ``| Model | Levels |`` per-model effort matrix.

    A model cell may name several models as a comma / "and" list — either
    "Opus 4.8 and Opus 4.7" or an Oxford-comma list like
    "Sonnet 5, Opus 4.8, and Opus 4.7"; each model gets the row's level list.
    Splitting on "and" alone mangled the comma form into one bogus name
    ("Sonnet 5, Opus 4.8,"), which the tracker then flagged daily as a new
    model — so split on both, mirroring ``parse_defaults``. Levels are the
    backtick-wrapped tokens of the second cell.
    """
    lines = in_scope.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and "Model" in line and "Levels" in line:
            header_idx = i
            break
    if header_idx is None:
        raise ExtractError("effort-level table (| Model | Levels |) not found")

    per_model: dict[str, list[str]] = {}
    for line in lines[header_idx + 1 :]:
        if not line.lstrip().startswith("|"):
            break  # end of the contiguous table block
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        model_cell, levels_cell = cells[0], cells[1]
        if set(model_cell) <= set(":- "):
            continue  # the |:---|:---| separator row
        levels = [tok.lower() for tok in re.findall(r"`([^`]+)`", levels_cell)]
        if not levels:
            continue
        for model in re.split(r",|\band\b", model_cell):
            model = model.strip().strip(",").strip()
            if model:
                per_model[model] = levels

    if len(per_model) < 2:
        raise ExtractError(f"effort table parsed too few models: {per_model!r}")
    return per_model


def build_effort_levels(per_model: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    for levels in per_model.values():
        seen.update(levels)
    ordered = [lv for lv in EFFORT_ORDER if lv in seen]
    extras = sorted(seen - set(EFFORT_ORDER))
    return ordered + extras


def parse_defaults(in_scope: str) -> dict[str, str]:
    """Best-effort parse of the documented default effort level.

    Two shapes, because the docs changed form in 2026-08 without changing the
    fact:

    - sentence: "The default effort is `high` on ..., and `xhigh` on Opus 4.7"
    - list item: "The model's default effort: `high` on every model that
      supports effort, except that Opus 4.7 defaults to `xhigh`"

    The blanket default lands under the key ``"*"``; per-model exceptions land
    under their model name. Informational only — the conformance check does not
    depend on it — so a miss returns ``{}`` rather than raising.
    """
    defaults: dict[str, str] = {}

    # Capture to end-of-line, not to the first ".", because model names carry
    # version dots (e.g. "Opus 4.8"). Strip only the trailing sentence period.
    m = re.search(r"The default effort is ([^\n]+)", in_scope)
    if m:
        sentence = m.group(1).rstrip().rstrip(".")
        for lm in re.finditer(r"`(\w+)`\s+on\s+([^`]+?)(?=,?\s+and\s+`|`|$)", sentence):
            level = lm.group(1).lower()
            for model in re.split(r",|\band\b", lm.group(2)):
                model = model.strip().strip(",").strip()
                if model:
                    defaults[model] = level
        if defaults:
            return defaults

    # List form: a blanket default plus carve-outs, singular or plural:
    # "Opus 4.7 defaults to `xhigh`", "Opus 5.5 and Sonnet 5.5 default to
    # `medium`". The plural form went unread and the tracker then struck Opus
    # 5.5's true `medium` default from the selector (2026-09-29).
    blanket = re.search(r"default effort: `(\w+)` on every model that supports effort", in_scope)
    if blanket:
        defaults["*"] = blanket.group(1).lower()
    for em in re.finditer(r"\bdefaults?\s+to\s+`(\w+)`", in_scope):
        head = in_scope[max(0, em.start() - 160) : em.start()]
        clause = re.split(r"except that |`,\s*|[;:]\s+|\.\s+|\n", head)[-1]
        for name in re.split(r",|\band\b", clause):
            name = name.strip()
            if _MODEL_NAME_RE.fullmatch(name):
                defaults[name] = em.group(1).lower()
    return defaults


def parse_ultracode(in_scope: str) -> dict[str, object]:
    lower = in_scope.lower()
    is_setting = "ultracode is a claude code setting" in lower
    sends_xhigh = any(rx.search(lower) for rx in _ULTRACODE_XHIGH_RES)
    # 2.1.284: turning ultracode on with /effort or the setting keeps the
    # session's effort; only the launch flag also sets xhigh.
    keeps_effort = "leaves the effort level unchanged" in lower
    # ultracode->xhigh is one of the four in-scope facts and feeds the
    # conformance gate. If the docs still document ultracode but reword the
    # "sends xhigh" phrasing, fail loud rather than emit sends_effort=None,
    # which would silently disable the gate's ultracode/xhigh assertion.
    if is_setting and not sends_xhigh:
        raise ExtractError(
            "ultracode is documented but its xhigh-effort link was not found "
            "(docs reworded the 'sends xhigh' phrasing?)"
        )
    return {
        "is_effort_level": False,
        "is_setting": is_setting,
        "sends_effort": "xhigh" if sends_xhigh else None,
        "keeps_session_effort": keeps_effort,
        "xhigh_via": "claude --effort ultracode" if keeps_effort else "/effort ultracode",
        "orchestrates_workflows": "orchestrate" in lower and "workflow" in lower,
        "session_only": "current session only" in lower,
        "set_via": ["/effort", '"ultracode": true'],
    }


def parse_ultrathink(in_scope: str) -> dict[str, object]:
    lower = in_scope.lower()
    effort_neutral = "without changing your session effort" in lower or "does not change" in lower
    return {
        "is_per_turn_keyword": "ultrathink" in lower,
        "changes_session_effort": False if effort_neutral else None,
        "orchestrates_workflows": False,
        "recognized": ["ultrathink"],
        "not_recognized": ["think", "think hard", "think more"],
    }


# The FACT "thinking can't be disabled on these models", in every wording the
# docs have used for it: "Thinking cannot be turned off on Fable 5.1 or Fable 5"
# (to 2026-09) and "You can't turn thinking off on Opus 5.5, Sonnet 5.5, Haiku
# 5.5, or the Fable models" (2026-09-29 on). The first regex alone read only the
# old wording, so from #585 (2026-09-10) the snapshot carried an empty list and
# nothing noticed. The list runs to the end of the sentence: a period followed by
# whitespace, which a version dot ("5.1") never is.
_NO_DISABLE_RE = re.compile(
    r"\b(?:cannot|can(?:'|\u2019)t|can\s+not)\s+"
    r"(?:be\s+turned\s+off|turn\s+(?:thinking|it)\s+off|turn\s+off\s+thinking)"
    r"\s+(?:on|for)\s+(?P<models>[^\n]+?)(?=\.(?:\s|$)|\n|$)",
    re.IGNORECASE,
)
# A sentence saying thinking can't be turned off, in any form — including the UI
# string the docs quote ("show `Thinking can't be turned off` for these models").
# If one is in scope but the list above came back empty, the docs reworded the
# fact: fail loud rather than write `cannot_disable_on: []` again.
_NO_DISABLE_MENTION_RE = re.compile(
    r"(?:cannot|can(?:'|\u2019)t|can\s+not)\s+(?:be\s+)?turn(?:ed)?\s+(?:thinking\s+)?off"
    r"|thinking\s+(?:cannot|can(?:'|\u2019)t|can\s+not)\s+be\s+(?:turned\s+off|disabled)",
    re.IGNORECASE,
)
# "the Fable models", "Fable models", "the Fable 5 models": a family the docs name
# instead of listing its members.
_FAMILY_RE = re.compile(r"(?:the\s+)?(?P<family>[A-Z][A-Za-z]*(?: \d[\w.]*)*)\s+models?")


def _expand_family(family: str, models: list[str]) -> list[str]:
    """The effort-table models a family name covers, in table order."""
    return [
        m for m in models if m == family or m.startswith(family + " ") or m.startswith(family + ".")
    ]


def parse_extended_thinking(in_scope: str, models: Iterable[str] = ()) -> dict[str, object]:
    """The extended-thinking controls and the models thinking can't be turned off on.

    ``models`` are the effort table's model names, used to expand a family the
    docs name ("the Fable models") into its members, so the snapshot always
    lists models by the names the rest of it uses.
    """
    known_controls = ["Option+T", "Alt+T", "alwaysThinkingEnabled", "MAX_THINKING_TOKENS=0"]
    present = [c for c in known_controls if c in in_scope]
    table = list(models)
    cannot: list[str] = []
    for match in _NO_DISABLE_RE.finditer(in_scope):
        for item in re.split(r",|\bor\b|\band\b", match.group("models")):
            item = item.strip().strip("`*").strip()
            if item.lower().startswith("the "):
                item = item[4:].strip()
            if not item:
                continue
            family = _FAMILY_RE.fullmatch(item)
            if _MODEL_NAME_RE.fullmatch(item):
                names = [item]
            elif family:
                names = _expand_family(family.group("family"), table)
                if not names:
                    raise ExtractError(
                        f"the docs say thinking can't be turned off on {item!r}, but no "
                        f"model in the effort table belongs to it: {table}"
                    )
            else:
                names = _MODEL_NAME_RE.findall(item)
                if not names:
                    raise ExtractError(
                        f"could not read a model out of {item!r} in the "
                        "'thinking can't be turned off' sentence"
                    )
            cannot.extend(n for n in names if n not in cannot)
    if not cannot and _NO_DISABLE_MENTION_RE.search(in_scope):
        raise ExtractError(
            "the docs say thinking can't be turned off on some models, but no model "
            "list was parsed (the sentence was reworded?) — refusing to write an "
            "empty extended_thinking.cannot_disable_on"
        )
    return {
        "primary_control_is_effort": "effort level is the primary control" in in_scope,
        "on_off_controls": present,
        "cannot_disable_on": cannot,
    }


def section_sha256(in_scope: str) -> str:
    return hashlib.sha256(in_scope.encode("utf-8")).hexdigest()


def build_snapshot(markdown: str, *, source_url: str) -> dict[str, object]:
    in_scope = isolate_in_scope(markdown)
    verify_anchors(in_scope)
    per_model = parse_effort_table(in_scope)
    # FLAG (never act on) a model the docs table introduces that this tracker
    # hasn't seen — new models are the catalog cron's lane.
    unexpected = sorted(set(per_model) - KNOWN_MODELS)
    if unexpected:
        print(
            f"extract_claude_code_effort: NOTE unexpected model(s) in the effort "
            f"table, not in the known baseline: {unexpected}. New models are the "
            f"catalog cron's lane — flag them (e.g. open an issue); do NOT add "
            f"them to selector model lists here.",
            file=sys.stderr,
        )
    return {
        "_comment": (
            "Canonical Claude Code effort/thinking facts extracted from the "
            "official model-config docs. Generated by "
            "update/extract_claude_code_effort.py — do not hand-edit; refresh by "
            "running that script. Consumed OFFLINE by "
            "update/validate_effort_conformance.py."
        ),
        "source_url": source_url,
        "in_scope_sections": [
            "adjust-effort-level",
            "choose-an-effort-level",
            "use-ultrathink-for-one-off-deep-reasoning",
            "extended-thinking",
        ],
        "effort_levels": build_effort_levels(per_model),
        "per_model_effort": per_model,
        "default_effort": parse_defaults(in_scope),
        "fallback_rule": "highest supported level at or below the requested level",
        "ultracode": parse_ultracode(in_scope),
        "ultrathink": parse_ultrathink(in_scope),
        "extended_thinking": parse_extended_thinking(in_scope, per_model),
        "unexpected_models": unexpected,
        "section_sha256": section_sha256(in_scope),
    }


def _str_list(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _lookup(snapshot: Mapping[str, object], dotted: str) -> object:
    node: object = snapshot
    for key in dotted.split("."):
        node = node.get(key) if isinstance(node, Mapping) else None
    return node


# The lists whose entries the gate and the selector lean on. An entry that
# disappears from one is a contract change (a control removed, a model that can
# now turn thinking off, an effort level withdrawn) — or a parse that quietly
# stopped matching, which is how `cannot_disable_on` went empty for six weeks.
SHRINK_GUARDED = (
    "extended_thinking.cannot_disable_on",
    "extended_thinking.on_off_controls",
    "effort_levels",
)


def snapshot_shrink(old: Mapping[str, object], new: Mapping[str, object]) -> list[str]:
    """Entries the committed snapshot ``old`` lists and the fresh ``new`` drops.

    Covers the guarded lists above and every per-model effort row: a model row
    that vanished, or a level a surviving row no longer lists. Additions are not
    reported — the refresh exists to take those.
    """
    removed: list[str] = []
    for key in SHRINK_GUARDED:
        after = set(_str_list(_lookup(new, key)))
        removed += [
            f"{key}: {entry}" for entry in _str_list(_lookup(old, key)) if entry not in after
        ]
    old_rows = old.get("per_model_effort")
    new_rows = new.get("per_model_effort")
    if isinstance(old_rows, Mapping):
        fresh = new_rows if isinstance(new_rows, Mapping) else {}
        for model, levels in old_rows.items():
            if model not in fresh:
                removed.append(f"per_model_effort: {model} (whole row)")
                continue
            after = set(_str_list(fresh[model]))
            removed += [
                f"per_model_effort.{model}: {lv}" for lv in _str_list(levels) if lv not in after
            ]
    return removed


def shrink_review_items(removed: list[str], source_url: str) -> list[tuple[str, str]]:
    """One review item per dropped entry, titled so a rerun finds it open."""
    items = []
    for entry in removed:
        key, _, value = entry.partition(": ")
        body = (
            f"The Claude Code docs refresh dropped `{value}` from `{key}` in "
            "`update/claude-code-effort.json` (extracted from "
            f"{source_url}).\n\n"
            "Either the docs withdrew the fact — a contract change the selector "
            "may still describe, so check `<thinking-context>`, the claude-code "
            "method and any `always-thinks` attributes — or the extractor stopped "
            "reading a reworded sentence, which is a bug in "
            "`update/extract_claude_code_effort.py`. The refresh wrote the new "
            "snapshot; this issue keeps the removal from passing unseen."
        )
        items.append((f'chore(claude-code): docs snapshot dropped {key} "{value}"', body))
    return items


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Claude Code effort/thinking facts from the docs."
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
        "--baseline",
        type=Path,
        default=None,
        help=(
            "the committed snapshot to compare against (read before --output is "
            "written); entries it lists that the fresh snapshot drops are reported"
        ),
    )
    parser.add_argument(
        "--review-queue",
        type=Path,
        default=None,
        help="queue each dropped entry here for a review issue (update/review_queue.py)",
    )
    args = parser.parse_args()

    try:
        markdown = args.input.read_text() if args.input else fetch_markdown(args.url)
    except Exception as exc:
        print(
            f"extract_claude_code_effort: fetch/read failed: {exc!r}",
            file=sys.stderr,
        )
        return 3

    try:
        snapshot = build_snapshot(markdown, source_url=args.url)
    except ExtractError as exc:
        print(
            f"extract_claude_code_effort: extraction failed: {exc}",
            file=sys.stderr,
        )
        return 4

    removed: list[str] = []
    if args.baseline is not None and args.baseline.exists():
        try:
            baseline = json.loads(args.baseline.read_text())
        except (OSError, ValueError) as exc:
            print(f"extract_claude_code_effort: baseline unreadable: {exc!r}", file=sys.stderr)
            return 3
        if isinstance(baseline, dict):
            removed = snapshot_shrink(baseline, snapshot)

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    # Mirror an ephemeral copy for the cron's hash comparison (gitignored).
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    per_model = snapshot["per_model_effort"]
    levels = snapshot["effort_levels"]
    summary = ", ".join(levels) if isinstance(levels, list) else str(levels)
    count = len(per_model) if isinstance(per_model, dict) else 0
    print(
        f"extract_claude_code_effort: wrote {args.output} "
        f"({count} models, effort levels: {summary})"
    )
    if removed:
        print(
            "extract_claude_code_effort: NOTE the fresh snapshot DROPS entries the "
            f"committed one lists: {removed}. Routed for review; never silently accepted.",
            file=sys.stderr,
        )
        if args.review_queue is not None:
            sys.path.insert(0, str(UPDATE_DIR))
            import review_queue

            review_queue.add(shrink_review_items(removed, args.url), args.review_queue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
