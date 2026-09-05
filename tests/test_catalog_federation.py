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
REAL_ZAI_CATALOG = UPDATE_DIR / "catalog-zai.json"
ZAI_MD = REPO_ROOT / "tests" / "fixtures" / "zai-pricing-sample.md"
REAL_GROQ_CATALOG = UPDATE_DIR / "catalog-groq.json"
GROQ_HTML = REPO_ROOT / "tests" / "fixtures" / "groq-pricing-sample.html"


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
# z.ai (Zhipu / GLM) catalog source — Markdown (.md) extractor
# --------------------------------------------------------------------------- #


def test_zai_extractor_parses_fixture() -> None:
    mod = _load("extract_zai_catalog")
    snap = mod.build_snapshot(ZAI_MD.read_text(), source_url="file://sample")

    models = {m["id"]: m for m in snap["models"]}
    # Exactly the curated subset is emitted (z.ai ships ~17 priced models).
    assert set(models) == {"glm-5.2", "glm-4.6", "glm-4.5-air"}

    assert models["glm-5.2"]["input_price_per_1m"] == 1.4
    assert models["glm-5.2"]["output_price_per_1m"] == 4.4
    assert models["glm-5.2"]["cache_read_per_1m"] == 0.26
    assert models["glm-4.6"]["output_price_per_1m"] == 2.2
    assert models["glm-4.5-air"]["output_price_per_1m"] == 1.1

    assert snap["jurisdiction"] == "cn"
    assert snap["overlay_mode"] == "whole-element"
    assert snap["unexpected_slugs"] == []  # every page slug is in the known baseline
    assert len(snap["section_sha256"]) == 64


def test_zai_extractor_excludes_free_and_noncurated() -> None:
    """Free-tier rows ($0 output) and non-curated models must never reach the
    snapshot — the curated allow-list is the only thing emitted."""
    mod = _load("extract_zai_catalog")
    snap = mod.build_snapshot(ZAI_MD.read_text(), source_url="x")
    ids = {m["id"] for m in snap["models"]}
    # GLM-5 / GLM-4.5-X are priced but not curated; the *-Flash rows are Free.
    assert "GLM-5" not in ids and "glm-5" not in ids
    assert "GLM-4.7-Flash" not in ids
    for m in snap["models"]:
        assert m["output_price_per_1m"] > 0


def test_zai_extractor_flags_new_model() -> None:
    mod = _load("extract_zai_catalog")
    # A genuinely new flagship slug (not in the known baseline) is flagged for review.
    md = ZAI_MD.read_text().replace("GLM-5.1", "GLM-6")
    snap = mod.build_snapshot(md, source_url="x")
    assert "GLM-6" in snap["unexpected_slugs"]


def test_zai_extractor_raises_on_restructure() -> None:
    mod = _load("extract_zai_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Pricing\n\nNo table here.\n", source_url="x")


def test_zai_extractor_raises_when_curated_missing() -> None:
    """A curated model vanishing from the page is a delisting/rename — fail loud."""
    mod = _load("extract_zai_catalog")
    md = ZAI_MD.read_text().replace("| GLM-5.2", "| GLM-5.2-renamed")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot(md, source_url="x")


def test_zai_extractor_cli_writes_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "catalog-zai.json"
    result = subprocess.run(
        [
            sys.executable,
            str(UPDATE_DIR / "extract_zai_catalog.py"),
            "--input",
            str(ZAI_MD),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert {m["id"] for m in data["models"]} == {"glm-5.2", "glm-4.6", "glm-4.5-air"}


def test_committed_zai_snapshot_invariants() -> None:
    snap = json.loads(REAL_ZAI_CATALOG.read_text())
    assert snap["jurisdiction"] == "cn"
    assert snap["overlay_mode"] == "whole-element"
    ids = {m["id"] for m in snap["models"]}
    assert {"glm-5.2", "glm-4.6", "glm-4.5-air"} <= ids
    for m in snap["models"]:
        assert m["input_price_per_1m"] > 0
        assert m["output_price_per_1m"] > 0


# --------------------------------------------------------------------------- #
# Groq-hosted gpt-oss catalog source — manual snapshot + drift-check
# --------------------------------------------------------------------------- #


def test_groq_snapshot_writer_invariants() -> None:
    mod = _load("extract_groq_catalog")
    snap = mod.build_snapshot()
    assert snap["provider"] == "groq"
    assert snap["jurisdiction"] == "us"
    assert snap["overlay_mode"] == "whole-element"
    assert snap["price_maintenance"] == "manual"
    models = {m["id"]: m for m in snap["models"]}
    assert models["gpt-oss-120b"]["output_price_per_1m"] == 0.60
    assert models["gpt-oss-20b"]["input_price_per_1m"] == 0.075
    assert len(snap["section_sha256"]) == 64


def test_groq_drift_check_matches_display_names() -> None:
    """The live page prints "GPT OSS 120B 128k"; the normalized drift check must
    still match the canonical id "gpt-oss-120b" (case/space/hyphen-insensitive)."""
    mod = _load("extract_groq_catalog")
    assert mod.names_missing_from_page(GROQ_HTML.read_text()) == []


def test_groq_drift_check_flags_missing_model() -> None:
    mod = _load("extract_groq_catalog")
    missing = mod.names_missing_from_page("<html>only kimi here, no oss</html>")
    assert set(missing) == {"gpt-oss-120b", "gpt-oss-20b"}


def test_groq_cli_writes_and_drift_checks(tmp_path: Path) -> None:
    out = tmp_path / "catalog-groq.json"
    result = subprocess.run(
        [
            sys.executable,
            str(UPDATE_DIR / "extract_groq_catalog.py"),
            "--input",
            str(GROQ_HTML),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert {m["id"] for m in data["models"]} == {"gpt-oss-120b", "gpt-oss-20b"}


def test_committed_groq_snapshot_invariants() -> None:
    snap = json.loads(REAL_GROQ_CATALOG.read_text())
    assert snap["jurisdiction"] == "us"
    assert snap["overlay_mode"] == "whole-element"
    ids = {m["id"] for m in snap["models"]}
    assert ids == {"gpt-oss-120b", "gpt-oss-20b"}
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


def test_catalog_gate_accepts_a_flagged_new_provider_model(tmp_path: Path) -> None:
    """Discovery flags a new model; it must not halt the whole refresh.

    A provider that ships a model roadmodel has not rated yet lands in
    ``models`` with its slug as id and its name in ``unexpected_slugs`` — the
    flag-only path that opens a tracking issue and waits for editorial tier
    ratings. G1 used to demand a ``slug_to_id`` entry anyway, which made that
    flag fatal: `deepseek-v4-flash-vision-exp` appeared 2026-08-24 and every
    catalog refresh after it died at this gate (run 33928974448), so one
    unrated provider model stopped all curation.
    """
    snap = json.loads(REAL_DEEPSEEK_CATALOG.read_text())
    snap["models"].append(
        {
            "id": "deepseek-v4-flash-vision-exp",
            "slug": "deepseek-v4-flash-vision-exp",
            "name": "DeepSeek V4 Flash Vision (experimental)",
            "input_price_per_1m": 0.1,
            "output_price_per_1m": 0.3,
        }
    )
    snap["unexpected_slugs"] = ["deepseek-v4-flash-vision-exp"]
    flagged = tmp_path / "catalog-deepseek.json"
    flagged.write_text(json.dumps(snap))

    result = _run_gate(flagged)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_catalog_gate_still_fails_on_a_silently_unmapped_slug(tmp_path: Path) -> None:
    """The invariant that survives: no slug may be unmapped AND unflagged."""
    snap = json.loads(REAL_DEEPSEEK_CATALOG.read_text())
    snap["models"].append(
        {
            "id": "deepseek-v4-mystery",
            "slug": "deepseek-v4-mystery",
            "input_price_per_1m": 0.1,
            "output_price_per_1m": 0.3,
        }
    )
    snap["unexpected_slugs"] = []
    drifted = tmp_path / "catalog-deepseek.json"
    drifted.write_text(json.dumps(snap))

    result = _run_gate(drifted)
    assert result.returncode == 1
    assert "neither in slug_to_id nor declared" in result.stderr


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
    # Anthropic / OpenAI / Google are price-only — never force-overlaid.
    for price_only_id in ("opus-4.8", "gpt-5.5", "gemini-3.5-flash"):
        assert price_only_id not in ids
    # Off-Cursor whole-element providers ARE overlaid: DeepSeek, and xAI/grok-4.3
    # since Cursor delisted it 2026-07-14 (still on xAI's own API).
    assert {"deepseek-v4-flash", "deepseek-v4-pro", "grok-4.3"} <= ids


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
    # The Codex variants stay Cursor-sourced BY DESIGN: OpenAI publishes no clean
    # per-token USD price for the gpt-5.3-codex / gpt-5.1-codex SKUs (the dedicated
    # Codex pages price the product in credits against base models; aggregator USD
    # figures are rejected). An intentional exception, not a pending gap.
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
    # whole-element since Cursor delisted xAI (2026-07-14); grok-4.3 stays
    # reachable via xAI's own API, so the overlay owns its element (like DeepSeek).
    assert snap["overlay_mode"] == "whole-element"
    assert snap["jurisdiction"] == "us"


def test_xai_extractor_raises_on_restructure() -> None:
    mod = _load("extract_xai_catalog")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Models\n\nno table\n", source_url="x")


def test_xai_committed_snapshot_matches_selector_prices() -> None:
    cat = json.loads(REAL_XAI_CATALOG.read_text())
    assert cat["overlay_mode"] == "whole-element"
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
    # gemini-3-pro is intentionally NOT in NAME_TO_ID (Google delisted the standalone
    # text SKU for gemini-3.1-pro; only "Gemini 3 Pro Image" remains), so the four
    # mapped models are the full expected set.
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
    # gemini-3-pro is deliberately unmapped (Cursor-sourced), so it is NOT a "missing"
    # model — that field stays a clean rename/drift detector.
    assert snap["missing_mapped_models"] == []
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
    assert cat["missing_mapped_models"] == []
    mc = _load("merge_catalog")
    base = mc.base_models(REAL_SELECTOR.read_text())
    for m in cat["models"]:
        sel = base[m["id"]]
        assert sel["input_price_per_1m"] == m["input_price_per_1m"]
        assert sel["output_price_per_1m"] == m["output_price_per_1m"]


# --------------------------------------------------------------------------- #
# T4 — Cursor cron is federation-aware (prompt carries the price carve-out)
# --------------------------------------------------------------------------- #


def test_cron_prompt_carries_federation_price_rule() -> None:
    """The Cursor catalog cron's Opus prompt must keep the federation carve-out so
    the daily refresh never re-authors a provider-direct model's price from Cursor's
    page (which the G4 price-provenance gate would then reject, reddening the PR).
    Guards against a future prompt edit silently dropping the rule — Phase 4.6 T4."""
    prompt = (UPDATE_DIR / "prompt.md").read_text().lower()
    assert "provider-direct" in prompt
    # Every provider with a committed catalog-<provider>.json snapshot is named as
    # price-owned-elsewhere, so Opus knows which models to leave alone.
    for provider in ("anthropic", "openai", "google", "xai", "deepseek", "mistral", "zai", "groq"):
        assert provider in prompt, f"federation rule must name {provider}"
    # Tells Opus to preserve those prices (not re-derive from Cursor)...
    assert (
        "do not re-derive" in prompt or "read-only" in prompt or "preserve the existing" in prompt
    )
    # ...and cites the deterministic backstop (the G4 price-provenance gate).
    assert "g4" in prompt or "price-provenance" in prompt


# --------------------------------------------------------------------------- #
# T4 deterministic backstop — price overlay (selector + cost-scale) from snapshots
# --------------------------------------------------------------------------- #

COST_SCALE = REPO_ROOT / "docs" / "model-tier-cost-scale.md"


def test_snapshot_price_map_includes_providers_excludes_codex() -> None:
    mod = _load("merge_catalog")
    prices = mod.snapshot_price_map(mod.provider_snapshots())
    # Codex SKUs have no snapshot, so the overlay never touches them — they stay
    # Cursor-authored (the #244 intentional exception).
    assert "gpt-5.3-codex" not in prices
    assert "gpt-5.1-codex" not in prices
    # Provider-direct models are present with their snapshot prices.
    assert prices["opus-4.8"]["output"] == 25.0
    assert prices["grok-4.3"] == {"input": 1.25, "output": 2.5}


def test_price_overlay_forces_snapshot_price_and_is_noop_on_match() -> None:
    mod = _load("merge_catalog")
    selector = (
        '<model-options>\n  <tier cost="very-high">\n'
        '      <model id="opus-4.8" name="Opus 4.8"\n'
        '             input-price-per-1m="$9.99" output-price-per-1m="$25.00"\n'
        '             tier-coding="S" />\n'
        "  </tier>\n</model-options>"
    )
    price_map = {"opus-4.8": {"input": 5.0, "output": 25.0}}
    new, applied, flags = mod.apply_price_overlay(selector, price_map)
    assert flags == []
    assert applied == ["opus-4.8"]
    assert 'input-price-per-1m="$5.00"' in new  # drifted input corrected from snapshot
    assert 'output-price-per-1m="$25.00"' in new  # matching output left byte-identical
    # Idempotent — second pass is a strict no-op.
    again, applied2, _ = mod.apply_price_overlay(new, price_map)
    assert again == new
    assert applied2 == []


def test_price_overlay_skips_models_absent_from_selector() -> None:
    mod = _load("merge_catalog")
    selector = "<model-options>\n</model-options>"
    new, applied, flags = mod.apply_price_overlay(
        selector, {"opus-4.8": {"input": 5.0, "output": 25.0}}
    )
    assert new == selector
    assert applied == []
    assert flags == []


def test_price_overlay_preserves_sub_cent_precision() -> None:
    mod = _load("merge_catalog")
    # A 3-decimal provider-direct price (DeepSeek-style) must not be rounded to 2dp.
    selector = (
        '<model-options>\n  <tier cost="low">\n'
        '      <model id="deepseek-v4-pro" name="X"\n'
        '             input-price-per-1m="$0.40" output-price-per-1m="$0.87" />\n'
        "  </tier>\n</model-options>"
    )
    new, applied, _ = mod.apply_price_overlay(
        selector, {"deepseek-v4-pro": {"input": 0.435, "output": 0.87}}
    )
    assert 'input-price-per-1m="$0.435"' in new
    assert applied == ["deepseek-v4-pro"]


def test_cost_scale_overlay_corrects_mapped_row_and_is_noop_on_match() -> None:
    mod = _load("merge_catalog")
    cost_scale = (
        "### API Pool — Anthropic (Claude)\n\n"
        "| Model           | Input | Cache Write | Cache Read | Output | Tier      | Notes |\n"
        "| --------------- | ----- | ----------- | ---------- | ------ | --------- | ----- |\n"
        "| Claude Opus 4.8 | $9.99 | $6.25       | $0.50      | $25.00 | Very High | -     |\n"
    )
    # opus-4.8 maps to "Claude Opus 4.8" in SELECTOR_TO_COST_SCALE_NAME.
    price_map = {"opus-4.8": {"input": 5.0, "output": 25.0}}
    new, applied, flags = mod.apply_cost_scale_price_overlay(cost_scale, price_map)
    assert flags == []
    assert applied == ["Claude Opus 4.8"]
    assert "$5.00" in new  # Input corrected
    assert "$25.00" in new  # Output (matching) preserved
    assert "$9.99" not in new
    # The header / separator rows must be untouched.
    assert "| Model           | Input |" in new
    # No-op on a second pass.
    again, applied2, _ = mod.apply_cost_scale_price_overlay(new, price_map)
    assert again == new
    assert applied2 == []


def test_cost_scale_overlay_flags_missing_row() -> None:
    mod = _load("merge_catalog")
    # opus-4.8 is mapped but absent from this (header-only) table -> flagged, not silent.
    cost_scale = "| Model | Input | Cache Write | Cache Read | Output | Tier | Notes |\n"
    new, applied, flags = mod.apply_cost_scale_price_overlay(
        cost_scale, {"opus-4.8": {"input": 5.0, "output": 25.0}}
    )
    assert applied == []
    assert any("no table row found" in f for f in flags)


def test_overlays_are_byte_stable_on_committed_docs() -> None:
    """The deterministic backstop must be a strict no-op when the committed selector
    + cost-scale already match the snapshots (today's state). This locks in
    byte-stability AND guards the cross-doc invariant — Phase 4.6 T4 backstop."""
    mod = _load("merge_catalog")
    prices = mod.snapshot_price_map(mod.provider_snapshots())
    selector = REAL_SELECTOR.read_text()
    new_sel, _, sel_flags = mod.apply_price_overlay(selector, prices)
    assert new_sel == selector, "selector price overlay changed committed docs (expected no-op)"
    assert sel_flags == []
    cost_scale = COST_SCALE.read_text()
    new_cs, _, cs_flags = mod.apply_cost_scale_price_overlay(cost_scale, prices)
    assert new_cs == cost_scale, "cost-scale price overlay changed committed docs (expected no-op)"
    assert cs_flags == []


# --------------------------------------------------------------------------- #
# T5 — Mistral onboarding closes the EU-jurisdiction gap
# --------------------------------------------------------------------------- #

import re as _re  # noqa: E402


def _model_jurisdictions(selector_text: str) -> dict[str, str]:
    opts = _re.search(r"<model-options>(.*?)</model-options>", selector_text, _re.DOTALL)
    assert opts is not None
    out: dict[str, str] = {}
    for m in _re.finditer(
        r'<model\s+id="([^"]+)"(?:[^"]|"(?:[^"\\]|\\.)*")*?jurisdiction="([^"]+)"',
        opts.group(1),
        _re.DOTALL,
    ):
        out[m.group(1)] = m.group(2)
    return out


def _methods(selector_text: str) -> list[dict[str, Any]]:
    block = _re.search(r"<access-methods>(.*?)</access-methods>", selector_text, _re.DOTALL)
    assert block is not None
    methods: list[dict[str, Any]] = []
    for chunk in block.group(1).split("<method ")[1:]:
        mid = _re.search(r'id="([^"]+)"', chunk)
        pj = _re.search(r'provider-jurisdiction="([^"]+)"', chunk)
        sm = _re.search(r'supports-models="([^"]*)"', chunk)
        if mid and pj and sm:
            methods.append(
                {
                    "id": mid.group(1),
                    "jurisdiction": pj.group(1),
                    "supports": [s for s in sm.group(1).split(",") if s],
                }
            )
    return methods


def test_eu_only_jurisdiction_now_resolves_to_a_recommendation() -> None:
    """T5's headline win: an allowed-jurisdictions of [eu] previously returned ZERO
    recommendations (every provider was us/cn). Mistral closes the gap — a complete
    recommendable path (an eu-jurisdiction model reachable via an eu-operator method)
    must now exist."""
    sel = REAL_SELECTOR.read_text()
    model_juris = _model_jurisdictions(sel)
    methods = _methods(sel)
    allowed = {"eu"}
    eu_models = {mid for mid, j in model_juris.items() if j in allowed}
    eu_methods = [mt for mt in methods if mt["jurisdiction"] in allowed]
    reachable = {mid for mt in eu_methods for mid in mt["supports"] if mid in eu_models}
    assert reachable, "an [eu]-only allowed-jurisdictions must resolve to >=1 recommendable model"
    assert {
        "mistral-medium-3.5",
        "mistral-small-4",
        "mistral-large-3",
        "codestral",
    } <= reachable
    assert any(mt["id"] == "mistral-api" for mt in eu_methods)


def test_mistral_method_supports_only_real_mistral_models() -> None:
    """Defensive: the mistral-api method's supports-models all exist in <model-options>
    as eu-jurisdiction models (mirrors the schema test, scoped to the new provider)."""
    sel = REAL_SELECTOR.read_text()
    model_juris = _model_jurisdictions(sel)
    mistral = next(mt for mt in _methods(sel) if mt["id"] == "mistral-api")
    assert mistral["jurisdiction"] == "eu"
    for mid in mistral["supports"]:
        assert model_juris.get(mid) == "eu", f"{mid} missing or not eu-jurisdiction"


def test_thinking_context_documents_mistral_reasoning_dial() -> None:
    """T5 PR2 (lighter approach): the selector's <thinking-context> describes Mistral's
    reasoning_effort dial + its output mapping. Mistral's reasoning docs are a JS SPA
    with an ambiguous enum, so the dial is documented HONESTLY here rather than pinned
    by a check-G gate — this presence test is the regression guard."""
    sel = REAL_SELECTOR.read_text()
    tc = _re.search(r"<thinking-context>(.*?)</thinking-context>", sel, _re.DOTALL)
    assert tc is not None
    body = tc.group(1)
    assert "Mistral" in body
    assert "reasoning_effort" in body
    # Output mapping present for the two documented values.
    assert "`none` → `Off`" in body
    assert "`high` → `High`" in body


def test_check_additions_cli_emits_proposed_additions() -> None:
    """Flag-only model-list federation (Phase 4.6): `merge_catalog --check-additions`
    prints the provider-direct snapshot models not yet in <model-options>, one id per
    line, so the cron can open a deduped editorial-add issue. It must emit exactly
    proposed_additions and exit 0 (fail-open). Today the federation is complete, so the
    set is empty — a model is NEVER auto-added (it needs editorial tier ratings)."""
    mod = _load("merge_catalog")
    base = mod.base_models(REAL_SELECTOR.read_text())
    expected = set(mod.proposed_additions(base, mod.provider_snapshots()))
    result = subprocess.run(
        [sys.executable, str(UPDATE_DIR / "merge_catalog.py"), "--check-additions"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    emitted = {line for line in result.stdout.splitlines() if line.strip()}
    assert emitted == expected
    assert emitted == set()  # federation complete today — no unfederated models


# --------------------------------------------------------------------------- #
# G5 — price COVERAGE (the inverse of G4)
#
# G4 walks SNAPSHOT models and reconciles the ones that reached the selector, so
# a selector model ABSENT from its own maker's snapshot is invisible to it: G4
# passes for lack of anything to compare, not because the price agreed. Claude
# Opus 5 shipped exactly that way — catalogued at $5/$25 from the aggregator
# mirror while Anthropic's own pricing page still listed five models and no
# Opus 5.
# --------------------------------------------------------------------------- #

_G5_SELECTOR = """
  <model-options>
    <tier cost="low">
      <model id="acme-1" name="Acme One"
             input-price-per-1m="$1.00" output-price-per-1m="$10.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="A" />
    </tier>
    <tier cost="high">
      <model id="acme-2" name="Acme Two"
             input-price-per-1m="$2.00" output-price-per-1m="$20.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="A" />
      <model id="pool-only" name="Pool Only"
             input-price-per-1m="$3.00" output-price-per-1m="$30.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="A" />
    </tier>
  </model-options>
  <access-methods>
      <method id="acme-api" name="Acme API" provider="acme"
              provider-jurisdiction="us" billing="per-token" requires="key"
              supports-models="acme-1,acme-2" />
      <method id="cursor" name="Cursor" provider="cursor"
              provider-jurisdiction="us" billing="subscription-pool" requires="sub"
              supports-models="acme-1,acme-2,pool-only" />
  </access-methods>
"""

# Acme publishes a snapshot, but it prices only acme-1.
_G5_SNAPSHOT = {
    "provider": "acme",
    "jurisdiction": "us",
    "models": [
        {"id": "acme-1", "input_price_per_1m": 1.0, "output_price_per_1m": 10.0},
    ],
}


def _g5_notes(selector: str = _G5_SELECTOR, snapshot: dict[str, Any] | None = None) -> list[str]:
    mod = _load("validate_catalog_conformance")
    snap = _G5_SNAPSHOT if snapshot is None else snapshot
    base = mod.base_models(selector)
    return mod.check_price_coverage(selector, base, [snap])


def test_g5_flags_model_absent_from_its_makers_snapshot() -> None:
    """The Opus 5 case: maker publishes prices, but not for THIS model."""
    notes = _g5_notes()
    assert len(notes) == 1, notes
    assert "'acme-2'" in notes[0]
    assert "UNVERIFIED" in notes[0]
    assert "acme" in notes[0]


def test_g5_silent_for_models_the_snapshot_does_price() -> None:
    """A model G4 actually reconciled must not be reported as uncovered."""
    assert all("'acme-1'" not in note for note in _g5_notes())


def test_g5_ignores_models_with_no_first_party_maker() -> None:
    """Aggregator-only models have no provider page that SHOULD have priced them.

    `pool-only` is reachable through Cursor alone, so there is no maker snapshot
    it is missing from — reporting it would be noise, not a provenance gap.
    """
    assert all("'pool-only'" not in note for note in _g5_notes())


def test_g5_silent_when_the_maker_publishes_no_snapshot_at_all() -> None:
    """No snapshot means nothing was ever claimed to be verified.

    G4 makes no assurance about this provider, so there is no false confidence
    for G5 to correct.
    """
    other = {"provider": "othercorp", "jurisdiction": "us", "models": []}
    assert _g5_notes(snapshot=other) == []


def test_g5_is_not_fatal_by_default_but_escalates_under_strict() -> None:
    """Advisory by default; --strict-provenance turns the notes into failures.

    Not fatal by default on purpose: providers ship models before pricing them
    publicly, and blocking the catalog refresh on an upstream publishing lag
    would strand the lane.
    """
    result = subprocess.run(
        [sys.executable, str(CATALOG_GATE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    strict = subprocess.run(
        [sys.executable, str(CATALOG_GATE), "--strict-provenance"],
        capture_output=True,
        text=True,
    )
    # The committed catalog currently carries un-cross-checked prices, so strict
    # mode must reject it — proving the flag actually escalates.
    assert strict.returncode == 1, strict.stdout
    assert "G5 (price coverage)" in strict.stderr


def test_g5_reports_the_committed_catalogs_real_gaps() -> None:
    """Guards the finding itself: Opus 5's price is mirror-only today."""
    result = subprocess.run([sys.executable, str(CATALOG_GATE)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "claude-opus-5" in result.stdout
    assert "price-coverage note(s)" in result.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
