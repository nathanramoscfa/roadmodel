"""Compose the model registry from per-provider catalog snapshots (Phase 4.6).

Federation chassis. Reads every committed ``update/catalog-<provider>.json``
(provider-direct pricing facts) plus the current ``<model-options>`` base (the
Cursor-sourced fallback, until per-provider migration completes), and composes a
single registry view keyed by canonical model id, applying the **precedence
rule** (a provider-direct snapshot wins over the Cursor base) and canonical-id
de-dup. The cost *tier* bucket is derived here from the output price per the
documented boundaries in ``docs/model-tier-cost-scale.md``.

SCOPE. ``--write`` (the de-clobber overlay, wired into ``update-models.yml`` after
the Opus refresh) deterministically reconciles every provider-direct model's facts
post-Opus so the daily Cursor refresh never clobbers them and the conformance gate
stays green BY CONSTRUCTION:
  1. whole-element providers (off-Cursor, e.g. DeepSeek, which the Opus rewrite
     drops): re-add the entire ``<model>`` element from the committed base.
  2. price overlay (ALL provider-direct ids): force ``input-price-per-1m`` /
     ``output-price-per-1m`` in ``docs/model-selector.txt`` to the provider-direct
     SNAPSHOT price — so a provider price change auto-flows and Opus can never
     author a price the G4 price-provenance gate would reject (Phase 4.6 T4
     deterministic backstop).
  3. cost-scale price overlay (provider-direct ids that are also cost-scale-tracked
     in ``build_catalog.SELECTOR_TO_COST_SCALE_NAME``): force the matching
     Input / Output cells in ``docs/model-tier-cost-scale.md`` to the same snapshot
     price, keeping the cross-doc price invariant
     (``test_selector_pricing_matches_cost_scale_pricing``) green.
Every overlay is numeric-compare-before-replace, so it is a strict no-op when the
docs already match the snapshots (today's state) — byte-stable. Without ``--write``
the module only REPORTS the composition + proposed additions.
See ``private/phase04.6-catalog-federation-roadmap.md``.
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
from build_catalog import SELECTOR_TO_COST_SCALE_NAME, _parse_models  # noqa: E402, I001
from selector_re import model_element_re  # noqa: E402, I001

REPO_ROOT = _UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"

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

    This used to assume "a model element contains no ``>`` until its closing
    ``/>``". Provider prose disproved it: GPT-5.6's pricing note says Fast mode
    covers "long context (>272k)", and the overlay then could not find those
    elements — so it silently stopped forcing provider-direct prices onto them,
    a price-integrity hole rather than a display bug. The quote-aware pattern
    is shared in update/selector_re.py.
    """
    return model_element_re(mid)


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
    """Ids the de-clobber overlay force-applies: ONLY ``overlay_mode ==
    "whole-element"`` snapshots (off-Cursor providers like DeepSeek that the cron
    would drop). ``price-only`` providers (on Cursor's page, e.g. Anthropic) keep
    their Cursor-maintained elements and are gated on price by G4, NOT overlaid —
    forcing them would freeze their benchmark-derived tier ratings. A snapshot
    with no ``overlay_mode`` is treated as price-only (safe default: not forced)."""
    ids: set[str] = set()
    for snap in snapshots:
        if snap.get("overlay_mode") != "whole-element":
            continue
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
            # Direct string replace (cur_el is an exact substring) — avoids a
            # regex-replacement lambda that would close over the loop var (B023)
            # and sidesteps backslash/backref expansion in the replacement.
            current = current.replace(cur_el, base_el, 1)
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


def snapshot_price_map(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """``id -> {"input": float, "output": float}`` from every provider-direct
    snapshot. G3 (composition) guarantees no canonical id is claimed by two
    sources, so a flat map is unambiguous."""
    prices: dict[str, dict[str, float]] = {}
    for snap in snapshots:
        models = snap.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            mid = model.get("id")
            inp = model.get("input_price_per_1m")
            out = model.get("output_price_per_1m")
            if (
                isinstance(mid, str)
                and isinstance(inp, (int, float))
                and isinstance(out, (int, float))
            ):
                prices[mid] = {"input": float(inp), "output": float(out)}
    return prices


def _fmt_price(value: float) -> str:
    """Format a numeric price as the docs' ``$X.XX`` convention: at least two
    decimals, trailing zeros beyond the second stripped (so 0.435 -> ``$0.435``,
    5.0 -> ``$5.00``). Only ever emitted when a price actually CHANGED — matching
    values are left untouched — so it never perturbs a byte-stable doc."""
    text = f"{value:.6f}".rstrip("0")
    intpart, _, frac = text.partition(".")
    if len(frac) < 2:
        frac = (frac + "00")[:2]
    return f"${intpart}.{frac}"


_PRICE_ATTRS = (("input-price-per-1m", "input"), ("output-price-per-1m", "output"))


def apply_price_overlay(
    current: str, price_map: dict[str, dict[str, float]]
) -> tuple[str, list[str], list[str]]:
    """Force each provider-direct id's ``input/output-price-per-1m`` in the selector
    to the snapshot price. Numeric-compare-before-replace: a model already matching
    its snapshot is left byte-identical. Ids not present in the selector (not yet
    added) are skipped. Returns ``(new_current, applied, flags)``."""
    applied: list[str] = []
    flags: list[str] = []
    for mid in sorted(price_map):
        element = extract_element(current, mid)
        if element is None:
            continue
        new_element = element
        for attr, key in _PRICE_ATTRS:
            match = re.search(rf'{re.escape(attr)}="\$([0-9.]+)"', new_element)
            if match is None:
                flags.append(f"price overlay: {mid!r} has no {attr} attribute")
                continue
            if round(float(match.group(1)), 6) != round(price_map[mid][key], 6):
                replacement = f'{attr}="{_fmt_price(price_map[mid][key])}"'
                new_element = new_element.replace(match.group(0), replacement, 1)
        if new_element != element:
            current = current.replace(element, new_element, 1)
            applied.append(mid)
    return current, applied, flags


def apply_cost_scale_price_overlay(
    cost_scale: str, price_map: dict[str, dict[str, float]]
) -> tuple[str, list[str], list[str]]:
    """Force the Input / Output cells of each cost-scale-tracked provider-direct
    model (mapped in ``build_catalog.SELECTOR_TO_COST_SCALE_NAME``) to its snapshot
    price, keeping ``model-selector.txt`` and ``model-tier-cost-scale.md`` in sync
    (the ``test_selector_pricing_matches_cost_scale_pricing`` invariant). A
    provider-direct model NOT in the cost-scale map (e.g. DeepSeek, exempt) is left
    to the selector-only overlay. Numeric-compare-before-replace (byte-stable on a
    match); a mapped model with no locatable table row is flagged."""
    name_to_price: dict[str, dict[str, float]] = {}
    for mid, price in price_map.items():
        cs_name = SELECTOR_TO_COST_SCALE_NAME.get(mid)
        if cs_name is not None:
            name_to_price[cs_name] = price
    applied: list[str] = []
    flags: list[str] = []
    seen: set[str] = set()
    lines = cost_scale.split("\n")
    # Price-table row: | Model | Input | Cache Write | Cache Read | Output | Tier | Notes |
    # split("|") -> [0]="" [1]=Model [2]=Input [3]=CacheW [4]=CacheR [5]=Output [6]=Tier ...
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 8:  # subscription tables (5 cols) are shorter — skip
            continue
        row_price = name_to_price.get(cells[1].strip())
        if row_price is None:
            continue
        seen.add(cells[1].strip())
        changed = False
        for idx, key in ((2, "input"), (5, "output")):
            match = re.search(r"\$([0-9.]+)", cells[idx])
            if match is None:
                flags.append(f"cost-scale overlay: {cells[1].strip()!r} cell {idx} has no $price")
                continue
            if round(float(match.group(1)), 6) != round(row_price[key], 6):
                cells[idx] = cells[idx].replace(match.group(0), _fmt_price(row_price[key]), 1)
                changed = True
        if changed:
            lines[i] = "|".join(cells)
            applied.append(cells[1].strip())
    for missing in sorted(set(name_to_price) - seen):
        flags.append(f"cost-scale overlay: no table row found for {missing!r}")
    return "\n".join(lines), applied, flags


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


def _run_check_additions(selector_path: Path) -> int:
    """FLAG-ONLY model-list federation (Phase 4.6): print each provider-direct
    snapshot model NOT yet in ``<model-options>``, one id per line on stdout
    (summary on stderr), so the cron can open a deduped "add this model editorially"
    issue. Discovery moves to the provider snapshots; a model is NEVER auto-added
    (it needs editorial tier ratings — the DeepSeek/Mistral path). Fail-open: any
    error prints no ids and returns 0, so a transient snapshot problem never breaks
    the catalog refresh."""
    try:
        base = base_models(selector_path.read_text())
        additions = proposed_additions(base, provider_snapshots())
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        print(f"merge_catalog: --check-additions failed (fail-open): {exc!r}", file=sys.stderr)
        return 0
    if additions:
        print(
            f"merge_catalog: {len(additions)} provider-direct model(s) not in "
            f"<model-options> — need an editorial add with tier ratings: {additions}",
            file=sys.stderr,
        )
        for mid in additions:
            print(mid)
    else:
        print(
            "merge_catalog: no unfederated provider-direct models (every snapshot "
            "model is already in <model-options>).",
            file=sys.stderr,
        )
    return 0


def _run_write(selector_path: Path, base_path: Path, cost_scale_path: Path) -> int:
    snaps = provider_snapshots()
    prices = snapshot_price_map(snaps)
    flags: list[str] = []

    # Selector: re-add dropped off-Cursor elements from base, then force every
    # provider-direct price from the snapshots.
    original = selector_path.read_text()
    current, el_applied, el_flags = apply_overlay(
        original, base_path.read_text(), provider_direct_ids(snaps)
    )
    current, px_applied, px_flags = apply_price_overlay(current, prices)
    flags.extend(el_flags)
    flags.extend(px_flags)
    if current != original:
        selector_path.write_text(current)
        print(
            f"merge_catalog: selector overlay — elements re-applied: {el_applied}; "
            f"prices re-applied: {px_applied}"
        )
    else:
        print("merge_catalog: selector overlay no-op (already matches base + snapshots)")

    # Cost-scale: force tracked provider-direct Input/Output cells to the snapshot
    # so the cross-doc price invariant stays green.
    if cost_scale_path.exists():
        cs_text = cost_scale_path.read_text()
        new_cs, cs_applied, cs_flags = apply_cost_scale_price_overlay(cs_text, prices)
        flags.extend(cs_flags)
        if new_cs != cs_text:
            cost_scale_path.write_text(new_cs)
            print(f"merge_catalog: cost-scale price overlay re-applied: {cs_applied}")
        else:
            print("merge_catalog: cost-scale price overlay no-op (already matches snapshots)")

    for flag in flags:
        print(f"merge_catalog: {flag}", file=sys.stderr)
    return 1 if flags else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose (report) / overlay (--write) the federated model registry."
    )
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH)
    parser.add_argument("--cost-scale", type=Path, default=COST_SCALE_PATH)
    parser.add_argument(
        "--write",
        action="store_true",
        help="De-clobber overlay: re-add dropped off-Cursor <model> elements from "
        "--base, then force every provider-direct price (selector + cost-scale) to "
        "the committed snapshots.",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Base (committed, pre-Opus) selector to take whole-element provider-direct "
        "models from. With --write; defaults to --selector itself (a self no-op) when omitted.",
    )
    parser.add_argument(
        "--check-additions",
        action="store_true",
        help="Flag-only model-list federation: print provider-direct snapshot models "
        "not yet in <model-options> (one id per line) for a deduped editorial-add issue.",
    )
    args = parser.parse_args()

    if args.check_additions:
        return _run_check_additions(args.selector)
    if args.write:
        base = args.base if args.base is not None else args.selector
        return _run_write(args.selector, base, args.cost_scale)
    return _run_report(args.selector)


if __name__ == "__main__":
    raise SystemExit(main())
