#!/usr/bin/env python3
"""The catalogued models OpenRouter routes, for the openrouter method's sync.

OpenRouter lists every model it routes on a public endpoint
(https://openrouter.ai/api/v1/models, no key needed). This maps each listed
model to a ``<model>`` id in docs/model-selector.txt by normalized name — the
maker prefix dropped, dots and dashes alike, a leading "claude-" optional,
matched against the catalog id and the display name — with the exceptions
that do not normalize in update/openrouter-model-map.json. The catalog cron
feeds the ids to ``merge_catalog.py --sync-method openrouter``, which adds the
catalogued ones to the method's supports-models (additive only).

Left out: ``:batch`` variants (a batch API, not a chat route), ``~…-latest``
aliases (a pointer that moves), and image or audio endpoints (Gemini 3 Pro is
offered there only as an image model). A batch-only model appears only as a
``:batch`` id, so it is left out with them.

Prints one catalog id per line, in OpenRouter's order (newest first). Fail-open:
a fetch or parse failure prints nothing and exits 0, so the refresh keeps the
committed list.

With ``--context-windows PATH`` it also writes each catalogued model's context
window (OpenRouter's ``context_length``, the largest of its routes) to PATH,
docs/context-windows.json in the catalog cron: the scorer leaves out a model
whose window cannot hold the material a task gives it to read. A model
OpenRouter stops listing keeps its last known window.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

UPDATE_DIR = Path(__file__).resolve().parent
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

from build_catalog import _parse_attrs  # noqa: E402
from selector_re import MODEL_RE  # noqa: E402

REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
MAP_PATH = UPDATE_DIR / "openrouter-model-map.json"
CONTEXT_PATH = REPO_ROOT / "docs" / "context-windows.json"
MODELS_URL = "https://openrouter.ai/api/v1/models"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)


def normalize(text: str) -> str:
    """A model name compared spelling-free: lower case, dots, spaces and
    underscores as dashes ("Claude Sonnet 5.5" -> "claude-sonnet-5-5")."""
    return re.sub(r"-{2,}", "-", re.sub(r"[\s_.]+", "-", text.strip().lower())).strip("-")


def _keys(text: str) -> set[str]:
    key = normalize(text)
    return {key, key.removeprefix("claude-")} if key else set()


def catalog_keys(selector_text: str) -> dict[str, set[str]]:
    """Each unretired ``<model>`` id -> the keys it answers to: its id and its
    display name, normalized, with and without a leading "claude-"."""
    options = _OPTIONS_RE.search(selector_text)
    if options is None:
        return {}
    out: dict[str, set[str]] = {}
    for m in MODEL_RE.finditer(options.group(1)):
        attrs = _parse_attrs(m.group(1))
        mid = attrs.get("id", "")
        if not mid or attrs.get("retired-on"):
            continue
        out[mid] = _keys(mid) | _keys(attrs.get("name", ""))
    return out


def routable(entry: dict[str, Any]) -> bool:
    """A chat route for a text model: no ``:batch`` variant, no ``~`` alias,
    and text out (image and audio endpoints are other models)."""
    ident = str(entry.get("id", ""))
    if not ident or ident.startswith("~") or ident.endswith(":batch"):
        return False
    arch = entry.get("architecture")
    outputs = arch.get("output_modalities") if isinstance(arch, dict) else None
    if isinstance(outputs, list):
        return "text" in outputs and "image" not in outputs and "audio" not in outputs
    return True


def openrouter_keys(entry: dict[str, Any]) -> set[str]:
    """The keys an OpenRouter model answers to: its id without the maker
    prefix or a ``:variant`` suffix, and its name without the "Maker: " lead."""
    ident = str(entry.get("id", "")).split("/", 1)[-1].split(":", 1)[0]
    name = str(entry.get("name", ""))
    name = name.split(": ", 1)[1] if ": " in name else name
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # "(batch)", "(free)"
    return _keys(ident) | _keys(name)


def map_entries(
    entries: list[dict[str, Any]], selector_text: str, exceptions: dict[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    """Each routable OpenRouter entry that maps to a catalog id, paired with
    that id, in OpenRouter's order. An exception maps an OpenRouter id
    (``:variant`` dropped) to a catalog id directly; otherwise a model maps
    when its keys meet exactly one catalog model's."""
    catalog = catalog_keys(selector_text)
    by_key: dict[str, set[str]] = {}
    for mid, keys in catalog.items():
        for key in keys:
            by_key.setdefault(key, set()).add(mid)
    out: list[tuple[str, dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not routable(entry):
            continue
        base_id = str(entry.get("id", "")).split(":", 1)[0]
        if base_id in exceptions:
            hit: str | None = exceptions[base_id] if exceptions[base_id] in catalog else None
        else:
            matches = set().union(*(by_key.get(k, set()) for k in openrouter_keys(entry)))
            hit = next(iter(matches)) if len(matches) == 1 else None
        if hit:
            out.append((hit, entry))
    return out


def map_models(
    entries: list[dict[str, Any]], selector_text: str, exceptions: dict[str, str]
) -> list[str]:
    """The catalog ids OpenRouter routes, in its order, each once
    (:func:`map_entries`)."""
    return list(dict.fromkeys(mid for mid, _ in map_entries(entries, selector_text, exceptions)))


def context_windows(
    entries: list[dict[str, Any]], selector_text: str, exceptions: dict[str, str]
) -> dict[str, int]:
    """Each catalog id OpenRouter routes -> the largest context window (in
    tokens) its routes list."""
    out: dict[str, int] = {}
    for mid, entry in map_entries(entries, selector_text, exceptions):
        top = entry.get("top_provider")
        n = entry.get("context_length") or (
            top.get("context_length") if isinstance(top, dict) else None
        )
        if isinstance(n, int) and n > 0:
            out[mid] = max(out.get(mid, 0), n)
    return dict(sorted(out.items()))


def write_context_windows(path: Path, windows: dict[str, int]) -> bool:
    """Merge ``windows`` into the file at ``path`` (a model no longer listed
    keeps its last known window); True when the file changed."""
    try:
        existing = json.loads(path.read_text()).get("models", {})
    except (OSError, ValueError, AttributeError):
        existing = {}
    merged = {**(existing if isinstance(existing, dict) else {}), **windows}
    doc = {
        "_comment": (
            "Each catalogued model's context window in tokens: OpenRouter's context_length, "
            "the largest of its routes (update/extract_openrouter_models.py --context-windows, "
            "run by the catalog cron). A surface may cap a model lower."
        ),
        "source": MODELS_URL,
        "models": dict(sorted(merged.items())),
    }
    text = json.dumps(doc, indent=2) + "\n"
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def load_exceptions(path: Path = MAP_PATH) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, dict):
        return {}
    return {str(k): str(v) for k, v in models.items() if isinstance(v, str)}


def fetch_entries(url: str = MODELS_URL) -> list[dict[str, Any]]:
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT, allow_redirects=True
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("no `data` list in the OpenRouter models response")
    return [e for e in data if isinstance(e, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catalog ids OpenRouter routes.")
    parser.add_argument(
        "--input", type=Path, default=None, help="read the models JSON from a file (for tests)"
    )
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH)
    parser.add_argument(
        "--context-windows",
        type=Path,
        default=None,
        help="also write each catalogued model's context window to this JSON file",
    )
    args = parser.parse_args(argv)
    try:
        if args.input is not None:
            entries = [e for e in json.loads(args.input.read_text())["data"] if isinstance(e, dict)]
        else:
            entries = fetch_entries()
    except Exception as exc:  # noqa: BLE001 - fail open: the committed list stands
        print(
            f"extract_openrouter_models: fetch failed ({exc!r}); nothing to sync", file=sys.stderr
        )
        return 0
    selector = args.selector.read_text()
    ids = map_models(entries, selector, load_exceptions())
    print(f"extract_openrouter_models: {len(ids)} catalogued models routed", file=sys.stderr)
    if args.context_windows is not None:
        windows = context_windows(entries, selector, load_exceptions())
        changed = write_context_windows(args.context_windows, windows)
        print(
            f"extract_openrouter_models: {len(windows)} context windows"
            f"{' written' if changed else ' unchanged'}",
            file=sys.stderr,
        )
    for mid in ids:
        print(mid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
