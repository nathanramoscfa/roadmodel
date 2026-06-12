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
import re
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


# --------------------------------------------------------------------------- #
# De-clobber overlay. The Cursor cron does a full-file Opus rewrite of the
# selector from Cursor's pricing page, which would drop a provider-direct model
# (e.g. DeepSeek) that isn't on that page. The provider-direct <model> elements —
# with their editorial tier ratings — live in the committed selector; this
# overlay forces each provider-direct id's element in the CURRENT (post-Opus)
# selector to match the BASE (committed, pre-Opus) selector. Idempotent; a no-op
# when no provider-direct id exists in the base.
# --------------------------------------------------------------------------- #

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_TIER_BLOCK_RE = re.compile(r'(<tier\s+cost="([^"]+)"\s*>)(.*?)(</tier>)', re.DOTALL)


def _element_re(mid: str) -> re.Pattern[str]:
    """Match a full, indented ``<model ... id="mid" ... />`` element.

    A model element contains no ``>`` until its closing ``/>``, so ``[^>]*?``
    safely spans its multi-line attributes without crossing into a sibling.
    """
    return re.compile(
        r'^[ \t]*<model\s+[^>]*?\bid="' + re.escape(mid) + r'"[^>]*?/>[ \t]*$',
        re.MULTILINE,
    )


def extract_element(selector_text: str, mid: str) -> str | None:
    m = _element_re(mid).search(selector_text)
    return m.group(0) if m else None


def _element_tier(selector_text: str, mid: str) -> str | None:
    options = _OPTIONS_RE.search(selector_text)
    if not options:
        return None
    for tier_m in _TIER_BLOCK_RE.finditer(options.group(1)):
        if _element_re(mid).search(tier_m.group(3)):
            return tier_m.group(2)
    return None


def provider_direct_ids(snapshots: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for snap in snapshots:
        for model in snap.get("models", []):
            mid = str(model.get("id", "")).strip()
            if mid:
                ids.add(mid)
    return ids


def _insert_into_tier(selector_text: str, element: str, tier_cost: str) -> str | None:
    """Insert ``element`` as the last model of the ``tier_cost`` block."""
    inserted = False

    def _sub_tier(tier_m: re.Match[str]) -> str:
        nonlocal inserted
        if inserted or tier_m.group(2) != tier_cost:
            return tier_m.group(0)
        inserted = True
        body = tier_m.group(3).rstrip()  # drop the trailing "\n    " before </tier>
        return tier_m.group(1) + body + "\n" + element + "\n    " + tier_m.group(4)

    def _sub_options(opt_m: re.Match[str]) -> str:
        return (
            "<model-options>" + _TIER_BLOCK_RE.sub(_sub_tier, opt_m.group(1)) + "</model-options>"
        )

    new_text = _OPTIONS_RE.sub(_sub_options, selector_text, count=1)
    return new_text if inserted else None


def apply_overlay(current: str, base: str, ids: set[str]) -> tuple[str, list[str], list[str]]:
    """Force each provider-direct id's ``<model>`` element in ``current`` to match
    ``base`` (insert if missing, replace if it drifted). Returns
    ``(new_current, applied_ids, flags)``. Ids absent from ``base`` are skipped —
    there is nothing authoritative to protect yet."""
    applied: list[str] = []
    flags: list[str] = []
    for mid in sorted(ids):
        base_el = extract_element(base, mid)
        if base_el is None:
            continue
        cur_el = extract_element(current, mid)
        if cur_el == base_el:
            continue
        if cur_el is not None:
            current = _element_re(mid).sub(lambda _m: base_el, current, count=1)
            applied.append(mid)
            continue
        tier = _element_tier(base, mid)
        if tier is None:
            flags.append(f"overlay: {mid!r} is in base but its <tier> block could not be located")
            continue
        new_current = _insert_into_tier(current, base_el, tier)
        if new_current is None:
            flags.append(f"overlay: could not insert {mid!r} into <tier cost={tier!r}>")
            continue
        current = new_current
        applied.append(mid)
    return current, applied, flags


def _run_report(selector_path: Path) -> int:
    base = base_models(selector_path.read_text())
    snaps = provider_snapshots()
    composed, flags = compose(base, snaps)
    additions = proposed_additions(base, snaps)
    provider_direct = sorted(m.id for m in composed.values() if m.source != "cursor")
    print(
        f"merge_catalog: {len(composed)} models composed; "
        f"{len(provider_direct)} provider-direct, {len(additions)} not-yet-in-selector."
    )
    for mid in provider_direct:
        cm = composed[mid]
        print(f"  provider-direct: {mid} (source={cm.source}, tier={cm.cost_tier})")
    if flags:
        print("merge_catalog: composition flags:", file=sys.stderr)
        for f in flags:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


def _run_write(selector_path: Path, base_path: Path) -> int:
    current = selector_path.read_text()
    base = base_path.read_text()
    ids = provider_direct_ids(provider_snapshots())
    new_current, applied, flags = apply_overlay(current, base, ids)
    for f in flags:
        print(f"merge_catalog: {f}", file=sys.stderr)
    if new_current != current:
        selector_path.write_text(new_current)
        print(f"merge_catalog: overlay re-applied provider-direct element(s): {applied}")
    else:
        print(
            f"merge_catalog: overlay no-op ({len(ids)} provider-direct id(s); "
            "none needed re-applying)"
        )
    return 1 if flags else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose (report) / overlay (--write) the federated model registry."
    )
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH)
    parser.add_argument(
        "--write",
        action="store_true",
        help="De-clobber overlay: force provider-direct <model> elements in "
        "--selector to match --base.",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Base (committed, pre-Opus) selector to take provider-direct elements "
        "from. With --write; defaults to --selector itself (a self no-op) when omitted.",
    )
    args = parser.parse_args()

    if args.write:
        return _run_write(args.selector, args.base if args.base is not None else args.selector)
    return _run_report(args.selector)


if __name__ == "__main__":
    raise SystemExit(main())
