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
  G4. Price provenance. For every provider-direct snapshot model that ALSO exists
      in ``<model-options>``, the selector's input/output price must EQUAL the
      provider-direct snapshot's. This makes the provider's OWN page authoritative
      for its prices (decision 1) — Cursor's pricing-page mirror can no longer be
      the authority; a Cursor↔provider divergence fails this gate so a human
      reconciles the selector to the provider-direct truth.
  G5. Price COVERAGE (advisory, not fatal). The inverse of G4. G4 walks SNAPSHOT
      models, so a ``<model-options>`` model ABSENT from its own maker's snapshot
      is invisible to it: G4 passes for lack of anything to compare, not because
      the price agreed. G5 names those models, so "unverified" is distinguishable
      from "verified". Claude Opus 5 shipped exactly this way — catalogued at
      $5/$25 from the aggregator mirror while Anthropic's own pricing page still
      listed five models and no Opus 5.

      Advisory on purpose: a provider legitimately ships a model before pricing
      it publicly, and failing the gate would block the whole catalog refresh on
      an upstream publishing lag — recreating the deadlock class that stranded
      the Codex lane (#517). ``--strict-provenance`` escalates the notes to
      failures for callers that want it fatal. The catalog cron folds them into
      its PR body's Warnings section so they get human eyes at review time.

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
from build_catalog import _parse_access_methods  # noqa: E402, I001
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

    # A provider that ships a NEW model puts it in `models` (id falls back to
    # the slug) and names it in `unexpected_slugs` — the flag-only discovery
    # path, which opens a tracking issue and waits for editorial tier ratings
    # before the model becomes recommendable. Requiring slug_to_id to cover it
    # made that flag FATAL: `deepseek-v4-flash-vision-exp` appeared on
    # 2026-08-24 and every catalog refresh after it died here, so one unrated
    # provider model halted all curation. The invariant worth keeping is that
    # no slug is SILENTLY unmapped — an explicitly flagged one is accounted
    # for, and G4 still ignores it because it is not in <model-options>.
    flagged_raw = snap.get("unexpected_slugs")
    flagged = {str(s) for s in flagged_raw} if isinstance(flagged_raw, list) else set()

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
        if slug not in slug_to_id and slug not in flagged and mid not in flagged:
            failures.append(
                f"G1 ({name}): slug {slug!r} is neither in slug_to_id nor declared "
                "in unexpected_slugs"
            )

    if not isinstance(snap.get("unexpected_slugs"), list):
        failures.append(f"G1 ({name}): 'unexpected_slugs' must be a list")
    overlay_mode = snap.get("overlay_mode")
    if overlay_mode is not None and overlay_mode not in ("whole-element", "price-only"):
        failures.append(
            f"G1 ({name}): overlay_mode {overlay_mode!r} must be 'whole-element' or 'price-only'"
        )
    if not _HEX64_RE.match(str(snap.get("section_sha256", ""))):
        failures.append(f"G1 ({name}): 'section_sha256' must be 64 hex chars")
    return failures


def check_price_provenance(
    base: dict[str, dict[str, Any]], snapshots: list[dict[str, Any]]
) -> list[str]:
    """G4 — the provider-direct snapshot is authoritative for a model's price.

    For each snapshot model that is ALSO in ``<model-options>``, the selector's
    input/output price must EQUAL the snapshot's. Models not yet in the selector
    are skipped (nothing to reconcile yet).
    """
    failures: list[str] = []
    for snap in snapshots:
        provider = str(snap.get("provider", "?"))
        models = snap.get("models", [])
        if not isinstance(models, list):
            continue
        for model in models:
            mid = str(model.get("id", ""))
            if mid not in base:
                continue
            sel = base[mid]
            for field, label in (
                ("input_price_per_1m", "input"),
                ("output_price_per_1m", "output"),
            ):
                snap_v = model.get(field)
                sel_v = sel.get(field)
                if not isinstance(snap_v, (int, float)) or not isinstance(sel_v, (int, float)):
                    continue
                if round(float(snap_v), 6) != round(float(sel_v), 6):
                    failures.append(
                        f"G4 (price provenance): {provider} model {mid!r} {label} price: "
                        f"selector=${sel_v} but the provider-direct source says ${snap_v} — "
                        f"Cursor's mirror has drifted from {provider}'s own page; reconcile "
                        f"the selector to the provider-direct price"
                    )
    return failures


def _model_makers(selector_text: str) -> dict[str, str]:
    """Map each ``<model-options>`` id to its MAKER provider.

    Mirrors ``roadmodel.cost.model_provider``: the maker is the provider of a
    first-party access method supporting the model, excluding pool aggregators
    (a model reachable via both its own provider's API and Cursor's pool is made
    by the former). Reimplemented here rather than imported so ``update/`` stays
    standalone. Models with no unambiguous first-party maker are omitted, which
    makes them invisible to G5 — deliberately, since "which provider should have
    published this price" has no answer for them.
    """
    aggregators = {"cursor"}
    supporters: dict[str, set[str]] = {}
    for method in _parse_access_methods(selector_text):
        provider = str(method.get("provider") or "")
        if not provider:
            continue
        for mid in method.get("supports_models", []):
            supporters.setdefault(str(mid), set()).add(provider)
    makers: dict[str, str] = {}
    for mid, provs in supporters.items():
        first_party = provs - aggregators
        if len(first_party) == 1:
            makers[mid] = next(iter(first_party))
    return makers


def check_price_coverage(
    selector_text: str, base: dict[str, dict[str, Any]], snapshots: list[dict[str, Any]]
) -> list[str]:
    """G5 — report selector models their own provider's snapshot does not price.

    G4 walks SNAPSHOT models and reconciles the ones that reached the selector.
    The inverse case is invisible to it: a model in ``<model-options>`` whose
    maker HAS a provider-direct snapshot, but which does not appear in that
    snapshot. Its price came from Cursor's mirror alone and was never
    cross-checked — G4 passes not because the price agrees but because there was
    nothing to compare it against.

    Claude Opus 5 shipped exactly this way: catalogued at $5/$25 from Cursor's
    page while Anthropic's own pricing docs still listed five models and no Opus
    5, so ``catalog-anthropic.json`` had no row to reconcile.

    Reported, never fatal. A provider legitimately ships a model before pricing
    it publicly, and failing the gate would block the whole catalog refresh on an
    upstream publishing lag — recreating the deadlock class that stranded the
    Codex lane (#517). The point is that "unverified" stops being *silent*.
    """
    makers = _model_makers(selector_text)
    priced: dict[str, set[str]] = {}
    for snap in snapshots:
        provider = str(snap.get("provider", ""))
        models = snap.get("models", [])
        if not provider or not isinstance(models, list):
            continue
        priced.setdefault(provider, set()).update(
            str(m.get("id", "")) for m in models if isinstance(m, dict)
        )

    notes: list[str] = []
    for mid in sorted(base):
        maker = makers.get(mid)
        if maker is None or maker not in priced:
            # No maker, or that maker publishes no snapshot at all — nothing
            # was claimed to be verified, so there is no false assurance.
            continue
        if mid in priced[maker]:
            continue
        sel = base[mid]
        notes.append(
            f"G5 (price coverage): {mid!r} is priced "
            f"${sel.get('input_price_per_1m')}/${sel.get('output_price_per_1m')} per Mtok "
            f"from the aggregator mirror only — {maker} publishes a provider-direct "
            f"snapshot but does not list this model, so G4 had nothing to reconcile "
            f"and the price is UNVERIFIED against {maker}'s own page"
        )
    return notes


def check_benched_models_still_exist(selector_text: str, base: dict[str, Any]) -> list[str]:
    """G6. Every benched model id must still be in ``<model-options>``.

    ``infra/model-availability.json`` benches a CATALOGUED model so the runtime
    Step-0a override can exclude it without a package release. If a refresh
    retires a model that is still on that list, the override silently starts
    referencing an id the catalog no longer has: the bench becomes a no-op, and
    a model that was pulled for export-control or access reasons is quietly
    recommendable again.

    Mandatory supersession (2026-09-05) makes that reachable for the first
    time — before it, retirement was optional and rare.
    """
    availability = REPO_ROOT / "infra" / "model-availability.json"
    if not availability.exists():
        return []
    try:
        data = json.loads(availability.read_text())
    except json.JSONDecodeError as exc:
        return [f"G6 (availability): infra/model-availability.json is not valid JSON ({exc})"]
    benched = data.get("unavailable")
    if not isinstance(benched, list):
        return ["G6 (availability): 'unavailable' must be a list"]
    failures = []
    for entry in benched:
        mid = entry.get("id") if isinstance(entry, dict) else entry
        if mid and str(mid) not in base:
            failures.append(
                f"G6 (availability): benched model {str(mid)!r} is no longer in "
                "<model-options> — the runtime bench now references an id the catalog "
                "does not carry, so the exclusion silently stops applying. Either keep "
                "the model or un-bench it deliberately."
            )
    return failures


def run_checks(selector_text: str, snapshot_paths: list[Path]) -> tuple[list[str], list[str]]:
    """Returns ``(failures, notes)``.

    ``failures`` are fatal (G1-G4). ``notes`` are G5 price-coverage advisories:
    real information, but never a reason to block a refresh — see
    :func:`check_price_coverage`.
    """
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

    # G4 — price provenance: selector prices match the provider-direct source.
    failures += check_price_provenance(base, snapshots)

    # G6 — a benched model must still exist to be benched.
    failures += check_benched_models_still_exist(selector_text, base)

    # G5 — price COVERAGE: which selector prices G4 could not check at all.
    notes = check_price_coverage(selector_text, base, snapshots)
    return failures, notes


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
    parser.add_argument(
        "--strict-provenance",
        action="store_true",
        help=(
            "escalate G5 price-coverage notes to failures. Off by default: a "
            "provider legitimately ships a model before pricing it publicly, and "
            "blocking the catalog refresh on an upstream publishing lag would "
            "strand the lane."
        ),
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

    failures, notes = run_checks(selector_text, snapshot_paths)
    if args.strict_provenance:
        failures += notes
        notes = []

    if failures:
        print(f"validate_catalog_conformance: {len(failures)} failure(s):", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    # G5 notes print on the PASS path so the cron log and the PR body both carry
    # them. An unverified price is not a defect — leaving it unsaid is.
    if notes:
        print(f"validate_catalog_conformance: {len(notes)} price-coverage note(s):")
        for msg in notes:
            print(f"  - {msg}")

    print(
        f"validate_catalog_conformance: PASS ({len(snapshot_paths)} provider-direct "
        "catalog snapshot(s): schema well-formed; prices positive; output prices map to "
        "documented cost tiers; composition has no two-source id conflict; selector prices "
        f"match the provider-direct source for every migrated model; {len(notes)} model(s) "
        "priced from the aggregator mirror only)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
