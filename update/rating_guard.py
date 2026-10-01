#!/usr/bin/env python3
"""Hold every AI curation pass to the rating rules, in code.

The catalog refresh's Opus pass may add models and move a few letters; the
tracker passes (Claude Code, Codex, Gemini, DeepSeek) may move none. The
prompts state the rules (update/prompt.md, "Tier rating updates" and the
new-model section), but a prompt is a request, not a guarantee. This script
compares the committed selector with the pass's proposal and reverts every
S→D letter edit that breaks a rule, reporting each revert:

On a model already in the catalog
  - coding / agentic / long-context / knowledge never move here. A measured
    letter belongs to update/derive_ratings.py (it runs after this guard);
    an unmeasured one stays an estimate until AA publishes the benchmark.
  - planning / multimodal / speed move at most ONE step per run, and only
    with a declaration in the pass's warnings, in the prompt's format:
        tier rating updated: <id> tier-<category> <old>→<new> — <source> shows <figure>
    citing the evidence mapped to that category (EVIDENCE: LMArena →
    planning, MMMU → multimodal, tokens/s → speed). A move INTO S also
    states the category leader's figure, "(leader <figure>)", within
    S_MARGIN points of the model's.

On a model new to the catalog
  - every letter starts from its placeholder, computed here rather than
    taken from the pass: the letters of its predecessor, the same-series
    model (same name words, bar a vendor prefix) with the highest version
    below its own; with no predecessor, B, and speed S for a Mini / Flash /
    Haiku / Nano / Lite name.
  - a letter may differ from its placeholder only with a declaration
        tier rating grounded: <id> tier-<category> <letter> — <source> shows <figure>
    citing that category's evidence (the S rule as above). Long-context and
    knowledge have no evidence outside Artificial Analysis, so their
    placeholder holds until AA measures the model; a measured derived
    letter is left to update/derive_ratings.py.

A tracker pass declares nothing, so every letter edit it makes is reverted.

    python update/rating_guard.py --apply --base /tmp/base-selector.txt \\
        [--declarations update/.last-warnings.txt]
    python update/rating_guard.py --check --base /tmp/base-selector.txt   # exit 1, no edit

The report (one line per revert) goes to stdout and update/.last-rating-guard.md,
which the catalog workflow adds to its PR body.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import derive_ratings  # noqa: E402
from selector_re import ATTR_RE, MODEL_RE  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
BENCHMARKS_PATH = REPO_ROOT / "docs" / "benchmarks.json"
REPORT_PATH = REPO_ROOT / "update" / ".last-rating-guard.md"

LETTERS = "SABCD"
CATEGORIES = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")
DERIVED = tuple(derive_ratings.CATEGORY_EVIDENCE)
ESTIMATED = tuple(c for c in CATEGORIES if c not in DERIVED)

# The evidence a declaration may cite, per category. Coding and agentic
# evidence counts only when a NEW model enters the catalog, before AA measures
# it; long-context and knowledge have none outside Artificial Analysis.
EVIDENCE: dict[str, re.Pattern[str]] = {
    "planning": re.compile(r"\bLMArena\b", re.IGNORECASE),
    "multimodal": re.compile(r"\bMMMU\b"),
    "speed": re.compile(r"tokens?\s*/\s*s(?:ec)?\b|tokens per second|output speed", re.IGNORECASE),
    "coding": re.compile(r"SWE-bench|Aider|LiveCodeBench|CursorBench", re.IGNORECASE),
    "agentic": re.compile(r"τ²-bench|tau2|tau-bench|Terminal-Bench", re.IGNORECASE),
}
# A letter enters S only within this many points of the category leader on
# the same benchmark (index points, or percentage points).
S_MARGIN = 5.0
# Name words that mark a small, fast model (the new-model default: speed S).
_FAST_WORDS = re.compile(r"\b(?:Mini|Flash|Haiku|Nano|Lite)\b", re.IGNORECASE)
# Words a series name may carry or drop without becoming another series.
_VENDOR_WORDS = frozenset({"claude"})

_ID = r"[\w.\-]+"
_SEP = r"\s+[—–-]{1,2}\s+"
_UPDATED = re.compile(
    rf"tier rating updated:\s*(?P<id>{_ID})\s+tier-(?P<cat>[a-z-]+)\s+"
    rf"(?P<old>[SABCD])\s*(?:→|->)\s*(?P<new>[SABCD]){_SEP}(?P<evidence>.+)"
)
_GROUNDED = re.compile(
    rf"tier rating grounded:\s*(?P<id>{_ID})\s+tier-(?P<cat>[a-z-]+)\s+"
    rf"(?P<new>[SABCD]){_SEP}(?P<evidence>.+)"
)
_SHOWS = re.compile(r"\bshows\s+(?P<value>-?\d+(?:\.\d+)?)")
_LEADER = re.compile(r"\(leader\s+(?P<leader>-?\d+(?:\.\d+)?)")
_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    tiers: dict[str, str]


@dataclass(frozen=True)
class Declaration:
    id: str
    category: str
    new: str
    evidence: str
    old: str | None = None  # "tier rating updated" only


@dataclass(frozen=True)
class Revert:
    id: str
    category: str
    proposed: str
    kept: str
    reason: str

    def line(self) -> str:
        return (
            f"- `{self.id}` tier-{self.category}: proposed {self.proposed}, kept "
            f"{self.kept} — {self.reason}"
        )


def models(selector: str) -> dict[str, Model]:
    """{id: Model} for every element in <model-options>."""
    block = _OPTIONS_RE.search(selector)
    if not block:
        raise ValueError("<model-options> block not found")
    out: dict[str, Model] = {}
    for m in MODEL_RE.finditer(block.group(1)):
        attrs: dict[str, str] = dict(ATTR_RE.findall(m.group(1)))
        if "id" not in attrs:
            continue
        tiers = {c: attrs[f"tier-{c}"] for c in CATEGORIES if f"tier-{c}" in attrs}
        out[attrs["id"]] = Model(attrs["id"], attrs.get("name", attrs["id"]), tiers)
    return out


def parse_declarations(text: str) -> dict[tuple[str, str], Declaration]:
    """{(id, category): declaration} from the pass's warnings. A later line
    for the same (id, category) wins."""
    decls: dict[tuple[str, str], Declaration] = {}
    for line in text.splitlines():
        if m := _UPDATED.search(line):
            d = Declaration(m["id"], m["cat"], m["new"], m["evidence"], old=m["old"])
            decls[(d.id, d.category)] = d
        elif m := _GROUNDED.search(line):
            d = Declaration(m["id"], m["cat"], m["new"], m["evidence"])
            decls[(d.id, d.category)] = d
    return decls


def same_series(a: str, b: str) -> bool:
    """`claude-sonnet-5` → `claude-sonnet-5-5`, `opus-4.8` → `claude-opus-5`,
    `gpt-5.6-luna` → `gpt-6-luna`: the same name words, versions aside and a
    vendor prefix optional. `gpt-5.5` → `gpt-5.5-mini` is a different model."""

    def words(s: str) -> set[str]:
        return set(re.findall(r"[a-z]+", s.lower())) - _VENDOR_WORDS

    return bool(words(a)) and words(a) == words(b)


def _version(model_id: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", model_id))


def predecessor(new_id: str, base_models: dict[str, Model]) -> str | None:
    """The same-series model with the highest version below ``new_id``'s:
    `claude-sonnet-5` for `claude-sonnet-5-5`, `gpt-5.6-luna` for `gpt-6-luna`."""
    version = _version(new_id)
    candidates = [
        mid for mid in base_models if same_series(mid, new_id) and _version(mid) < version
    ]
    return max(candidates, key=_version, default=None)


def measured(bench: dict[str, dict[str, Any]], model_id: str, category: str) -> bool:
    row = bench.get(model_id)
    return row is not None and derive_ratings.points(row, category) is not None


def _evidence_problem(decl: Declaration, category: str) -> str | None:
    """Why this declaration cannot carry its letter, or None when it can."""
    pattern = EVIDENCE.get(category)
    if pattern is None:
        return "no source outside Artificial Analysis can set this category"
    if not pattern.search(decl.evidence):
        return f"its declaration cites no {category} evidence"
    if decl.new == "S" and decl.old != "S":
        shows, leader = _SHOWS.search(decl.evidence), _LEADER.search(decl.evidence)
        if not shows or not leader:
            return "an S needs the model's figure and the leader's, '(leader <figure>)'"
        gap = abs(float(leader["leader"]) - float(shows["value"]))
        if gap > S_MARGIN:
            return f"an S needs a figure within {S_MARGIN:g} points of the leader (gap {gap:g})"
    return None


def check_existing(
    base: Model,
    new: Model,
    decls: dict[tuple[str, str], Declaration],
    bench: dict[str, dict[str, Any]],
) -> list[Revert]:
    reverts: list[Revert] = []
    for cat in CATEGORIES:
        was, now = base.tiers.get(cat), new.tiers.get(cat)
        if was is None or now is None or was == now:
            continue
        if cat in DERIVED:
            if measured(bench, new.id, cat):
                continue  # update/derive_ratings.py sets it next
            reverts.append(
                Revert(
                    new.id,
                    cat,
                    now,
                    was,
                    "an unmeasured model's derived letter stays until AA measures it",
                )
            )
            continue
        if abs(LETTERS.index(now) - LETTERS.index(was)) > 1:
            reverts.append(Revert(new.id, cat, now, was, "a letter moves at most one step per run"))
            continue
        decl = decls.get((new.id, cat))
        if decl is None or decl.old is None:
            reverts.append(Revert(new.id, cat, now, was, "no 'tier rating updated' declaration"))
            continue
        if (decl.old, decl.new) != (was, now):
            reverts.append(
                Revert(new.id, cat, now, was, f"its declaration says {decl.old}→{decl.new}")
            )
            continue
        if problem := _evidence_problem(decl, cat):
            reverts.append(Revert(new.id, cat, now, was, problem))
    return reverts


def placeholder(new: Model, base_models: dict[str, Model]) -> tuple[dict[str, str], str]:
    """The letters a new model starts from, and where they come from."""
    pred_id = predecessor(new.id, base_models)
    if pred_id is not None:
        return dict(base_models[pred_id].tiers), f"inherited from `{pred_id}`"
    letters = {c: "B" for c in CATEGORIES}
    if _FAST_WORDS.search(new.name) or _FAST_WORDS.search(new.id.replace("-", " ")):
        letters["speed"] = "S"
    return letters, "the B default: no same-series predecessor"


def check_new(
    new: Model,
    base_models: dict[str, Model],
    decls: dict[tuple[str, str], Declaration],
    bench: dict[str, dict[str, Any]],
) -> list[Revert]:
    start, source = placeholder(new, base_models)
    reverts: list[Revert] = []
    for cat in CATEGORIES:
        now, expected = new.tiers.get(cat), start.get(cat)
        if now is None or expected is None or now == expected:
            continue
        if cat in DERIVED and measured(bench, new.id, cat):
            continue  # update/derive_ratings.py sets it next
        decl = decls.get((new.id, cat))
        if decl is None or decl.old is not None:
            reason = f"differs from its placeholder ({source}) with no 'tier rating grounded' declaration"
        elif decl.new != now:
            reason = f"its declaration says {decl.new}"
        else:
            reason = _evidence_problem(decl, cat) or ""
        if reason:
            reverts.append(Revert(new.id, cat, now, expected, reason))
    return reverts


def guard(
    base: str, proposed: str, declarations: str, bench: dict[str, dict[str, Any]]
) -> tuple[str, list[Revert]]:
    """Return (``proposed`` with every rule-breaking letter edit reverted, the reverts)."""
    base_models = models(base)
    decls = parse_declarations(declarations)
    bench = derive_ratings.with_composites(bench)
    reverts: list[Revert] = []
    for mid, new in models(proposed).items():
        if mid in base_models:
            reverts += check_existing(base_models[mid], new, decls, bench)
        else:
            reverts += check_new(new, base_models, decls, bench)
    return apply_reverts(proposed, reverts), reverts


def apply_reverts(selector: str, reverts: list[Revert]) -> str:
    if not reverts:
        return selector
    by_id: dict[str, list[Revert]] = {}
    for r in reverts:
        by_id.setdefault(r.id, []).append(r)

    def edit(m: re.Match[str]) -> str:
        body = m.group(1)
        mid = re.search(r'\bid="([^"]+)"', body)
        if not mid or mid.group(1) not in by_id:
            return m.group(0)
        for r in by_id[mid.group(1)]:
            body = re.sub(
                rf'tier-{r.category}="[SABCD]"', f'tier-{r.category}="{r.kept}"', body, count=1
            )
        return m.group(0).replace(m.group(1), body, 1)

    block = _OPTIONS_RE.search(selector)
    if not block:
        raise ValueError("<model-options> block not found")
    new_block = MODEL_RE.sub(edit, block.group(1))
    return selector[: block.start(1)] + new_block + selector[block.end(1) :]


def render_report(reverts: list[Revert]) -> str:
    if not reverts:
        return "## Rating guard\n\nEvery letter edit follows the rules.\n"
    lines = [
        "## Rating guard",
        "",
        f"{len(reverts)} letter edit(s) reverted (update/rating_guard.py):",
        "",
        *(r.line() for r in reverts),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true", help="revert rule-breaking edits in place")
    mode.add_argument("--check", action="store_true", help="exit 1 on a rule-breaking edit")
    parser.add_argument("--base", type=Path, required=True, help="the committed selector")
    parser.add_argument("--declarations", type=Path, help="the pass's warnings (one per line)")
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH)
    parser.add_argument(
        "--report", type=Path, default=REPORT_PATH, help="where --apply writes the report"
    )
    args = parser.parse_args()

    declarations = ""
    if args.declarations and args.declarations.exists():
        declarations = args.declarations.read_text(encoding="utf-8")
    bench: dict[str, dict[str, Any]] = {}
    if BENCHMARKS_PATH.exists():
        bench = json.loads(BENCHMARKS_PATH.read_text(encoding="utf-8")).get("models", {})
    proposed = args.selector.read_text(encoding="utf-8")
    guarded, reverts = guard(args.base.read_text(encoding="utf-8"), proposed, declarations, bench)
    report = render_report(reverts)
    print(report)
    if args.check:
        return 1 if reverts else 0
    args.report.write_text(report if reverts else "", encoding="utf-8")
    if guarded != proposed:
        args.selector.write_text(guarded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
