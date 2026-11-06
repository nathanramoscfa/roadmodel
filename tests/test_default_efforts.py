"""Vendor default efforts reach the catalog with no value kept by hand.

The parser tests quote each vendor's own wording. Nothing here reads a vendor's
current value out of the committed snapshots: a test that did would fail the
day the vendor moved it, which is the change this exists to carry.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE = REPO_ROOT / "update"
SCRIPTS = REPO_ROOT / "scripts"
for path in (UPDATE, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import automation_integrity  # noqa: E402
import build_catalog  # noqa: E402
import cron_pr  # noqa: E402
import extract_default_efforts as ext  # noqa: E402
import security_catalog  # noqa: E402

CATALOG = json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())
METHODS = {m["id"]: m for m in CATALOG["access_methods"]}

ANTHROPIC = """---
title: Effort
featureMetadata:
  status: stable
  supportedModels:
    - claude-fable-5-1
    - claude-opus-5-5
    - claude-sonnet-5-5
    - claude-haiku-5-5
    - claude-opus-4-5-20251101
  supportedPlatforms:
    Claude API: stable
---

<Tip>
  Setting `effort` to the model's default (`"medium"` on Claude Opus 5.5 and Claude Haiku 5.5, `"high"` on other models) produces exactly the same behavior.
</Tip>

| Level    | Description |
| -------- | ----------- |
| `high`   | Spends as many tokens as the task needs. The default on every model that supports effort except Claude Opus 5.5 and Claude Haiku 5.5. |
| `medium` | Balanced approach. The default on Claude Opus 5.5 and Claude Haiku 5.5. |
"""

OPENAI_REASONING = """Defaults are also model-dependent rather than universal. `gpt-5.5` defaults to `medium` reasoning effort.

If you omit `reasoning.effort`, GPT-5.6 defaults to `medium` in both modes. GPT-6.1 Sol, GPT-6 Sol, and GPT-6 Luna also default to `medium` reasoning effort.
"""

OPENAI_LATEST = """### GPT-6 Astra

GPT-6 Astra is our most intelligent model yet.

### GPT-6.1 Sol

It supports `low`, `medium` (default),
`high`, `xhigh`, and `max` reasoning effort.

### GPT-6.1 Terra

It supports `none`, `low`, `medium` (default), `high`, `xhigh`, and `max`
reasoning effort.

## What's new
"""

XAI = """If not specified, `reasoning_effort` defaults to `"high"`. Reasoning cannot be disabled.

| Model | `reasoning` parameter | Behavior |
|---|---|---|
| `grok-4.7` | `reasoning.effort`: `"low"` / `"medium"` / `"high"` (default) / `"xhigh"` | Controls reasoning depth |
| `grok-4.20-multi-agent` | `reasoning.effort`: `"low"` / `"medium"` / `"high"` / `"xhigh"` | Controls agent count |
"""

GROQ = """### [Options for Reasoning Effort (Muse Spark Open)](#options-for-reasoning-effort-muse-spark-open)

| reasoning\\_effort Options | Description |
| ------------------------- | ----------- |
| high                      | High effort reasoning. |
| xhigh                     | Highest effort reasoning, for the model's strongest results. This is the default.  |

### [Options for Reasoning Effort (GPT-OSS)](#options-for-reasoning-effort-gptoss)

| reasoning\\_effort Options | Description |
| ------------------------- | ----------- |
| high                      | High effort reasoning. |

## [Quick Start](#quick-start)

| other | Enable it. This is the default. |
"""

ZAI = """  * Available values: `max` (default and recommended, deep inference), `high` (enhanced inference), `low` (mild inference)
  * * For GLM-5.3 and GLM-5.3-FLASH, only `max`, `high` and `low` are supported.
  * * For GLM-5.2, the supported options are `max` (default and recommended, for deep inference), `xhigh`, `high`.
"""


def test_anthropic_gives_every_listed_model_the_blanket_bar_its_exceptions() -> None:
    assert ext.parse_anthropic(ANTHROPIC) == {
        "Fable 5.1": "high",
        "Haiku 5.5": "medium",
        "Opus 4.5": "high",
        "Opus 5.5": "medium",
        "Sonnet 5.5": "high",
    }


@pytest.mark.parametrize(
    "broken",
    [
        ANTHROPIC.replace("except Claude Opus 5.5 and Claude Haiku 5.5", "except Claude Opus 5.5"),
        ANTHROPIC.replace('`"high"` on other models', '`"max"` on other models'),
        ANTHROPIC.replace("    - claude-opus-5-5\n", ""),
        ANTHROPIC.replace("The default on every model", "Most models"),
    ],
)
def test_anthropic_statements_that_disagree_stop_the_read(broken: str) -> None:
    assert broken != ANTHROPIC
    with pytest.raises(ext.ExtractError):
        ext.parse_anthropic(broken)


def test_openai_reads_both_guides_and_expands_a_family() -> None:
    names = ["GPT-5.6 Sol", "GPT-5.6 Luna", "GPT-6 Sol", "GPT-6 Astra"]
    assert ext.parse_openai(OPENAI_REASONING, OPENAI_LATEST, names) == {
        "GPT-5.6 Luna": "medium",
        "GPT-5.6 Sol": "medium",
        "GPT-6 Luna": "medium",
        "GPT-6 Sol": "medium",
        "GPT-6.1 Sol": "medium",
        "GPT-6.1 Terra": "medium",
    }


def test_openai_gives_a_model_it_does_not_state_nothing() -> None:
    """GPT-6 Astra has no stated default on the API, so none is inferred."""
    assert "GPT-6 Astra" not in ext.parse_openai(OPENAI_REASONING, OPENAI_LATEST, [])


def test_openai_guides_that_disagree_stop_the_read() -> None:
    latest = OPENAI_LATEST.replace("`low`, `medium` (default)", "`low` (default), `medium`")
    with pytest.raises(ext.ExtractError, match="GPT-6.1 Sol"):
        ext.parse_openai(OPENAI_REASONING, latest, [])


def test_codex_reads_its_catalog_and_skips_hidden_models() -> None:
    catalog = {
        "models": [
            {"slug": "gpt-6.1-sol", "visibility": "list", "default_reasoning_level": "low"},
            {"slug": "gpt-5.1-codex-max", "visibility": "list", "default_reasoning_level": "high"},
            {"slug": "codex-auto-review", "visibility": "hide", "default_reasoning_level": "high"},
            {"slug": "gpt-6-luna", "visibility": "list"},
        ]
    }
    assert ext.parse_codex(catalog) == {"GPT-6.1 Sol": "low", "GPT-5.1 Codex Max": "high"}


def test_xai_reads_its_table_and_skips_a_row_with_no_default() -> None:
    assert ext.parse_xai(XAI) == {"Grok 4.7": "high"}


def test_xai_table_and_sentence_must_agree() -> None:
    with pytest.raises(ext.ExtractError):
        ext.parse_xai(XAI.replace('defaults to `"high"`', 'defaults to `"low"`'))


def test_groq_reads_the_marked_row_of_each_options_table() -> None:
    """Scoped to the options tables: a later "This is the default." row is not one."""
    assert ext.parse_groq(GROQ, ["gpt-oss-20b"]) == {"Muse Spark Open": "xhigh"}


def test_groq_with_no_options_tables_stops_the_read() -> None:
    with pytest.raises(ext.ExtractError):
        ext.parse_groq("nothing here", [])


def test_zai_reads_the_overall_and_the_per_family_statement() -> None:
    assert ext.parse_zai(ZAI) == {"GLM-5.2": "max", "GLM-5.3": "max", "GLM-5.3-FLASH": "max"}


def test_zai_with_no_stated_default_stops_the_read() -> None:
    with pytest.raises(ext.ExtractError):
        ext.parse_zai(
            ZAI.replace("Available values: `max` (default and recommended", "Values: `max`")
        )


def test_a_word_outside_the_known_levels_never_reads_as_a_default() -> None:
    with pytest.raises(ext.ExtractError, match="known effort level"):
        ext.parse_xai(XAI.replace('"high"` (default)', '"turbo"` (default)'))


def _reader(stated: dict[str, str]) -> Callable[..., dict[str, str]]:
    return lambda _fetch, _names: stated


def _failing(exc: Exception) -> Callable[..., dict[str, str]]:
    def read(_fetch: Any, _names: Any) -> dict[str, str]:
        raise exc

    return read


def _one_source(monkeypatch: pytest.MonkeyPatch, read: Callable[..., dict[str, str]]) -> None:
    monkeypatch.setattr(ext, "SOURCES", {"xai-api": (read, "https://example.test/x")})


def test_a_vendor_change_lands_in_the_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    _one_source(monkeypatch, _reader({"Grok 4.7": "xhigh"}))
    snapshot, review = ext.refresh({"xai-api": {"Grok 4.7": "high"}}, str, [])
    assert snapshot["xai-api"] == {"Grok 4.7": "xhigh"}
    assert review == []


def test_a_source_that_stops_parsing_keeps_its_entry_and_files_a_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _one_source(monkeypatch, _failing(ext.ExtractError("reworded")))
    snapshot, review = ext.refresh({"xai-api": {"Grok 4.7": "high"}}, str, [])
    assert snapshot["xai-api"] == {"Grok 4.7": "high"}
    assert [title for title, _ in review] == ["chore(default-efforts): could not read xai-api"]


def test_an_empty_read_is_a_failed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _one_source(monkeypatch, _reader({}))
    snapshot, review = ext.refresh({"xai-api": {"Grok 4.7": "high"}}, str, [])
    assert snapshot["xai-api"] == {"Grok 4.7": "high"}
    assert len(review) == 1


def test_a_404_is_a_moved_page_not_a_blip(monkeypatch: pytest.MonkeyPatch) -> None:
    _one_source(monkeypatch, _failing(requests.HTTPError("404 Client Error")))
    _, review = ext.refresh({}, str, [])
    assert len(review) == 1


@pytest.mark.parametrize("exc", [requests.ConnectionError("down"), requests.Timeout("slow")])
def test_a_blip_keeps_the_entry_without_filing_an_issue(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    _one_source(monkeypatch, _failing(exc))
    snapshot, review = ext.refresh({"xai-api": {"Grok 4.7": "high"}}, str, [])
    assert snapshot["xai-api"] == {"Grok 4.7": "high"}
    assert review == []


def test_a_model_the_vendor_stops_naming_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    _one_source(monkeypatch, _reader({"Grok 4.7": "high"}))
    committed = {"xai-api": {"Grok 4.6": "high", "Grok 4.7": "high"}}
    snapshot, review = ext.refresh(committed, str, [])
    assert snapshot["xai-api"] == {"Grok 4.7": "high"}
    assert ['"Grok 4.6"' in title for title, _ in review] == [True]


def _models(*names: str) -> list[dict[str, str]]:
    return [{"id": name.lower().replace(" ", "-"), "name": name} for name in names]


def _write(directory: Path, name: str, data: Any) -> None:
    (directory / name).write_text(json.dumps(data))


def test_claude_code_takes_named_defaults_then_the_blanket(tmp_path: Path) -> None:
    _write(
        tmp_path, "claude-code-effort.json", {"default_effort": {"*": "high", "Opus 5.5": "xhigh"}}
    )
    models = _models("Opus 5.5", "Sonnet 5", "Haiku 4.5")
    method = {
        "id": "claude-code",
        "supports_models": ["opus-5.5", "sonnet-5", "haiku-4.5"],
        "effort_levels_by_model": {"opus-5.5": ["high", "xhigh"], "sonnet-5": ["high"]},
    }
    build_catalog._attach_default_efforts([method], models, tmp_path)
    # Haiku 4.5 has no dial, so no default, whatever the blanket says.
    assert method["default_effort_by_model"] == {"opus-5.5": "xhigh", "sonnet-5": "high"}


def test_a_one_word_default_covers_every_model_on_the_method(tmp_path: Path) -> None:
    _write(tmp_path, "deepseek-thinking.json", {"effort_default": "max"})
    method = {"id": "deepseek-api", "supports_models": ["a", "b"], "effort_levels": ["high", "max"]}
    build_catalog._attach_default_efforts([method], _models("A", "B"), tmp_path)
    assert method["default_effort_by_model"] == {"a": "max", "b": "max"}


def test_one_source_can_feed_two_surfaces_and_stays_per_surface(tmp_path: Path) -> None:
    _write(tmp_path, "default-efforts.json", {"codex": {"A": "low"}, "openai-api": {"A": "medium"}})
    methods = [
        {"id": "codex-cli", "supports_models": ["a"]},
        {"id": "codex-api", "supports_models": ["a"]},
        {"id": "openai-api", "supports_models": ["a"]},
    ]
    build_catalog._attach_default_efforts(methods, _models("A"), tmp_path)
    assert [m["default_effort_by_model"] for m in methods] == [
        {"a": "low"},
        {"a": "low"},
        {"a": "medium"},
    ]


def test_a_word_no_level_or_dial_allows_is_dropped(tmp_path: Path) -> None:
    _write(
        tmp_path, "gemini-thinking.json", {"level_defaults": {"A": "on", "B": "max", "C": "low"}}
    )
    method = {
        "id": "google-api",
        "supports_models": ["a", "b", "c"],
        "effort_levels_by_model": {"a": ["low"], "b": ["low"], "c": ["low"]},
    }
    build_catalog._attach_default_efforts([method], _models("A", "B", "C"), tmp_path)
    assert method["default_effort_by_model"] == {"c": "low"}


def test_a_method_with_no_source_has_no_key(tmp_path: Path) -> None:
    _write(tmp_path, "default-efforts.json", {"xai-api": {}})
    methods = [
        {"id": "cursor", "supports_models": ["a"]},
        {"id": "xai-api", "supports_models": ["a"]},
    ]
    build_catalog._attach_default_efforts(methods, _models("A"), tmp_path)
    assert all("default_effort_by_model" not in m for m in methods)


def test_a_vendor_moving_a_default_flows_to_the_catalog_with_no_other_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: the same selector, the snapshot alone moved. Run against
    real files, moving the real value, so no vendor value is pinned here."""
    for name in {row[0] for row in build_catalog.EFFORT_SOURCES}:
        shutil.copy(UPDATE / name, tmp_path / name)
    monkeypatch.setattr(build_catalog, "_UPDATE_DIR", tmp_path)
    before = build_catalog.build_catalog()
    method = next(m for m in before["access_methods"] if m["id"] == "claude-code")
    mid = next(iter(method["default_effort_by_model"]))
    name = next(m["name"] for m in before["models"] if m["id"] == mid)
    moved = next(
        level
        for level in method["effort_levels_by_model"][mid]
        if level != method["default_effort_by_model"][mid]
    )

    snapshot = json.loads((tmp_path / "claude-code-effort.json").read_text())
    snapshot["default_effort"][name] = moved
    (tmp_path / "claude-code-effort.json").write_text(json.dumps(snapshot))

    after = build_catalog.build_catalog()
    method = next(m for m in after["access_methods"] if m["id"] == "claude-code")
    assert method["default_effort_by_model"][mid] == moved

    sys.path.insert(0, str(UPDATE))
    import validate_effort_conformance as gate

    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    assert gate.check_default_effort(selector, snapshot) == []


@pytest.mark.parametrize("mid", sorted(METHODS))
def test_a_published_default_is_a_level_the_model_has(mid: str) -> None:
    method = METHODS[mid]
    by_model = method.get("effort_levels_by_model")
    for model, level in method.get("default_effort_by_model", {}).items():
        assert model in method["supports_models"]
        assert level in build_catalog.LEVEL_ORDER
        if by_model is not None:
            assert level in by_model[model]
        elif "effort_levels" in method:
            assert level in method["effort_levels"]


def test_every_default_source_names_a_real_method() -> None:
    for _, _, method_ids in build_catalog.DEFAULT_SOURCES:
        assert set(method_ids) <= set(METHODS)


def test_every_extracted_vendor_reaches_a_method() -> None:
    keys = {key for name, key, _ in build_catalog.DEFAULT_SOURCES if name == "default-efforts.json"}
    assert keys == set(ext.SOURCES)


def test_the_snapshot_is_refresh_data_in_every_lane() -> None:
    path = "update/default-efforts.json"
    assert path in automation_integrity.INPUTS
    assert tuple(automation_integrity.INPUTS) == security_catalog.DATA_PATHS
    assert path in cron_pr.POLICIES["update-default-efforts.yml"][1]


def test_the_cron_merges_through_the_validated_lane() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "update-default-efforts.yml").read_text()
    merger = (REPO_ROOT / ".github" / "workflows" / "merge-refresh.yml").read_text()
    name = workflow.split("name: ", 1)[1].splitlines()[0]
    assert f"      - {name}\n" in merger
    assert "runs-on: ubuntu-latest" in workflow
    assert "chore/default-efforts-refresh-" in workflow
