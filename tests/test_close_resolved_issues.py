"""update/close_resolved_issues.py — the crons close their own resolved issues.

Pure tests over resolution(): a cron-filed issue closes once the committed
catalog carries its model (or the discovery lane declined it), and stays open
while the condition still holds; issues of any other shape are never touched.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "close_resolved_issues", REPO_ROOT / "update" / "close_resolved_issues.py"
)
assert _spec is not None and _spec.loader is not None
cri = importlib.util.module_from_spec(_spec)
sys.modules["close_resolved_issues"] = cri
_spec.loader.exec_module(cri)

KEYS = {"claude-opus-5-5", "opus-5-5", "gpt-6-sol", "gemini-3-8-flash"}
DECLINED = {("google", "gemini-2-5-computer-use")}


def test_a_docs_issue_closes_when_its_model_is_in_the_catalog() -> None:
    title = 'chore(catalog): Claude Code docs introduced model "Opus 5.5"'
    assert (
        cri.resolution(title, KEYS, DECLINED)
        == "`Opus 5.5` is in the catalog (docs/model-selector.txt)."
    )
    assert cri.resolution('chore(catalog): Codex docs introduced model "gpt-6-sol"', KEYS, DECLINED)
    assert (
        cri.resolution('chore(catalog): Codex docs introduced model "gpt-6.1-sol"', KEYS, DECLINED)
        is None
    )


def test_a_provider_direct_issue_closes_when_its_model_is_in_the_catalog() -> None:
    title = 'chore(catalog): provider-direct model "Gemini 3.8 Flash" not in <model-options>'
    assert cri.resolution(title, KEYS, DECLINED)


def test_a_discovery_issue_closes_when_added_or_declined() -> None:
    added = 'chore(catalog): provider page prices "openai/gpt-6-sol"; the catalog neither added nor declined it'
    declined = 'chore(catalog): provider page prices "google/Gemini 2.5 Computer Use"; the catalog neither added nor declined it'
    pending = 'chore(catalog): provider page prices "google/Gemini 3.5 Flash-Lite"; the catalog neither added nor declined it'
    assert "in the catalog" in cri.resolution(added, KEYS, DECLINED)  # type: ignore[operator]
    assert "declined in the discovery lane" in cri.resolution(declined, KEYS, DECLINED)  # type: ignore[operator]
    assert cri.resolution(pending, KEYS, DECLINED) is None


def test_other_issues_are_never_touched() -> None:
    for title in (
        "chore(cron): automated refresh pipeline is unhealthy",
        "web: the recommend edge's call to its own E2E mock never returns, locally only",
        'feat(selector): Gemini docs introduced thinking level "ultra"',
    ):
        assert cri.resolution(title, KEYS, DECLINED) is None
