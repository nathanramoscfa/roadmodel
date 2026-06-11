"""Compose the model registry from per-provider catalog snapshots (Phase 4.6).

Federation chassis. Reads every committed ``update/catalog-<provider>.json``
(provider-direct pricing facts) plus the current ``<model-options>`` base (the
Cursor-sourced fallback, until per-provider migration completes), and composes a
single registry view keyed by canonical model id, applying the **precedence
rule** (a provider-direct snapshot wins over the Cursor base) and canonical-id
de-dup. The cost *tier* bucket is derived here from the output price per the
documented boundaries in ``docs/model-tier-cost-scale.md``.

SCOPE — Phase 4.6 T2 (additive): this module computes and REPORTS the composition
and the proposed ``<model-options>`` additions; it does NOT write
``docs/model-selector.txt`` or the cost-scale doc, and is NOT yet wired into the
Cursor cron. The production wiring — rendering provider-direct models into
``<model-options>`` (which also needs editorial tier ratings) plus a merge-overlay
step in ``update-models.yml`` so the weekly Cursor refresh does not clobber
provider-direct models — is the next slice. See
``private/phase04.6-catalog-federation-roadmap.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Sibling import (update/ is not a package) — mirror check_gemini_source.py.
_UPDATE_DIR = Path(__file__).resolve().parent
if str(_UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_UPDATE_DIR))
# E402/I001 are expected after the path guard above.
from build_catalog import _parse_models  # noqa: E402, I001

REPO_ROOT = _UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"

# Jurisdiction codes accepted by the selector's <jurisdiction-context>.
VALID_JURISDICTIONS = frozenset({"us", "eu", "uk", "ca", "au", "jp", "kr", "cn", "ru", "unknown"})


class MergeError(RuntimeError):
    """A catalog snapshot or composition is malformed."""


def cost_tier_for_output_price(price: float) -> str:
    """Output-price -> cost tier, per docs/model-tier-cost-scale.md boundaries.

    Low < $10; Medium $10-14.99; High $15-24.99; Very High >= $25. Inclusive on
    the lower bound of each tier.
    """
    if price < 10:
        return "low"
    if price < 15:
        return "medium"
    if price < 25:
        return "high"
    return "very-high"


@dataclass
class ComposedModel:
    """One model in the composed registry."""

    id: str
    source: str  # "cursor" (base fallback) | a provider name (provider-direct)
    facts: dict[str, Any]  # canonical facts from the winning source
    cost_tier: str | None  # derived from output price when known


def provider_snapshots(update_dir: Path = _UPDATE_DIR) -> list[dict[str, Any]]:
    """Every committed ``catalog-<provider>.json`` snapshot, sorted by path."""
    snaps: list[dict[str, Any]] = []
    for path in sorted(update_dir.glob("catalog-*.json")):
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise MergeError(f"catalog snapshot is not a JSON object: {path}")
        snaps.append(data)
    return snaps


def base_models(selector_text: str) -> dict[str, dict[str, Any]]:
    """The current ``<model-options>`` models keyed by id (the Cursor fallback)."""
    return {m["id"]: m for m in _parse_models(selector_text)}


def _tier_from_facts(facts: dict[str, Any]) -> str | None:
    out = facts.get("output_price_per_1m")
    if isinstance(out, (int, float)):
        return cost_tier_for_output_price(float(out))
    tier = facts.get("tier_cost")
    return str(tier) if tier else None


def compose(
    base: dict[str, dict[str, Any]], snapshots: list[dict[str, Any]]
) -> tuple[dict[str, ComposedModel], list[str]]:
    """Compose base + provider-direct snapshots into one registry view.

    Returns ``(composed, flags)``. Precedence: a provider-direct snapshot model
    overlays (or adds to) the Cursor base. A canonical id claimed by TWO
    provider-direct sources is a decision-4a conflict (flagged; the second is not
    applied). ``flags`` non-empty means a hard conformance failure.
    """
    flags: list[str] = []
    composed: dict[str, ComposedModel] = {
        mid: ComposedModel(id=mid, source="cursor", facts=m, cost_tier=_tier_from_facts(m))
        for mid, m in base.items()
    }

    claimed_by: dict[str, str] = {}
    for snap in snapshots:
        provider = str(snap.get("provider", "")) or "<unknown>"
        models = snap.get("models", [])
        if not isinstance(models, list):
            flags.append(f"snapshot for {provider!r} has a non-list 'models'")
            continue
        for model in models:
            mid = str(model.get("id", "")).strip()
            if not mid:
                flags.append(f"snapshot for {provider!r} has a model with no id")
                continue
            if mid in claimed_by:
                flags.append(
                    f"check 4a (catalog): model {mid!r} is claimed by two provider-direct "
                    f"sources ({claimed_by[mid]} and {provider}) — exactly one source must "
                    f"own a model's canonical facts"
                )
                continue
            claimed_by[mid] = provider
            composed[mid] = ComposedModel(
                id=mid, source=provider, facts=model, cost_tier=_tier_from_facts(model)
            )
    return composed, flags


def proposed_additions(
    base: dict[str, dict[str, Any]], snapshots: list[dict[str, Any]]
) -> list[str]:
    """Provider-direct model ids not yet present in the ``<model-options>`` base.

    These are the models the wiring slice will render INTO ``<model-options>``
    (each also needs editorial tier ratings before it is recommendable).
    """
    base_ids = set(base)
    additions: set[str] = set()
    for snap in snapshots:
        for model in snap.get("models", []):
            mid = str(model.get("id", "")).strip()
            if mid and mid not in base_ids:
                additions.add(mid)
    return sorted(additions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose the federated model registry (report).")
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH)
    args = parser.parse_args()

    base = base_models(args.selector.read_text())
    snaps = provider_snapshots()
    composed, flags = compose(base, snaps)
    additions = proposed_additions(base, snaps)

    provider_direct = sorted(m.id for m in composed.values() if m.source != "cursor")
    print(
        f"merge_catalog: {len(composed)} models composed; "
        f"{len(provider_direct)} provider-direct, {len(additions)} proposed addition(s)."
    )
    for mid in provider_direct:
        cm = composed[mid]
        print(f"  provider-direct: {mid} (source={cm.source}, tier={cm.cost_tier})")
    if additions:
        print(f"  proposed <model-options> additions (need editorial tier ratings): {additions}")
    if flags:
        print("merge_catalog: composition flags:", file=sys.stderr)
        for f in flags:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
