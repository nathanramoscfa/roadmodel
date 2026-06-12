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
REAL_ANTHROPIC_CATALOG = UPDATE_DIR / "catalog-anthropic.json"
ANTHROPIC_MD = REPO_ROOT / "tests" / "fixtures" / "anthropic-pricing-sample.md"
REAL_OPENAI_CATALOG = UPDATE_DIR / "catalog-openai.json"
OPENAI_MD = REPO_ROOT / "tests" / "fixtures" / "openai-pricing-sample.md"
REAL_XAI_CATALOG = UPDATE_DIR / "catalog-xai.json"
XAI_MD = REPO_ROOT / "tests" / "fixtures" / "xai-models-sample.md"
REAL_GOOGLE_CATALOG = UPDATE_DIR / "catalog-google.json"
GOOGLE_HTML = REPO_ROOT / "tests" / "fixtures" / "google-pricing-sample.html"


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


def _run_gate(*snapshots: Path, selector: Path = REAL_SELECTOR) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CATALOG_GATE), "--selector", str(selector)]
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


# --------------------------------------------------------------------------- #
# Anthropic provider-direct catalog source (T3 — Markdown, price-only)
# --------------------------------------------------------------------------- #


def test_anthropic_extractor_parses_standard_table() -> None:
    mod = _load("extract_anthropic_catalog")
    snap = mod.build_snapshot(ANTHROPIC_MD.read_text(), source_url="file://sample")
    models = {m["id"]: m for m in snap["models"]}
    assert set(models) == {
        "claude-fable-5",
        "opus-4.8",
        "opus-4.7",
        "sonnet-4.6",
        "claude-4.5-haiku",
    }
    # The STANDARD table, not the 50%-off Batch table below it.
    assert models["opus-4.8"]["input_price_per_1m"] == 5.0
    assert models["opus-4.8"]["output_price_per_1m"] == 25.0
    # Cache Hits & Refreshes column, NOT the "Cache Writes" columns.
    assert models["opus-4.8"]["cache_read_per_1m"] == 0.5
    assert models["claude-fable-5"]["output_price_per_1m"] == 50.0
    assert models["sonnet-4.6"]["output_price_per_1m"] == 15.0
    assert snap["overlay_mode"] == "price-only"
    assert snap["jurisdiction"] == "us"
    # Non-selector (Mythos) + deprecated rows are not mapped.
    assert "Claude Mythos 5" not in {m["name"] for m in snap["models"]}


def test_anthropic_extractor_raises_on_restructure() -> None:
    mod = _load("extract_anthropic_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Pricing\n\nNo table here.\n", source_url="x")


def test_anthropic_committed_snapshot_matches_selector_prices() -> None:
    cat = json.loads(REAL_ANTHROPIC_CATALOG.read_text())
    assert cat["overlay_mode"] == "price-only"
    mc = _load("merge_catalog")
    base = mc.base_models(REAL_SELECTOR.read_text())
    for m in cat["models"]:
        sel = base[m["id"]]
        assert sel["input_price_per_1m"] == m["input_price_per_1m"]
        assert sel["output_price_per_1m"] == m["output_price_per_1m"]


# --------------------------------------------------------------------------- #
# overlay_mode scoping + G4 price provenance
# --------------------------------------------------------------------------- #


def test_overlay_only_targets_whole_element_providers() -> None:
    mod = _load("merge_catalog")
    snaps = [
        {"provider": "anthropic", "overlay_mode": "price-only", "models": [{"id": "opus-4.8"}]},
        {
            "provider": "deepseek",
            "overlay_mode": "whole-element",
            "models": [{"id": "deepseek-v4-pro"}],
        },
        {"provider": "x", "models": [{"id": "no-mode-model"}]},  # no mode -> not forced
    ]
    assert mod.provider_direct_ids(snaps) == {"deepseek-v4-pro"}


def test_real_overlay_excludes_price_only_providers() -> None:
    mod = _load("merge_catalog")
    ids = mod.provider_direct_ids(mod.provider_snapshots())
    # Anthropic / OpenAI / Google / xAI are price-only — never force-overlaid.
    for price_only_id in ("opus-4.8", "gpt-5.5", "gemini-3.5-flash", "grok-4.3"):
        assert price_only_id not in ids
    # Only the off-Cursor whole-element provider (DeepSeek) is overlaid.
    assert {"deepseek-v4-flash", "deepseek-v4-pro"} <= ids


def test_price_provenance_fails_on_selector_drift(tmp_path: Path) -> None:
    """G4: a selector Anthropic price that drifts from the provider-direct snapshot
    fails the gate (Cursor's mirror != Anthropic's own page)."""
    drifted = REAL_SELECTOR.read_text().replace(
        'id="opus-4.8" name="Opus 4.8"\n'
        '             input-price-per-1m="$5.00" output-price-per-1m="$25.00"',
        'id="opus-4.8" name="Opus 4.8"\n'
        '             input-price-per-1m="$5.00" output-price-per-1m="$26.00"',
    )
    assert drifted != REAL_SELECTOR.read_text(), "drift fixture anchor did not match"
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_gate(REAL_ANTHROPIC_CATALOG, selector=selector)
    assert result.returncode == 1
    assert "G4 (price provenance)" in result.stderr
    assert "opus-4.8" in result.stderr


# --------------------------------------------------------------------------- #
# OpenAI provider-direct catalog source (T3 — JS-array .md, standard pane only)
# --------------------------------------------------------------------------- #


def test_openai_extractor_parses_standard_pane_not_batch() -> None:
    mod = _load("extract_openai_catalog")
    snap = mod.build_snapshot(OPENAI_MD.read_text(), source_url="file://sample")
    models = {m["id"]: m for m in snap["models"]}
    assert set(models) == {
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.2",
        "gpt-5",
        "gpt-5-mini",
    }
    # STANDARD pane prices, NOT the half-price Batch pane below.
    assert models["gpt-5.5"]["input_price_per_1m"] == 5.0
    assert models["gpt-5.5"]["output_price_per_1m"] == 30.0
    assert models["gpt-5.4"]["output_price_per_1m"] == 15.0
    assert models["gpt-5-mini"]["output_price_per_1m"] == 2.0
    # The "(<272K context length)" suffix is stripped; cached-input becomes cache_read.
    assert models["gpt-5.5"]["cache_read_per_1m"] == 0.5
    assert snap["overlay_mode"] == "price-only"
    assert snap["jurisdiction"] == "us"
    # gpt-5.1 + the -pro rows are present in the pane but NOT mapped (selector uses
    # gpt-5.1-codex, not gpt-5.1) — confirm they are skipped.
    assert "gpt-5.1" not in models
    assert "gpt-5.5-pro" not in {m["name"] for m in snap["models"]}


def test_openai_extractor_raises_on_restructure() -> None:
    mod = _load("extract_openai_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Pricing\n\nno standard pane here\n", source_url="x")


def test_openai_committed_snapshot_matches_selector_prices() -> None:
    cat = json.loads(REAL_OPENAI_CATALOG.read_text())
    assert cat["overlay_mode"] == "price-only"
    mc = _load("merge_catalog")
    base = mc.base_models(REAL_SELECTOR.read_text())
    for m in cat["models"]:
        sel = base[m["id"]]
        assert sel["input_price_per_1m"] == m["input_price_per_1m"]
        assert sel["output_price_per_1m"] == m["output_price_per_1m"]
    # The Codex variants are deliberately NOT migrated (not on the standard page).
    ids = {m["id"] for m in cat["models"]}
    assert "gpt-5.3-codex" not in ids
    assert "gpt-5.1-codex" not in ids


# --------------------------------------------------------------------------- #
# xAI provider-direct catalog source (T3 — Markdown table, price-only)
# --------------------------------------------------------------------------- #


def test_xai_extractor_parses_token_table_not_image() -> None:
    mod = _load("extract_xai_catalog")
    snap = mod.build_snapshot(XAI_MD.read_text(), source_url="file://sample")
    models = {m["id"]: m for m in snap["models"]}
    assert set(models) == {"grok-4.3"}  # only the selector model; grok-4.20/build/image skipped
    assert models["grok-4.3"]["input_price_per_1m"] == 1.25
    assert models["grok-4.3"]["output_price_per_1m"] == 2.5
    assert snap["overlay_mode"] == "price-only"
    assert snap["jurisdiction"] == "us"


def test_xai_extractor_raises_on_restructure() -> None:
    mod = _load("extract_xai_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Models\n\nno table\n", source_url="x")


def test_xai_committed_snapshot_matches_selector_prices() -> None:
    cat = json.loads(REAL_XAI_CATALOG.read_text())
    assert cat["overlay_mode"] == "price-only"
    mc = _load("merge_catalog")
    base = mc.base_models(REAL_SELECTOR.read_text())
    for m in cat["models"]:
        sel = base[m["id"]]
        assert sel["input_price_per_1m"] == m["input_price_per_1m"]
        assert sel["output_price_per_1m"] == m["output_price_per_1m"]


# --------------------------------------------------------------------------- #
# Google (Gemini) provider-direct catalog source (T3 — HTML section-walk)
# --------------------------------------------------------------------------- #


def test_google_extractor_section_walk_and_disambiguation() -> None:
    mod = _load("extract_google_catalog")
    snap = mod.build_snapshot(GOOGLE_HTML.read_text(), source_url="file://sample")
    models = {m["id"]: m for m in snap["models"]}
    # 4 of 5: gemini-3-pro has no standalone heading (only "Gemini 3 Pro Image").
    assert set(models) == {
        "gemini-3.5-flash",
        "gemini-3.1-pro",
        "gemini-3-flash",
        "gemini-2.5-flash",
    }
    assert models["gemini-3.5-flash"]["output_price_per_1m"] == 9.0
    # Pro is context-tiered: the FIRST Standard table (<=200K) is the headline price.
    assert models["gemini-3.1-pro"]["input_price_per_1m"] == 2.0
    assert models["gemini-3.1-pro"]["output_price_per_1m"] == 12.0
    assert models["gemini-3-flash"]["output_price_per_1m"] == 3.0
    # 2.5 Flash, NOT the $0.10 Flash-Lite near-miss below it.
    assert models["gemini-2.5-flash"]["input_price_per_1m"] == 0.3
    # Near-misses did NOT bind.
    assert "gemini-3-pro" not in models  # "Gemini 3 Pro Image" must not bind
    assert snap["missing_mapped_models"] == ["gemini-3-pro"]
    assert snap["overlay_mode"] == "price-only"


def test_google_extractor_raises_on_restructure() -> None:
    mod = _load("extract_google_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot(
            "<html><body><h2>Gemini 3.1 Pro</h2><p>Input price Paid Tier</p></body></html>",
            source_url="x",
        )


def test_google_committed_snapshot_matches_selector_prices() -> None:
    cat = json.loads(REAL_GOOGLE_CATALOG.read_text())
    assert cat["overlay_mode"] == "price-only"
    assert cat["missing_mapped_models"] == ["gemini-3-pro"]
    mc = _load("merge_catalog")
    base = mc.base_models(REAL_SELECTOR.read_text())
    for m in cat["models"]:
        sel = base[m["id"]]
        assert sel["input_price_per_1m"] == m["input_price_per_1m"]
        assert sel["output_price_per_1m"] == m["output_price_per_1m"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
