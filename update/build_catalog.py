# update/build_catalog.py
#!/usr/bin/env python3
"""Deterministic catalog.json generator for roadmodel.

Reads docs/model-selector.txt and docs/model-tier-cost-scale.md and emits
docs/catalog.json — a machine-consumable view of the same data the prose
docs carry. The cron in .github/workflows/update-models.yml runs this
after the Opus-driven prose refresh and commits the JSON in the same PR;
hatch_build.py invokes it at wheel-build time when the JSON is missing.

Determinism contract:
    Two consecutive runs against unchanged source docs MUST produce
    byte-identical output. ``generated_at_utc`` is derived from the
    newest source-doc mtime (or SOURCE_DATE_EPOCH when set) rather than
    wall-clock time so the workflow's determinism guard passes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
SELECTOR_PATH = DOCS_DIR / "model-selector.txt"
COST_SCALE_PATH = DOCS_DIR / "model-tier-cost-scale.md"
CATALOG_PATH = DOCS_DIR / "catalog.json"

SCHEMA_VERSION = "2"

TASK_CATEGORIES = (
    "coding",
    "planning",
    "agentic",
    "multimodal",
    "long-context",
    "knowledge",
    "speed",
)

# Maps selector model ids to their cost-scale display name so cache-read
# values can be cross-referenced. Mirrors tests/test_doc_schema.py.
SELECTOR_TO_COST_SCALE_NAME = {
    "opus-4.7": "Claude 4.7 Opus",
    "gpt-5.5": "GPT-5.5",
    "sonnet-4.6": "Claude 4.6 Sonnet",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.3-codex": "GPT-5.3 Codex",
    "gpt-5.2": "GPT-5.2",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
    "composer-2": "Composer 2",
    "grok-4.3": "Grok 4.3",
    "claude-4.5-haiku": "Claude 4.5 Haiku",
    "gpt-5.4-mini": "GPT-5.4 Mini",
    "gpt-5.4-nano": "GPT-5.4 Nano",
}

CURSOR_2X_PHRASE = (
    "Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
)

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_TIER_RE = re.compile(r'<tier\s+cost="([^"]+)"\s*>(.*?)</tier>', re.DOTALL)
_MODEL_RE = re.compile(r"<model\s+([^>]+?)\s*/>", re.DOTALL)
_METHOD_RE = re.compile(r"<method\s+([^>]+?)\s*/>", re.DOTALL)
_ACCESS_METHODS_RE = re.compile(
    r"<access-methods>(.*?)</access-methods>", re.DOTALL
)
_MAX_MODE_CTX_RE = re.compile(
    r"<max-mode-context>(.*?)</max-mode-context>", re.DOTALL
)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_LEADING_DOLLAR_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_price(value: str) -> float | None:
    """Return the leading dollar amount as a float, or None for routing rates.

    "$5.00" → 5.0
    "$0.20" → 0.2
    "~$1.25 (Auto + Composer pool)" → 1.25
    "varies (routes to top-tier model)" → None
    """
    if not value:
        return None
    match = _LEADING_DOLLAR_RE.search(value)
    if not match:
        return None
    return float(match.group(1))


def _parse_models(selector_text: str) -> list[dict[str, Any]]:
    options_match = _OPTIONS_RE.search(selector_text)
    if not options_match:
        raise ValueError("<model-options> block not found in selector text")
    models: list[dict[str, Any]] = []
    for tier_m in _TIER_RE.finditer(options_match.group(1)):
        tier_cost = tier_m.group(1)
        for model_m in _MODEL_RE.finditer(tier_m.group(2)):
            attrs = dict(_ATTR_RE.findall(model_m.group(1)))
            tiers = {cat: attrs.get(f"tier-{cat}", "") for cat in TASK_CATEGORIES}
            models.append(
                {
                    "id": attrs.get("id", ""),
                    "name": attrs.get("name", ""),
                    "input_price_per_1m": _parse_price(
                        attrs.get("input-price-per-1m", "")
                    ),
                    "output_price_per_1m": _parse_price(
                        attrs.get("output-price-per-1m", "")
                    ),
                    "cache_read_per_1m": None,
                    "tier_cost": tier_cost,
                    "tiers": tiers,
                    "headline_benchmarks": attrs.get("headline-benchmarks", ""),
                    "pricing_notes": attrs.get("pricing-notes", ""),
                    "best_for": attrs.get("best-for", ""),
                }
            )
    return models


def _parse_access_methods(selector_text: str) -> list[dict[str, Any]]:
    access_match = _ACCESS_METHODS_RE.search(selector_text)
    if not access_match:
        raise ValueError("<access-methods> block not found in selector text")
    methods: list[dict[str, Any]] = []
    for method_m in _METHOD_RE.finditer(access_match.group(1)):
        attrs = dict(_ATTR_RE.findall(method_m.group(1)))
        supports = [
            s.strip()
            for s in attrs.get("supports-models", "").split(",")
            if s.strip()
        ]
        methods.append(
            {
                "id": attrs.get("id", ""),
                "name": attrs.get("name", ""),
                "provider": attrs.get("provider", ""),
                "billing": attrs.get("billing", ""),
                "requires": attrs.get("requires", ""),
                "supports_models": sorted(supports),
                "exposes_max_mode": attrs.get("exposes-max-mode", ""),
                "exposes_thinking": attrs.get("exposes-thinking", ""),
                "best_for": attrs.get("best-for", ""),
            }
        )
    return methods


def _parse_max_mode_rules(
    selector_text: str, models: list[dict[str, Any]]
) -> dict[str, Any]:
    ctx_match = _MAX_MODE_CTX_RE.search(selector_text)
    if not ctx_match:
        raise ValueError("<max-mode-context> block not found in selector text")
    applies_to = sorted(
        m["id"]
        for m in models
        if CURSOR_2X_PHRASE in (m.get("pricing_notes") or "")
    )
    return {
        "cursor_2x_input": {
            "applies_to_models": applies_to,
            "rule": CURSOR_2X_PHRASE,
        }
    }


def _parse_cost_scale_rows(cost_scale_text: str) -> dict[str, dict[str, str]]:
    """Walk every pricing table and return {model_name: {col: value}}.

    Identical-name rows (e.g. Composer 2 in both Auto+Composer pool and the
    Cursor Composer API pool) collapse to the last occurrence. Both rows
    carry the same Cache Read value, so this is safe for cache-read lookup.
    """
    out: dict[str, dict[str, str]] = {}
    in_table = False
    header: list[str] = []
    for line in cost_scale_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == "Model" and "Notes" in cells:
            header = cells
            in_table = True
            continue
        if not in_table:
            continue
        if cells and cells[0].startswith("---"):
            continue
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells, strict=True))
        out[row["Model"]] = row
    return out


def _attach_cache_read(
    models: list[dict[str, Any]], cost_scale_text: str
) -> None:
    rows = _parse_cost_scale_rows(cost_scale_text)
    for model in models:
        cs_name = SELECTOR_TO_COST_SCALE_NAME.get(model["id"])
        if not cs_name or cs_name not in rows:
            continue
        cache_str = rows[cs_name].get("Cache Read", "")
        model["cache_read_per_1m"] = _parse_price(cache_str)


def _parse_subscription_tiers(cost_scale_text: str) -> list[dict[str, Any]]:
    """Parse the "Subscription Tiers and Access Methods" section.

    The header row is `Subscription | Monthly | Provider | Access methods
    unlocked | Coverage`. Each row maps to:
        tier            ← Subscription
        monthly_usd     ← Monthly (stripped of "$" / commas)
        provider        ← Provider
        surface_funded  ← Access methods unlocked (comma-split)
        notes           ← Coverage
    """
    section_start = cost_scale_text.find("## Subscription Tiers")
    if section_start == -1:
        raise ValueError("'## Subscription Tiers' section not found")
    section = cost_scale_text[section_start:]
    next_h2 = section.find("\n## ", 1)
    if next_h2 != -1:
        section = section[:next_h2]

    tiers: list[dict[str, Any]] = []
    in_table = False
    header: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == "Subscription" and "Coverage" in cells:
            header = cells
            in_table = True
            continue
        if not in_table:
            continue
        if cells and cells[0].startswith("---"):
            continue
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells, strict=True))
        monthly_raw = row.get("Monthly", "").lstrip("$").replace(",", "").strip()
        try:
            monthly_usd: float | None = float(monthly_raw)
        except ValueError:
            monthly_usd = None
        surfaces = [
            s.strip()
            for s in row.get("Access methods unlocked", "").split(",")
            if s.strip()
        ]
        tiers.append(
            {
                "provider": row.get("Provider", ""),
                "tier": row.get("Subscription", ""),
                "monthly_usd": monthly_usd,
                "surface_funded": sorted(surfaces),
                "notes": row.get("Coverage", ""),
            }
        )
    return tiers


def _derive_generated_at() -> str:
    """Pick a timestamp that is stable across consecutive runs.

    Uses ``SOURCE_DATE_EPOCH`` when set (the reproducible-builds
    convention); otherwise the max mtime of the two source docs. Both
    produce identical output for identical inputs, which is what the
    workflow's determinism guard requires.
    """
    epoch_env = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch_env:
        epoch = int(epoch_env)
    else:
        epoch = int(
            max(SELECTOR_PATH.stat().st_mtime, COST_SCALE_PATH.stat().st_mtime)
        )
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_catalog() -> dict[str, Any]:
    selector_text = SELECTOR_PATH.read_text()
    cost_scale_text = COST_SCALE_PATH.read_text()

    models = _parse_models(selector_text)
    _attach_cache_read(models, cost_scale_text)
    models.sort(key=lambda m: m["id"])

    access_methods = _parse_access_methods(selector_text)
    access_methods.sort(key=lambda m: m["id"])

    max_mode_rules = _parse_max_mode_rules(selector_text, models)

    subscription_tiers = _parse_subscription_tiers(cost_scale_text)
    subscription_tiers.sort(key=lambda t: (t["provider"], t["tier"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _derive_generated_at(),
        "source_doc_sha256": {
            "model-selector.txt": _sha256(SELECTOR_PATH),
            "model-tier-cost-scale.md": _sha256(COST_SCALE_PATH),
        },
        "models": models,
        "access_methods": access_methods,
        "max_mode_rules": max_mode_rules,
        "subscription_tiers": subscription_tiers,
    }


def render_json(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, indent=2, sort_keys=False) + "\n"


def main() -> int:
    catalog = build_catalog()
    CATALOG_PATH.write_text(render_json(catalog))
    print(f"Wrote {CATALOG_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
