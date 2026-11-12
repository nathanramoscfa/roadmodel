"""The catalog refresh puts every model Claude Code's docs name on claude-code.

Fable 5.2 reached the Claude Code snapshot on 2026-11-12 but not the
claude-code method: no step read the snapshot's model list, and the AI passes
may only change prices and letters. ``update/claude_code_models.py`` maps the
snapshot's effort table to catalog ids, and ``update-models.yml`` adds them with
the same additive sync the Codex methods use.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import claude_code_models as ccm  # noqa: E402
import merge_catalog  # noqa: E402

SELECTOR = """\
  <model-options>
      <model id="claude-fable-5.2" name="Fable 5.2" cost-tier="$$$$" />
      <model id="claude-fable-5.1" name="Claude Fable 5.1" cost-tier="$$$$" />
      <model id="opus-4.8" name="Opus 4.8" retired-on="2026-10-28" />
      <model id="gpt-6-sol" name="GPT-6 Sol" cost-tier="$$$" />
  </model-options>
"""


def test_the_effort_table_maps_to_live_catalog_ids() -> None:
    table = {"Fable 5.2": [], "Fable 5.1": [], "Opus 4.8": [], "Opus 9": []}
    snapshot = {"per_model_effort": table}
    # A "Claude" prefix keys the same; a retired or uncatalogued name is skipped.
    assert ccm.claude_code_ids(snapshot, SELECTOR) == ["claude-fable-5.2", "claude-fable-5.1"]
    assert ccm.claude_code_ids({}, SELECTOR) == []


def test_the_committed_snapshot_puts_its_models_on_claude_code() -> None:
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    snapshot = json.loads((REPO_ROOT / "update" / "claude-code-effort.json").read_text())
    ids = ccm.claude_code_ids(snapshot, selector)
    assert "claude-opus-5-5" in ids
    synced, _ = merge_catalog.ensure_supported(selector, "claude-code", ids)
    methods = merge_catalog._method_supports_re("claude-code").search(synced)
    assert methods is not None
    assert set(ids) <= set(methods.group(2).split(","))


def test_the_catalog_refresh_runs_the_sync() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert "python update/claude_code_models.py" in workflow
    assert '--sync-method claude-code --ids "${claude_code_ids}"' in workflow
