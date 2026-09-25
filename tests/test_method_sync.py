# tests/test_method_sync.py
"""Deterministic method sync in update/merge_catalog.py.

On 2026-09-25 OpenAI launched GPT-6 Astra/Sol/Luna. The catalog prompt's
supports-models guard refuses three new models at once, so two of them reached
<model-options> with no method at all and the refresh PR went red. A catalogued
model on a provider's own price list is reachable on that provider's API; Codex
publishes its own list. Both are now synced in code, additively.
"""

from __future__ import annotations

import sys
from pathlib import Path

UPDATE_DIR = Path(__file__).resolve().parent.parent / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import merge_catalog as mc  # noqa: E402

SEL = """<model-options>
  <model id="gpt-6-sol" name="GPT-6 Sol"/>
  <model id="gpt-5.5" name="GPT-5.5"/>
</model-options>
<method id="openai-api" name="OpenAI API"
        supports-models="gpt-5.5"/>
<method id="codex-cli" name="Codex" supports-models="gpt-5.5"/>
"""


def test_catalogued_ids_are_added_first_and_uncatalogued_ones_never() -> None:
    out, added = mc.ensure_supported(SEL, "openai-api", ["gpt-6-sol", "gpt-6-luna"])
    assert added == ["gpt-6-sol"]  # gpt-6-luna has no <model> element yet
    assert 'supports-models="gpt-6-sol,gpt-5.5"' in out


def test_sync_is_additive_and_idempotent() -> None:
    once, _ = mc.ensure_supported(SEL, "openai-api", ["gpt-6-sol"])
    twice, added = mc.ensure_supported(once, "openai-api", ["gpt-6-sol", "gpt-5.5"])
    assert added == [] and twice == once
    assert mc.ensure_supported(SEL, "no-such-api", ["gpt-6-sol"]) == (SEL, [])


def test_snapshot_price_list_drives_the_provider_api_method() -> None:
    snap = {"provider": "openai", "models": [{"id": "gpt-5.5"}], "discovered": ["gpt-6-sol"]}
    out, added = mc.apply_method_sync(SEL, [snap])
    assert added == {"openai-api": ["gpt-6-sol"]}
    assert 'id="codex-cli" name="Codex" supports-models="gpt-5.5"' in out  # untouched


def test_shipped_catalog_is_already_in_sync() -> None:
    """Every catalogued model on a provider's committed price list is on its API."""
    text = mc.SELECTOR_PATH.read_text()
    _, added = mc.apply_method_sync(text, mc.provider_snapshots())
    assert added == {}, added


def test_extract_codex_models_can_print_every_recommended_slug(tmp_path: Path) -> None:
    import subprocess

    md = tmp_path / "models.md"
    md.write_text(
        '## Recommended models\n<ModelCard slug="gpt-6-sol" />\n<ModelCard slug="gpt-5.5" />\n'
    )
    out = subprocess.run(
        [
            sys.executable,
            str(UPDATE_DIR / "extract_codex_models.py"),
            "--input",
            str(md),
            "--recommended",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "gpt-6-sol" in out
