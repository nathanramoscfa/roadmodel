"""Offline catalog-federation conformance gate (Phase 4.6).

Validates the committed provider-direct catalog snapshots
(``update/catalog-<provider>.json``) and their composition against the
``<model-options>`` base. Reads COMMITTED files and makes NO network call (the
per-PR ``test`` job has no network) — the sibling of
``update/validate_effort_conformance.py`` for the catalog lane.

Checks:
  G1. Snapshot schema. Each ``catalog-<provider>.json`` has a non-empty
      ``provider``; a ``jurisdiction`` in the selector's valid set; a non-empty
      ``models`` list; per model a non-empty ``id`` + positive numeric
      input/output price (cache-read, when present, positive); a ``slug_to_id``
      map covering every model slug; a list ``unexpected_slugs``; and a 64-hex
      ``section_sha256``.
  G2. Cost-tier derivability. Every model's output price maps to a documented
      cost tier (low/medium/high/very-high) via the cost-scale boundaries.
  G3. Composition integrity (decision 4a). ``merge_catalog.compose`` over the
      committed base + snapshots produces NO conflict flags (no canonical id
      claimed by two provider-direct sources).

Exit codes: 0 PASS, 1 conformance failure, 2 input/config error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Sibling import (update/ is not a package) — reuse the single composition engine.
_UPDATE_DIR = Path(__file__).resolve().parent
if str(_UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_UPDATE_DIR))
# E402/I001 are expected after the path guard above.
from merge_catalog import (  # noqa: E402, I001
    VALID_JURISDICTIONS,
    base_models,
    compose,
    cost_tier_for_output_price,
)

REPO_ROOT = _UPDATE_DIR.parent
DEFAULT_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_VALID_TIERS = {"low", "medium", "high", "very-high"}


class ConfigError(RuntimeError):
    """An input file was missing or malformed."""


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def check_snapshot_schema(path: Path, snap: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    name = path.name

    if not str(snap.get("provider", "")).strip():
        failures.append(f"G1 ({name}): missing/empty 'provider'")
    juris = str(snap.get("jurisdiction", ""))
    if juris not in VALID_JURISDICTIONS:
        failures.append(f"G1 ({name}): jurisdiction {juris!r} not in {sorted(VALID_JURISDICTIONS)}")

    models = snap.get("models")
    if not isinstance(models, list) or not models:
        failures.append(f"G1 ({name}): 'models' must be a non-empty list")
        models = []

    slug_to_id = snap.get("slug_to_id")
    slug_to_id = slug_to_id if isinstance(slug_to_id, dict) else {}

    for model in models:
        mid = str(model.get("id", "")).strip()
        if not mid:
            failures.append(f"G1 ({name}): a model has no 'id'")
            continue
        if not _is_positive_number(model.get("input_price_per_1m")):
            failures.append(f"G1 ({name}): {mid} input_price_per_1m must be a positive number")
        out = model.get("output_price_per_1m")
        if not _is_positive_number(out):
            failures.append(f"G1 ({name}): {mid} output_price_per_1m must be a positive number")
        else:
            # G2 — output price must map to a documented cost tier.
            if cost_tier_for_output_price(float(out)) not in _VALID_TIERS:
                failures.append(f"G2 ({name}): {mid} output price {out} maps to no documented tier")
        cache = model.get("cache_read_per_1m")
        if cache is not None and not _is_positive_number(cache):
            failures.append(f"G1 ({name}): {mid} cache_read_per_1m, when present, must be positive")
        slug = str(model.get("slug", mid))
        if slug not in slug_to_id:
            failures.append(f"G1 ({name}): slug {slug!r} missing from slug_to_id map")

    if not isinstance(snap.get("unexpected_slugs"), list):
        failures.append(f"G1 ({name}): 'unexpected_slugs' must be a list")
    if not _HEX64_RE.match(str(snap.get("section_sha256", ""))):
        failures.append(f"G1 ({name}): 'section_sha256' must be 64 hex chars")
    return failures


def run_checks(selector_text: str, snapshot_paths: list[Path]) -> list[str]:
    failures: list[str] = []
    snapshots: list[dict[str, Any]] = []
    for path in snapshot_paths:
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            failures.append(f"G1 ({path.name}): not valid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            failures.append(f"G1 ({path.name}): snapshot must be a JSON object")
            continue
        snapshots.append(data)
        failures += check_snapshot_schema(path, data)

    # G3 — composition integrity (decision 4a): no id claimed by two sources.
    base = base_models(selector_text)
    _, flags = compose(base, snapshots)
    failures += [f"G3 (composition): {flag}" for flag in flags]
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Conformance gate: provider-direct catalog snapshots + composition."
    )
    parser.add_argument("--selector", type=Path, default=DEFAULT_SELECTOR)
    parser.add_argument(
        "--snapshots",
        type=Path,
        nargs="*",
        default=None,
        help="catalog-<provider>.json files (default: every update/catalog-*.json)",
    )
    args = parser.parse_args()

    try:
        selector_text = args.selector.read_text()
    except FileNotFoundError as exc:
        print(f"validate_catalog_conformance: config error: {exc}", file=sys.stderr)
        return 2

    snapshot_paths = (
        sorted(args.snapshots)
        if args.snapshots is not None
        else sorted(_UPDATE_DIR.glob("catalog-*.json"))
    )
    if not snapshot_paths:
        print(
            "validate_catalog_conformance: no catalog-*.json provider snapshots found",
            file=sys.stderr,
        )
        return 2

    failures = run_checks(selector_text, snapshot_paths)
    if failures:
        print(f"validate_catalog_conformance: {len(failures)} failure(s):", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    print(
        f"validate_catalog_conformance: PASS ({len(snapshot_paths)} provider-direct "
        "catalog snapshot(s): schema well-formed; prices positive; output prices map to "
        "documented cost tiers; composition has no two-source id conflict)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
