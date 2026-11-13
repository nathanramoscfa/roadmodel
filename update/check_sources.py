"""Decide what a catalog run must do: which sources changed since the last one.

Each provider's own sources decide (2026-11). Until then the run hashed only
Cursor's pricing page, so a model Google priced on its own page waited for
Cursor to edit theirs: Gemini 4 Carbon sat undiscovered while every run said
"pricing.md unchanged". Now the signature carries one line per source:

- ``cursor``: Cursor's pricing page (``sources.json`` ``pricing``), which the
  curation pass (~$5 of Opus tokens) reads for Cursor's own models and the
  models Cursor offers;
- ``provider:<name>``: each provider's price snapshot (``update/catalog-*.json``)
  as this run's readers wrote it, so a new model or price on Google's,
  Anthropic's or OpenAI's own page starts a refresh;
- ``tracker:<name>``: the model names a docs tracker has seen (the Gemini and
  Claude Code ``unexpected_models``, the vendor default-effort tables);
- ``codex``: the models Codex lists (``--codex-ids``).

Any changed line starts the deterministic refresh, which needs no model call.
A changed ``cursor`` line starts the curation pass too, but only when
``--cursor-due`` is set (the daily run and a manual dispatch): the workflow
checks hourly, and the pass must not run once per Cursor edit. A Cursor change
seen on an hourly run keeps the old ``cursor`` line, so the daily run sees it.

Output:
- the new signature in ``update/.cache/sources-hash.new`` (staging: the
  workflow promotes it after the refresh and PR steps succeed, so a failed run
  retries the same change);
- ``changed``, ``cursor_changed`` and ``changed_sources`` in ``$GITHUB_OUTPUT``;
- ``update/.last-summary.txt`` naming the changed sources (the curation pass
  overwrites it with its own summary when it runs).

A Cursor fetch error on a due run counts as changed, so the pass runs and
surfaces the problem instead of silently skipping a refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = UPDATE_DIR / "sources.json"
CACHE_DIR = UPDATE_DIR / ".cache"
HASH_PATH = CACHE_DIR / "sources-hash"
HASH_STAGING_PATH = CACHE_DIR / "sources-hash.new"
SUMMARY_PATH = UPDATE_DIR / ".last-summary.txt"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Docs trackers, each with the part of its snapshot that names models.
TRACKERS: dict[str, str] = {
    "gemini-thinking": "unexpected_models",
    "claude-code-effort": "unexpected_models",
    "default-efforts": "*",
}


def pricing_url() -> str:
    payload = json.loads(SOURCES_PATH.read_text())
    return str(payload["pricing"]["url"])


def fetch_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tracker_models(snapshot: dict[str, object], field: str) -> list[str]:
    """The model names a tracker snapshot records: one list field, or with
    ``*`` the model keys of every surface table (update/default-efforts.json)."""
    if field != "*":
        value = snapshot.get(field)
        return sorted(str(v) for v in value) if isinstance(value, list) else []
    names: set[str] = set()
    for key, table in snapshot.items():
        if key.startswith("_") or not isinstance(table, dict):
            continue
        names.update(str(name) for name in table)
    return sorted(names)


def local_signature(update_dir: Path, codex_ids: Path | None) -> dict[str, str]:
    """Every source this run read itself, keyed as in the signature file."""
    lines: dict[str, str] = {}
    for path in sorted(update_dir.glob("catalog-*.json")):
        lines[f"provider:{path.stem.removeprefix('catalog-')}"] = _sha(path.read_bytes())
    for name, field in TRACKERS.items():
        # The committed snapshot, and this run's read of the docs page where the
        # workflow made one (update/dispose_discoveries.py SECOND_SOURCES).
        paths = [update_dir / f"{name}.json", update_dir / ".cache" / f"{name}.json"]
        found = [json.loads(path.read_text()) for path in paths if path.exists()]
        if found:
            models = sorted({m for snap in found for m in tracker_models(snap, field)})
            lines[f"tracker:{name}"] = _sha(json.dumps(models).encode())
    if codex_ids is not None and codex_ids.exists():
        ids = sorted(x.strip() for x in codex_ids.read_text().splitlines() if x.strip())
        if ids:  # an empty list is a failed fetch: keep the last one
            lines["codex"] = _sha("\n".join(ids).encode())
    return lines


def parse_signature(text: str) -> dict[str, str]:
    """``{key: digest}``. The one-line form before 2026-11 (``<digest>  <url>``)
    was Cursor's page alone."""
    lines: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("http"):
            lines["cursor"] = parts[0]
        elif len(parts) == 2:
            lines[parts[0]] = parts[1]
    return lines


def render_signature(lines: dict[str, str]) -> str:
    return "".join(f"{key} {value}\n" for key, value in sorted(lines.items()))


def decide(
    old: dict[str, str], new: dict[str, str], cursor_due: bool
) -> tuple[dict[str, str], list[str], bool]:
    """The signature to stage, the changed sources, and whether the curation
    pass runs. ``new`` lacks ``cursor`` when the fetch failed."""
    staged = dict(new)
    cursor_new = new.get("cursor")
    cursor_changed = cursor_due and (cursor_new is None or cursor_new != old.get("cursor"))
    if not cursor_due or cursor_new is None:
        # Not processed this run: keep the last line so a later run sees it.
        staged.pop("cursor", None)
        if "cursor" in old:
            staged["cursor"] = old["cursor"]
    changed = sorted(k for k in staged if k != "cursor" and staged[k] != old.get(k))
    if cursor_changed:
        changed.insert(0, "cursor")
    return staged, changed, cursor_changed


def emit_output(changed: list[str], cursor_changed: bool) -> None:
    lines = [
        f"changed={'true' if changed else 'false'}\n",
        f"cursor_changed={'true' if cursor_changed else 'false'}\n",
        f"changed_sources={','.join(changed)}\n",
    ]
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.writelines(lines)
    print("".join(lines), end="")


def summary(changed: list[str]) -> str:
    names = {
        "cursor": "Cursor's pricing page",
        "codex": "the Codex model list",
    }
    labels = [
        names.get(key)
        or (
            f"{key.removeprefix('provider:')}'s pricing page"
            if key.startswith("provider:")
            else f"the {key.removeprefix('tracker:')} docs tracker"
        )
        for key in changed
    ]
    return f"Automated catalog refresh. Changed since the last run: {', '.join(labels)}.\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cursor-due",
        choices=("true", "false"),
        default="true",
        help="whether this run processes a change to Cursor's page (the curation pass)",
    )
    parser.add_argument("--codex-ids", type=Path, default=None, help="the Codex model list")
    args = parser.parse_args()

    new = local_signature(UPDATE_DIR, args.codex_ids)
    try:
        new["cursor"] = _sha(fetch_bytes(pricing_url()))
    except Exception as exc:
        print(f"check_sources: Cursor fetch failed ({exc!r})", file=sys.stderr)

    old = parse_signature(HASH_PATH.read_text()) if HASH_PATH.exists() else {}
    staged, changed, cursor_changed = decide(old, new, args.cursor_due == "true")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HASH_STAGING_PATH.write_text(render_signature(staged))
    if changed:
        print(f"check_sources: changed: {', '.join(changed)}")
        SUMMARY_PATH.write_text(summary(changed))
    else:
        print("check_sources: no source changed since the last run")
    emit_output(changed, cursor_changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
