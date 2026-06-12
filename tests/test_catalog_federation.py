"""Tests for the Phase 4.6 catalog-federation chassis (T2, additive slice).

Covers the DeepSeek provider-direct catalog SOURCE
(``update/extract_deepseek_catalog.py``), the composition ENGINE
(``update/merge_catalog.py`` — precedence, canonical-id de-dup, cost-tier
derivation), and the offline conformance GATE
(``update/validate_catalog_conformance.py``). This slice is additive: it does NOT
touch ``<model-options>`` / ``catalog.json`` / the cost-scale doc, so those
artifacts stay byte-stable and the recommender's behavior is unchanged.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
CATALOG_EXTRACTOR = UPDATE_DIR / "extract_deepseek_catalog.py"
CATALOG_GATE = UPDATE_DIR / "validate_catalog_conformance.py"
PRICING_HTML = REPO_ROOT / "tests" / "fixtures" / "deepseek-pricing-sample.html"
REAL_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"
REAL_DEEPSEEK_CATALOG = UPDATE_DIR / "catalog-deepseek.json"


def _load(name: str) -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


# --------------------------------------------------------------------------- #
# Catalog source extractor
# --------------------------------------------------------------------------- #


def test_catalog_extractor_parses_fixture() -> None:
    mod = _load("extract_deepseek_catalog")
    snap = mod.build_snapshot(PRICING_HTML.read_text(), source_url="file://sample")

    models = {m["id"]: m for m in snap["models"]}
    flash = models["deepseek-v4-flash"]
    assert flash["input_price_per_1m"] == 0.14
    assert flash["output_price_per_1m"] == 0.28
    assert flash["cache_read_per_1m"] == 0.0028
    assert flash["context_tokens"] == 1_000_000
    assert flash["max_output_tokens"] == 384_000
    assert flash["name"] == "DeepSeek-V4-Flash"

    pro = models["deepseek-v4-pro"]
    assert pro["input_price_per_1m"] == 0.435
    assert pro["output_price_per_1m"] == 0.87
    assert pro["cache_read_per_1m"] == 0.003625

    assert snap["jurisdiction"] == "cn"
    assert snap["unexpected_slugs"] == []
    assert len(snap["section_sha256"]) == 64


def test_catalog_extractor_cli_writes_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "catalog-deepseek.json"
    result = subprocess.run(
        [
            sys.executable,
            str(CATALOG_EXTRACTOR),
            "--input",
            str(PRICING_HTML),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert {m["id"] for m in data["models"]} == {"deepseek-v4-flash", "deepseek-v4-pro"}


def test_catalog_extractor_raises_on_restructure() -> None:
    mod = _load("extract_deepseek_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("<html><body>No pricing table.</body></html>", source_url="x")


def test_catalog_extractor_flags_unexpected_model() -> None:
    mod = _load("extract_deepseek_catalog")
    html = PRICING_HTML.read_text().replace("deepseek-v4-pro", "deepseek-v5-pro")
    snap = mod.build_snapshot(html, source_url="x")
    assert "deepseek-v5-pro" in snap["unexpected_slugs"]


def test_committed_catalog_snapshot_invariants() -> None:
    snap = json.loads(REAL_DEEPSEEK_CATALOG.read_text())
    assert snap["jurisdiction"] == "cn"
    ids = {m["id"] for m in snap["models"]}
    assert {"deepseek-v4-flash", "deepseek-v4-pro"} <= ids
    for m in snap["models"]:
        assert m["input_price_per_1m"] > 0
        assert m["output_price_per_1m"] > 0


# --------------------------------------------------------------------------- #
# Composition engine
# --------------------------------------------------------------------------- #


def test_cost_tier_boundaries() -> None:
    mod = _load("merge_catalog")
    f = mod.cost_tier_for_output_price
    assert f(0.28) == "low"
    assert f(9.99) == "low"
    assert f(10.0) == "medium"
    assert f(14.99) == "medium"
    assert f(15.0) == "high"
    assert f(24.99) == "high"
    assert f(25.0) == "very-high"
    assert f(50.0) == "very-high"


def test_compose_provider_direct_precedence() -> None:
    mod = _load("merge_catalog")
    base = {
        "opus-4.8": {"id": "opus-4.8", "output_price_per_1m": 25.0, "tier_cost": "very-high"},
        "gpt-5": {"id": "gpt-5", "output_price_per_1m": 10.0, "tier_cost": "medium"},
    }
    snapshots = [
        {"provider": "anthropic", "models": [{"id": "opus-4.8", "output_price_per_1m": 24.0}]}
    ]
    composed, flags = mod.compose(base, snapshots)
    assert flags == []
    assert composed["opus-4.8"].source == "anthropic"  # provider-direct wins
    assert composed["opus-4.8"].cost_tier == "high"  # 24.0 -> high
    assert composed["gpt-5"].source == "cursor"  # untouched fallback


def test_compose_adds_new_models_and_reports_additions() -> None:
    mod = _load("merge_catalog")
    base = {"gpt-5": {"id": "gpt-5", "output_price_per_1m": 10.0}}
    snapshots = [
        {
            "provider": "deepseek",
            "models": [{"id": "deepseek-v4-flash", "output_price_per_1m": 0.28}],
        }
    ]
    composed, flags = mod.compose(base, snapshots)
    assert flags == []
    assert composed["deepseek-v4-flash"].source == "deepseek"
    assert mod.proposed_additions(base, snapshots) == ["deepseek-v4-flash"]


def test_compose_flags_two_source_conflict() -> None:
    mod = _load("merge_catalog")
    base: dict[str, dict[str, Any]] = {}
    snapshots = [
        {"provider": "deepseek", "models": [{"id": "shared-id", "output_price_per_1m": 1.0}]},
        {"provider": "mistral", "models": [{"id": "shared-id", "output_price_per_1m": 2.0}]},
    ]
    _, flags = mod.compose(base, snapshots)
    assert any("check 4a" in f for f in flags)


def test_compose_on_real_artifacts_is_clean() -> None:
    mod = _load("merge_catalog")
    base = mod.base_models(REAL_SELECTOR.read_text())
    snaps = mod.provider_snapshots()
    composed, flags = mod.compose(base, snaps)
    assert flags == []
    # DeepSeek is the only provider-direct source today; both models compose at low
    # tier, and provider-direct wins over the (now-present) <model-options> base entry.
    assert composed["deepseek-v4-flash"].source == "deepseek"
    assert composed["deepseek-v4-flash"].cost_tier == "low"
    assert composed["deepseek-v4-pro"].source == "deepseek"
    # DeepSeek is now IN <model-options> (the wiring slice landed it), so it is no
    # longer a "proposed" (not-yet-in-selector) addition.
    assert mod.proposed_additions(base, snaps) == []


# --------------------------------------------------------------------------- #
# De-clobber overlay (force provider-direct elements after the cron's Opus rewrite)
# --------------------------------------------------------------------------- #


def _mini_selector(*low_tier_models: str) -> str:
    body = "\n".join(low_tier_models)
    return f'<model-options>\n    <tier cost="low">\n{body}\n    </tier>\n  </model-options>\n'


_DS_ELEMENT = (
    '      <model id="deepseek-v4-pro" name="DeepSeek-V4-Pro"\n'
    '             input-price-per-1m="$0.435" output-price-per-1m="$0.87"\n'
    '             jurisdiction="cn"\n'
    '             tier-coding="B" tier-planning="B" tier-agentic="B"\n'
    '             tier-multimodal="C" tier-long-context="B" tier-knowledge="B"\n'
    '             tier-speed="B"\n'
    '             headline-benchmarks="placeholder"\n'
    '             pricing-notes="placeholder"\n'
    '             best-for="placeholder" />'
)
_KIMI_ELEMENT = (
    '      <model id="kimi-k2.5" name="Kimi K2.5" jurisdiction="cn" output-price-per-1m="$3.00" />'
)


def test_overlay_reinserts_dropped_element() -> None:
    mod = _load("merge_catalog")
    base = _mini_selector(_KIMI_ELEMENT, _DS_ELEMENT)
    current = _mini_selector(_KIMI_ELEMENT)  # Opus dropped the provider-direct DeepSeek element
    new_current, applied, flags = mod.apply_overlay(current, base, {"deepseek-v4-pro"})
    assert flags == []
    assert applied == ["deepseek-v4-pro"]
    assert mod.extract_element(new_current, "deepseek-v4-pro") == _DS_ELEMENT
    assert mod.extract_element(new_current, "kimi-k2.5") is not None  # untouched


def test_overlay_replaces_drifted_element() -> None:
    mod = _load("merge_catalog")
    base = _mini_selector(_KIMI_ELEMENT, _DS_ELEMENT)
    drifted = _DS_ELEMENT.replace('tier-coding="B"', 'tier-coding="S"')  # Opus altered it
    current = _mini_selector(_KIMI_ELEMENT, drifted)
    new_current, applied, flags = mod.apply_overlay(current, base, {"deepseek-v4-pro"})
    assert flags == []
    assert applied == ["deepseek-v4-pro"]
    assert mod.extract_element(new_current, "deepseek-v4-pro") == _DS_ELEMENT  # forced back


def test_overlay_noop_when_identical() -> None:
    mod = _load("merge_catalog")
    base = _mini_selector(_KIMI_ELEMENT, _DS_ELEMENT)
    new_current, applied, flags = mod.apply_overlay(base, base, {"deepseek-v4-pro"})
    assert applied == []
    assert flags == []
    assert new_current == base


def test_overlay_noop_when_id_absent_from_base() -> None:
    mod = _load("merge_catalog")
    base = _mini_selector(_KIMI_ELEMENT)  # no provider-direct element to protect
    current = _mini_selector(_KIMI_ELEMENT)
    new_current, applied, flags = mod.apply_overlay(current, base, {"deepseek-v4-pro"})
    assert applied == []
    assert flags == []
    assert new_current == current


def test_overlay_on_committed_selector_is_byte_stable() -> None:
    """With base == the committed selector, the overlay must change nothing (the
    DeepSeek elements are already present + identical)."""
    mod = _load("merge_catalog")
    text = REAL_SELECTOR.read_text()
    ids = mod.provider_direct_ids(mod.provider_snapshots())
    new_text, applied, flags = mod.apply_overlay(text, text, ids)
    assert new_text == text
    assert applied == []
    assert flags == []


# --------------------------------------------------------------------------- #
# Conformance gate
# --------------------------------------------------------------------------- #


def _run_gate(*snapshots: Path) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CATALOG_GATE), "--selector", str(REAL_SELECTOR)]
    if snapshots:
        cmd += ["--snapshots", *[str(p) for p in snapshots]]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_catalog_gate_passes_on_committed_artifacts() -> None:
    result = _run_gate()  # default: globs update/catalog-*.json
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout


def test_catalog_gate_fails_on_nonpositive_price(tmp_path: Path) -> None:
    snap = json.loads(REAL_DEEPSEEK_CATALOG.read_text())
    snap["models"][0]["output_price_per_1m"] = -1
    drifted = tmp_path / "catalog-deepseek.json"
    drifted.write_text(json.dumps(snap))
    result = _run_gate(drifted)
    assert result.returncode == 1
    assert "positive number" in result.stderr


def test_catalog_gate_fails_on_two_source_conflict(tmp_path: Path) -> None:
    a = tmp_path / "catalog-deepseek.json"
    b = tmp_path / "catalog-mistral.json"
    common = {
        "provider": "deepseek",
        "jurisdiction": "cn",
        "models": [
            {"id": "dupe", "slug": "dupe", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0}
        ],
        "slug_to_id": {"dupe": "dupe"},
        "unexpected_slugs": [],
        "section_sha256": "0" * 64,
    }
    a.write_text(json.dumps(common))
    b.write_text(json.dumps({**common, "provider": "mistral", "jurisdiction": "eu"}))
    result = _run_gate(a, b)
    assert result.returncode == 1
    assert "check 4a" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
