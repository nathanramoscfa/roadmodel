# tests/test_cron_issue_dedup.py
"""Every cron that files a tracking issue must dedup on an EXACT title.

Five workflows open issues on their own. `gh issue list --search '... in:title'`
looks the safest way to check "is one already open", and is the one that does
not work: GitHub's search index lags behind issue creation, so the search comes
back empty in-run and the cron files the same issue again tomorrow.

That produced 11 duplicate Claude Code issues in 2026-07 (fixed in #420) and
then four copies of the same DeepSeek flag — #542, #543, #544, #545 — between
2026-08-24 and 2026-09-02, because update-models.yml was missed by that fix.

The reliable check is the REST issue list plus an exact-title comparison, so
this test pins both halves for every workflow that creates issues.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

# Either shell-side exact-line matching or jq-side exact-title selection.
EXACT_TITLE_MATCH = (re.compile(r"grep -Fqx"), re.compile(r"select\(\s*\.title\s*=="))


def _code(path: Path) -> str:
    """Workflow text with comment lines dropped.

    The fixed crons explain the old broken pattern in a comment above the new
    one, so a naive scan flags the very files that carry the fix.
    """
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _issue_creating_workflows() -> list[Path]:
    """Scheduled workflows that file issues — the ones that can duplicate.

    Scope is deliberate. A workflow that files an issue once, in response to an
    event (auto-remediate.yml, after exhausting its fix attempts), cannot
    accumulate copies of the same title. Only something that runs again
    tomorrow can, which is exactly what these crons do.
    """
    return [p for p in WORKFLOWS if "gh issue create" in _code(p) and "schedule:" in _code(p)]


def test_there_are_scheduled_issue_creating_workflows() -> None:
    """Guard the guard: if the filter stops matching, the rest passes vacuously."""
    found = {p.name for p in _issue_creating_workflows()}
    assert found >= {
        "update-models.yml",
        "update-claude-code.yml",
        "update-codex.yml",
        "update-gemini.yml",
        "update-deepseek.yml",
    }, f"expected the five refresh crons among issue-filing scheduled workflows, got {found}"


def test_no_workflow_dedups_issues_through_the_search_index() -> None:
    offenders = [
        p.name
        for p in _issue_creating_workflows()
        if re.search(r"gh issue list[^\n]*--search", _code(p))
    ]
    assert not offenders, (
        f"{offenders} dedup open issues via `gh issue list --search`, whose index "
        "lag re-files the same issue daily (#542-#545). List with "
        "`--state open --limit 200 --json title` and compare exact titles."
    )


def test_issue_creating_workflows_compare_exact_titles() -> None:
    offenders = []
    for path in _issue_creating_workflows():
        text = _code(path)
        if not any(pattern.search(text) for pattern in EXACT_TITLE_MATCH):
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} create issues without an exact-title dedup. A substring or "
        "label match is not enough: `gh issue create --label` has not been "
        "applying labels to App-token issues, so a label filter matches nothing "
        "and re-dups forever."
    )
