# tests/test_catalog_json.py
"""Schema + cross-reference invariants on docs/catalog.json.

Catches: drift between the prose docs (`model-selector.txt`,
`model-tier-cost-scale.md`) and the machine-readable catalog the wheel
ships at `roadmodel/data/catalog.json`. The cron rebuilds the JSON every
Monday after the Opus prose refresh; these tests fail loudly if a future
prose change is committed without a fresh JSON, or if the generator drops
a field.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
SELECTOR_PATH = DOCS_DIR / "model-selector.txt"
COST_SCALE_PATH = DOCS_DIR / "model-tier-cost-scale.md"
CATALOG_PATH = DOCS_DIR / "catalog.json"
BUILD_SCRIPT = REPO_ROOT / "update" / "build_catalog.py"

EXPECTED_TOP_LEVEL_KEYS = {
    "schema_version",
    "output_contract_version",
    "generated_at_utc",
    "source_doc_sha256",
    "models",
    "access_methods",
    "max_mode_rules",
    "subscription_tiers",
}

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_MODEL_RE = re.compile(r"<model\s+([^>]+?)\s*/>", re.DOTALL)
_METHOD_RE = re.compile(r"<method\s+([^>]+?)\s*/>", re.DOTALL)
_ACCESS_METHODS_RE = re.compile(r"<access-methods>(.*?)</access-methods>", re.DOTALL)
# Attribute values may embed backslash-escaped quotes; see
# test_claude_code_best_for_is_not_truncated for what a naive `[^"]*` costs.
_ATTR_RE = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"', re.DOTALL)
_ESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)
_LEADING_DOLLAR_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
_CONTRACT_VERSION_RE = re.compile(r"OUTPUT CONTRACT VERSION:\s*(\d+)")


def _load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def _attrs(blob: str) -> dict[str, str]:
    return {name: _ESCAPE_RE.sub(r"\1", value) for name, value in _ATTR_RE.findall(blob)}


def _raw_attr_value(element_text: str, attr: str) -> str:
    """Scan out one attribute value WITHOUT the shared regex.

    Deliberately hand-rolled: the truncation test must not lean on the same
    pattern the generator uses, or a regression in that pattern would break
    both sides in lockstep and the test would still pass.
    """
    start = element_text.index(f'{attr}="') + len(attr) + 2
    out: list[str] = []
    i = start
    while element_text[i] != '"':
        if element_text[i] == "\\":
            i += 1  # take the escaped character literally
        out.append(element_text[i])
        i += 1
    return "".join(out)


def _parse_selector_models() -> list[dict[str, str]]:
    text = SELECTOR_PATH.read_text()
    options_match = _OPTIONS_RE.search(text)
    assert options_match, "<model-options> not found"
    return [_attrs(m.group(1)) for m in _MODEL_RE.finditer(options_match.group(1))]


def _parse_selector_methods() -> list[dict[str, str]]:
    text = SELECTOR_PATH.read_text()
    access_match = _ACCESS_METHODS_RE.search(text)
    assert access_match, "<access-methods> not found"
    return [_attrs(m.group(1)) for m in _METHOD_RE.finditer(access_match.group(1))]


def _parse_subscription_section_rows() -> list[dict[str, str]]:
    text = COST_SCALE_PATH.read_text()
    start = text.find("## Subscription Tiers")
    assert start != -1, "Subscription Tiers section not found"
    section = text[start:]
    next_h2 = section.find("\n## ", 1)
    if next_h2 != -1:
        section = section[:next_h2]

    rows: list[dict[str, str]] = []
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
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def _norm_price(value: str | None) -> float | None:
    if not value:
        return None
    match = _LEADING_DOLLAR_RE.search(value)
    return float(match.group(1)) if match else None


# --- Schema ---


def test_schema_top_level_keys() -> None:
    catalog = _load_catalog()
    missing = EXPECTED_TOP_LEVEL_KEYS - set(catalog.keys())
    extra = set(catalog.keys()) - EXPECTED_TOP_LEVEL_KEYS
    assert not missing, f"catalog.json missing top-level keys: {missing}"
    assert not extra, f"catalog.json has unexpected top-level keys: {extra}"
    # 3 since the method elements gained `exposes_orchestration` and the
    # document gained `output_contract_version` (output-contract v2).
    assert catalog["schema_version"] == "3"
    assert isinstance(catalog["output_contract_version"], int)
    assert isinstance(catalog["models"], list) and catalog["models"]
    assert isinstance(catalog["access_methods"], list) and catalog["access_methods"]
    assert isinstance(catalog["subscription_tiers"], list)
    assert isinstance(catalog["max_mode_rules"], dict)
    sdoc = catalog["source_doc_sha256"]
    assert set(sdoc.keys()) == {"model-selector.txt", "model-tier-cost-scale.md"}


# --- Models: bidirectional cross-reference ---


def test_every_model_in_selector_is_in_json() -> None:
    selector_ids = {m["id"] for m in _parse_selector_models()}
    json_ids = {m["id"] for m in _load_catalog()["models"]}
    missing = selector_ids - json_ids
    assert not missing, (
        f"Selector models missing from catalog.json: {sorted(missing)}. "
        "Regenerate with `python update/build_catalog.py`."
    )


def test_every_json_model_is_in_selector() -> None:
    selector_ids = {m["id"] for m in _parse_selector_models()}
    json_ids = {m["id"] for m in _load_catalog()["models"]}
    stale = json_ids - selector_ids
    assert not stale, (
        f"catalog.json contains models absent from <model-options>: "
        f"{sorted(stale)}. Regenerate with `python update/build_catalog.py`."
    )


def test_prices_round_trip() -> None:
    selector_by_id = {m["id"]: m for m in _parse_selector_models()}
    mismatches: list[str] = []
    for model in _load_catalog()["models"]:
        sel = selector_by_id[model["id"]]
        sel_in = _norm_price(sel.get("input-price-per-1m"))
        sel_out = _norm_price(sel.get("output-price-per-1m"))
        if sel_in != model["input_price_per_1m"]:
            mismatches.append(
                f"{model['id']} input: selector={sel_in} catalog={model['input_price_per_1m']}"
            )
        if sel_out != model["output_price_per_1m"]:
            mismatches.append(
                f"{model['id']} output: selector={sel_out} catalog={model['output_price_per_1m']}"
            )
    assert not mismatches, "Price mismatches:\n  " + "\n  ".join(mismatches)


# --- Access methods round-trip ---


def test_access_methods_round_trip() -> None:
    selector_methods = {m["id"]: m for m in _parse_selector_methods()}
    json_methods = {m["id"]: m for m in _load_catalog()["access_methods"]}
    assert set(selector_methods.keys()) == set(json_methods.keys()), (
        "Access-method id sets differ:\n  selector="
        f"{sorted(selector_methods)}\n  catalog={sorted(json_methods)}"
    )
    mismatches: list[str] = []
    for mid, sel in selector_methods.items():
        cat = json_methods[mid]
        sel_supports = sorted(
            s.strip() for s in sel.get("supports-models", "").split(",") if s.strip()
        )
        if sel_supports != cat["supports_models"]:
            mismatches.append(
                f"{mid} supports-models: selector={sel_supports} catalog={cat['supports_models']}"
            )
        for sel_attr, cat_key, default in (
            ("provider", "provider", ""),
            # provider-jurisdiction and exposes-orchestration drive real
            # behaviour (jurisdiction filtering; whether a block may emit an
            # ORCHESTRATION line at all), so they are round-tripped too — the
            # generator silently dropped exposes-orchestration until 2026-08.
            ("provider-jurisdiction", "provider_jurisdiction", "unknown"),
            ("billing", "billing", ""),
            ("requires", "requires", ""),
            ("exposes-max-mode", "exposes_max_mode", ""),
            ("exposes-thinking", "exposes_thinking", ""),
            ("exposes-orchestration", "exposes_orchestration", ""),
            ("best-for", "best_for", ""),
        ):
            if sel.get(sel_attr, default) != cat[cat_key]:
                mismatches.append(
                    f"{mid} {sel_attr}: selector="
                    f"{sel.get(sel_attr, default)!r} catalog={cat[cat_key]!r}"
                )
    assert not mismatches, "Access-method mismatches:\n  " + "\n  ".join(mismatches)


def test_every_method_declares_orchestration_exposure() -> None:
    """`exposes_orchestration` must be present and yes/no on every method.

    Output-contract v2 emits the ORCHESTRATION line iff this is "yes"; an
    empty value would read as "no" and silently strip the line from the one
    platform (Claude Code) that has the dial.
    """
    bad = [
        f"{m['id']}={m.get('exposes_orchestration')!r}"
        for m in _load_catalog()["access_methods"]
        if m.get("exposes_orchestration") not in {"yes", "no"}
    ]
    assert not bad, "access_methods with a bad exposes_orchestration: " + ", ".join(bad)


def test_claude_code_best_for_is_not_truncated() -> None:
    r"""The claude-code best-for embeds escaped quotes (`\"ultracode\": true`).

    A `"([^"]*)"` attribute regex stops at that first inner quote, so the
    shipped JSON carried ~1147 of 3120 characters ending on a dangling
    backslash — dropping the whole Ultracode / `/effort` dial description that
    downstream consumers read. Compare against a hand-scanned ground truth.
    """
    selector = SELECTOR_PATH.read_text()
    start = selector.index('<method id="claude-code"')
    element = selector[start : selector.index("/>", start)]
    expected = _raw_attr_value(element, "best-for")

    catalog_methods = {m["id"]: m for m in _load_catalog()["access_methods"]}
    actual = catalog_methods["claude-code"]["best_for"]

    assert actual == expected, (
        f"claude-code best_for is truncated: catalog={len(actual)} chars, "
        f"selector={len(expected)} chars. Regenerate with "
        "`python update/build_catalog.py`."
    )
    assert "ultracode" in actual, "Ultracode / /effort material missing from best_for"
    assert '"ultracode": true' in actual, "escaped quotes were not unescaped in the JSON value"
    assert not actual.endswith("\\"), "best_for ends on a dangling escape (truncated mid-token)"


def test_output_contract_version_matches_selector() -> None:
    """The catalog's `output_contract_version` mirrors the selector's own
    `OUTPUT CONTRACT VERSION: N` declaration in <output-format>. Parsers use
    it to decide whether a block may omit MAX MODE / carry a split
    EFFORT+THINKING pair, so a stale value silently mis-reads live output.
    """
    text = SELECTOR_PATH.read_text()
    declared = _CONTRACT_VERSION_RE.search(text)
    assert declared, "<output-format> does not declare 'OUTPUT CONTRACT VERSION: N'"
    assert _load_catalog()["output_contract_version"] == int(declared.group(1)), (
        "catalog.json output_contract_version is stale. Regenerate with "
        "`python update/build_catalog.py`."
    )


# --- Subscription tiers round-trip ---


def test_subscription_tiers_match_tier_cost_scale() -> None:
    rows = _parse_subscription_section_rows()
    catalog_tiers = _load_catalog()["subscription_tiers"]
    assert rows, "No subscription rows parsed from model-tier-cost-scale.md"
    assert len(rows) == len(catalog_tiers), (
        f"Subscription row count mismatch: cost-scale={len(rows)} catalog={len(catalog_tiers)}"
    )
    catalog_by_key = {(t["provider"], t["tier"]): t for t in catalog_tiers}
    mismatches: list[str] = []
    for row in rows:
        key = (row["Provider"], row["Subscription"])
        if key not in catalog_by_key:
            mismatches.append(f"Missing in catalog: {key}")
            continue
        cat = catalog_by_key[key]
        monthly_raw = row.get("Monthly", "").lstrip("$").replace(",", "").strip()
        try:
            expected_monthly: float | None = float(monthly_raw)
        except ValueError:
            expected_monthly = None
        if cat["monthly_usd"] != expected_monthly:
            mismatches.append(
                f"{key} monthly: cost-scale={expected_monthly} catalog={cat['monthly_usd']}"
            )
        # Annual is OPTIONAL + editorial: "—" / blank round-trips to a
        # null annual_usd; a "$N" cell to that float (Phase 4.7 T2).
        annual_raw = row.get("Annual", "").lstrip("$").replace(",", "").strip()
        try:
            expected_annual: float | None = float(annual_raw)
        except ValueError:
            expected_annual = None
        if cat.get("annual_usd") != expected_annual:
            mismatches.append(
                f"{key} annual: cost-scale={expected_annual} catalog={cat.get('annual_usd')}"
            )
        expected_surfaces = sorted(
            s.strip() for s in row.get("Access methods unlocked", "").split(",") if s.strip()
        )
        if cat["surface_funded"] != expected_surfaces:
            mismatches.append(
                f"{key} surfaces: cost-scale={expected_surfaces} catalog={cat['surface_funded']}"
            )
        if cat["notes"] != row.get("Coverage", ""):
            mismatches.append(f"{key} coverage text differs")
    assert not mismatches, "Subscription tier mismatches:\n  " + "\n  ".join(mismatches)


# --- Determinism ---


def test_build_catalog_is_deterministic(tmp_path: Path) -> None:
    """Two consecutive runs of build_catalog.py MUST emit byte-identical
    output. The cron's determinism guard depends on this; a regression
    here would also make the guard fail on every refresh.
    """
    work = tmp_path / "repo"
    work.mkdir()
    (work / "docs").mkdir()
    (work / "update").mkdir()
    shutil.copy2(SELECTOR_PATH, work / "docs" / "model-selector.txt")
    shutil.copy2(COST_SCALE_PATH, work / "docs" / "model-tier-cost-scale.md")
    shutil.copy2(BUILD_SCRIPT, work / "update" / "build_catalog.py")

    def run() -> bytes:
        subprocess.run(
            [sys.executable, "update/build_catalog.py"],
            cwd=str(work),
            check=True,
            capture_output=True,
        )
        return (work / "docs" / "catalog.json").read_bytes()

    first = run()
    second = run()
    assert first == second, "build_catalog.py is not deterministic"
