"""Each vendor's default reasoning effort, read from the vendor's own source.

The other effort trackers cover one dial each: Claude Code, Gemini and DeepSeek
state their defaults in the snapshots those trackers already write. This covers
the rest, so ``docs/catalog.json`` can carry every published default without a
value written by hand anywhere:

- ``anthropic-api``: the API's effort docs. Not Claude Code's defaults: Sonnet
  5.5 starts lower in Claude Code than on the API.
- ``openai-api``: the reasoning guide and the latest-model guide.
- ``codex``: ``default_reasoning_level`` in the catalog Codex ships. Codex with
  an API key runs on this copy (``/v1/models`` carries no reasoning fields);
  signed in with ChatGPT it fetches a live copy that needs that login, which
  can lead this one by a model until the next release catches up.
- ``xai-api``, ``groq-api``, ``zai-api``: their reasoning docs.

A vendor that publishes no default has none here. Nothing is inferred, and a
model the source does not name stays out.

Never guesses: a value outside the known levels, or two statements in a source
that disagree, is an error. A vendor whose source fails keeps its committed
entry and queues a review issue, so one reworded page neither blanks a vendor
nor ships a misread. Writes ``update/default-efforts.json``; no LLM is involved.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import requests

UPDATE_DIR = Path(__file__).resolve().parent
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

from build_catalog import LEVEL_ORDER  # noqa: E402

DEFAULT_OUTPUT = UPDATE_DIR / "default-efforts.json"
CATALOG_PATH = UPDATE_DIR.parent / "docs" / "catalog.json"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

ANTHROPIC_URL = "https://platform.claude.com/docs/en/build-with-claude/effort.md"
OPENAI_REASONING_URL = "https://developers.openai.com/api/docs/guides/reasoning.md"
OPENAI_LATEST_URL = "https://developers.openai.com/api/docs/guides/latest-model.md"
CODEX_RELEASE_URL = "https://api.github.com/repos/openai/codex/releases/latest"
CODEX_CATALOG_URL = (
    "https://raw.githubusercontent.com/openai/codex/{tag}/codex-rs/models-manager/models.json"
)
XAI_URL = "https://docs.x.ai/developers/model-capabilities/text/reasoning.md"
GROQ_URL = "https://console.groq.com/docs/reasoning.md"
ZAI_URL = "https://docs.z.ai/guides/capabilities/thinking.md"

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_SLUG_ITEM_RE = re.compile(r"^\s+- (claude-[a-z0-9-]+)\s*$", re.M)
# `"medium"` on Claude Opus 5.5 and Claude Haiku 5.5, `"high"` on other models
_ANTHROPIC_SENTENCE_RE = re.compile(r'`"(\w+)"` on ([^,`]+), `"(\w+)"` on other models')
# | `high` | ... The default on every model that supports effort except A and B. |
_ANTHROPIC_ROW_RE = re.compile(
    r"^\|\s*`(\w+)`\s*\|[^|\n]*?The default on every model that supports effort"
    r" except (.+?)(?:\.\s|\s*\|)",
    re.M,
)
_GPT_NAME = r"GPT-\d[\d.]*(?: [A-Z][a-z]+)?"
# GPT-6.1 Sol, GPT-6 Sol, and GPT-6 Luna also default to `medium`
_GPT_SENTENCE_RE = re.compile(
    rf"({_GPT_NAME}(?:,? (?:and )?{_GPT_NAME})*) (?:also )?defaults? to `(\w+)`"
)
_LATEST_SECTION_RE = re.compile(rf"^### ({_GPT_NAME})$(.*?)(?=^#|\Z)", re.M | re.S)
_MARKED_DEFAULT_RE = re.compile(r"`(\w+)` \(default\)")
# | `grok-4.7` | `reasoning.effort`: `"low"` / `"high"` (default) / ... | ... |
_XAI_ROW_RE = re.compile(r'^\|\s*`(grok-[\w.-]+)`\s*\|[^|\n]*`"(\w+)"` \(default\)', re.M)
_XAI_BLANKET_RE = re.compile(r'`reasoning_effort` defaults to `"(\w+)"`')
_GROQ_SECTION_RE = re.compile(r"^### \[Options for Reasoning Effort \((.+?)\)\]", re.M)
_GROQ_ROW_RE = re.compile(r"^\|\s*(\w+)\s*\|[^|\n]*This is the default\.", re.M)
_ZAI_AVAILABLE_RE = re.compile(r"Available values: `(\w+)` \(default")
_ZAI_ONLY_RE = re.compile(r"For ([^,]+), only `")
_ZAI_LISTED_RE = re.compile(r"For ([^,]+), the supported options are `(\w+)` \(default")

Fetch = Callable[[str], str]


class ExtractError(RuntimeError):
    """A vendor's source no longer reads the way this parser expects."""


def fetch_text(url: str) -> str:
    # A bare */*: xAI answers a `.md` URL with 404 if Accept names text/markdown.
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def _level(word: str) -> str:
    level = word.strip().lower()
    if level not in LEVEL_ORDER:
        raise ExtractError(f"{word!r} is not a known effort level")
    return level


def _names(text: str) -> list[str]:
    """ "A, B, and C" -> ["A", "B", "C"]."""
    return [name.strip() for name in re.split(r",|\band\b", text) if name.strip()]


def _agree(*statements: Mapping[str, str]) -> dict[str, str]:
    """Merge a vendor's statements; two about one model must say the same."""
    merged: dict[str, str] = {}
    for statement in statements:
        for model, level in statement.items():
            if merged.setdefault(model, level) != level:
                raise ExtractError(f"{model}: the source says both {merged[model]} and {level}")
    return merged


def _expand(name: str, catalog_names: Iterable[str]) -> list[str]:
    """A family a source names as one ("GPT-5.6") as the models it covers."""
    prefix = name.lower()
    members = [n for n in catalog_names if n.lower().startswith((f"{prefix} ", f"{prefix}-"))]
    return members or [name]


def _claude_name(slug: str) -> str:
    """claude-opus-5-5 -> Opus 5.5; claude-opus-4-5-20251101 -> Opus 4.5."""
    family, *version = re.sub(r"-\d{8}$", "", slug).split("-")[1:]
    return f"{family.capitalize()} {'.'.join(version)}"


def _gpt_name(slug: str) -> str:
    """gpt-6.1-sol -> GPT-6.1 Sol; gpt-5.1-codex-max -> GPT-5.1 Codex Max."""
    _, version, *words = slug.split("-")
    return " ".join([f"GPT-{version}", *(word.capitalize() for word in words)])


def parse_anthropic(page: str) -> dict[str, str]:
    """Every effort model at the page's blanket default, bar its exceptions.

    The tip and the level table state the exceptions separately, so a page that
    moves one without the other stops here.
    """
    frontmatter = _FRONTMATTER_RE.search(page)
    slugs = _SLUG_ITEM_RE.findall(frontmatter.group(1)) if frontmatter else []
    sentence = _ANTHROPIC_SENTENCE_RE.search(page)
    row = _ANTHROPIC_ROW_RE.search(page)
    if not slugs or sentence is None or row is None:
        raise ExtractError("the supported-model list or a default statement is missing")
    lower, named, blanket = sentence.groups()
    excepted = set(_names(named))
    if excepted != set(_names(row.group(2))) or _level(row.group(1)) != _level(blanket):
        raise ExtractError(f"tip reads {sentence.group(0)!r}, table row {row.group(0)!r}")
    bare = {name.removeprefix("Claude ") for name in excepted}
    models = {_claude_name(slug) for slug in slugs}
    if not bare <= models:
        raise ExtractError(f"{sorted(bare - models)} are not on the supported-model list")
    return {name: _level(lower if name in bare else blanket) for name in sorted(models)}


def parse_openai(reasoning: str, latest: str, catalog_names: Iterable[str]) -> dict[str, str]:
    """What the two guides state, model by model; a family covers its models."""
    names = list(catalog_names)
    guide: dict[str, str] = {}
    for named, level in _GPT_SENTENCE_RE.findall(reasoning):
        for name in re.findall(_GPT_NAME, named):
            for model in _expand(name, names):
                guide[model] = _level(level)
    sections: dict[str, str] = {}
    for name, body in _LATEST_SECTION_RE.findall(latest):
        marked = _MARKED_DEFAULT_RE.search(body)
        if marked is not None:
            sections[name] = _level(marked.group(1))
    return _agree(guide, sections)


def parse_codex(catalog: Mapping[str, Any]) -> dict[str, str]:
    """The listed models in Codex's own catalog; hidden ones are not choosable."""
    return {
        _gpt_name(str(row["slug"])): _level(str(row["default_reasoning_level"]))
        for row in catalog["models"]
        if row.get("visibility") == "list" and row.get("default_reasoning_level")
    }


def parse_xai(page: str) -> dict[str, str]:
    """The model table, held to the sentence stating the blanket default."""
    blanket = _XAI_BLANKET_RE.search(page)
    rows = {slug.capitalize(): _level(level) for slug, level in _XAI_ROW_RE.findall(page)}
    if blanket is None or set(rows.values()) != {_level(blanket.group(1))}:
        raise ExtractError(f"the sentence and the table disagree: {rows}")
    return {name.replace("-", " "): level for name, level in rows.items()}


def parse_groq(page: str, catalog_names: Iterable[str]) -> dict[str, str]:
    """The row a model's options table marks as its default, if it marks one."""
    names = list(catalog_names)
    _, *sections = _GROQ_SECTION_RE.split(page)
    if not sections:
        raise ExtractError("no reasoning-effort option tables found")
    stated: dict[str, str] = {}
    for heading, body in zip(sections[::2], sections[1::2], strict=True):
        row = _GROQ_ROW_RE.search(body.split("\n## ", 1)[0])
        if row is not None:
            for model in _expand(heading, names):
                stated[model] = _level(row.group(1))
    return stated


def parse_zai(page: str) -> dict[str, str]:
    """The `reasoning_effort` default, given once overall and once per family."""
    overall = _ZAI_AVAILABLE_RE.search(page)
    if overall is None:
        raise ExtractError("no default on the reasoning_effort values")
    level = _level(overall.group(1))
    stated = {name: level for named in _ZAI_ONLY_RE.findall(page) for name in _names(named)}
    listed = {
        name: _level(word) for named, word in _ZAI_LISTED_RE.findall(page) for name in _names(named)
    }
    return _agree(stated, listed)


def read_anthropic(fetch: Fetch, _catalog: list[str]) -> dict[str, str]:
    return parse_anthropic(fetch(ANTHROPIC_URL))


def read_openai(fetch: Fetch, names: list[str]) -> dict[str, str]:
    return parse_openai(fetch(OPENAI_REASONING_URL), fetch(OPENAI_LATEST_URL), names)


def read_codex(fetch: Fetch, _catalog: list[str]) -> dict[str, str]:
    tag = str(json.loads(fetch(CODEX_RELEASE_URL))["tag_name"])
    return parse_codex(json.loads(fetch(CODEX_CATALOG_URL.format(tag=tag))))


def read_xai(fetch: Fetch, _catalog: list[str]) -> dict[str, str]:
    return parse_xai(fetch(XAI_URL))


def read_groq(fetch: Fetch, names: list[str]) -> dict[str, str]:
    return parse_groq(fetch(GROQ_URL), names)


def read_zai(fetch: Fetch, _catalog: list[str]) -> dict[str, str]:
    return parse_zai(fetch(ZAI_URL))


SOURCES: dict[str, tuple[Callable[[Fetch, list[str]], dict[str, str]], str]] = {
    "anthropic-api": (read_anthropic, ANTHROPIC_URL),
    "openai-api": (read_openai, f"{OPENAI_REASONING_URL} and {OPENAI_LATEST_URL}"),
    "codex": (read_codex, CODEX_CATALOG_URL),
    "xai-api": (read_xai, XAI_URL),
    "groq-api": (read_groq, GROQ_URL),
    "zai-api": (read_zai, ZAI_URL),
}

# Groq names only a default for models outside the catalog today, which is a
# real answer: an empty read there is not a failure.
MAY_BE_EMPTY = frozenset({"groq-api"})


def refresh(
    previous: Mapping[str, Any], fetch: Fetch, catalog_names: list[str]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """A fresh snapshot, plus a review item for each thing it could not settle."""
    snapshot: dict[str, Any] = {
        "_comment": (
            "Each vendor's default reasoning effort, from its own docs or catalog. "
            "Generated by update/extract_default_efforts.py — do not hand-edit. "
            "update/build_catalog.py publishes it per access method."
        ),
        "source_urls": {vendor: source[1] for vendor, source in SOURCES.items()},
    }
    review: list[tuple[str, str]] = []
    for vendor, (read, url) in SOURCES.items():
        committed = previous.get(vendor)
        committed = dict(committed) if isinstance(committed, Mapping) else {}
        try:
            stated = read(fetch, catalog_names)
            if not stated and vendor not in MAY_BE_EMPTY:
                raise ExtractError("no default found")
        except (requests.ConnectionError, requests.Timeout) as exc:
            print(f"extract_default_efforts: {vendor}: {exc!r}; keeping it", file=sys.stderr)
            snapshot[vendor] = committed
            continue
        except (requests.RequestException, ExtractError, KeyError, TypeError, ValueError) as exc:
            print(f"extract_default_efforts: {vendor}: {exc!r}; keeping it", file=sys.stderr)
            snapshot[vendor] = committed
            review.append(
                (
                    f"chore(default-efforts): could not read {vendor}",
                    f"{url} did not parse: `{exc!r}`.\n\nThe refresh kept the committed "
                    f"`{vendor}` entry in `update/default-efforts.json`. Either the vendor "
                    "changed what it says, or `update/extract_default_efforts.py` needs "
                    "to learn the new wording.",
                )
            )
            continue
        snapshot[vendor] = dict(sorted(stated.items()))
        for model in sorted(set(committed) - set(stated)):
            review.append(
                (
                    f'chore(default-efforts): {vendor} no longer states a default for "{model}"',
                    f"{url} stopped naming `{model}`, so the catalog no longer gives it a "
                    "default on this surface. Either the vendor withdrew the model or the "
                    "statement, or the parser stopped matching a reworded sentence.",
                )
            )
    return snapshot, review


def _catalog_names(path: Path = CATALOG_PATH) -> list[str]:
    return [str(model["name"]) for model in json.loads(path.read_text())["models"]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh update/default-efforts.json.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--review-queue",
        type=Path,
        default=None,
        help="queue each thing the run could not settle (update/review_queue.py)",
    )
    args = parser.parse_args()

    previous = json.loads(args.output.read_text()) if args.output.exists() else {}
    snapshot, review = refresh(previous, fetch_text, _catalog_names())
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    print(f"extract_default_efforts: wrote {args.output} ({len(review)} for review)")
    if review and args.review_queue is not None:
        import review_queue

        review_queue.add(review, args.review_queue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
