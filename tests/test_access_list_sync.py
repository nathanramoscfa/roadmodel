"""New models reach every access list on their own.

Two halves (#853 left Sonnet 5 alive for four days because Sonnet 5.5 was
missing from two methods' lists):

- OpenRouter's list is synced, not hand-kept: update/extract_openrouter_models.py
  maps OpenRouter's public model list onto catalog ids, and the catalog cron
  adds them to the method (merge_catalog.py --sync-method openrouter).
- Near-miss detection: update/supersede.py names a same-maker model that would
  supersede an older one but for coverage; the catalog cron checks each
  (method, model) pair, a pair that lasts three days files one deduped issue,
  and update/close_resolved_issues.py closes it once the pair resolves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import close_resolved_issues  # noqa: E402
import extract_openrouter_models as orx  # noqa: E402
import supersede  # noqa: E402
import update_models  # noqa: E402

CATS = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")


def _model(mid: str, name: str, price_in: float, price_out: float, aa: float) -> str:
    ratings = " ".join(f'tier-{c}="A"' for c in CATS)
    return (
        f'<model id="{mid}" name="{name}"\n'
        f'       input-price-per-1m="${price_in:.2f}" output-price-per-1m="${price_out:.2f}"\n'
        f'       jurisdiction="us" {ratings}\n'
        f'       headline-benchmarks="AA Intelligence Index {aa}" pricing-notes="" best-for=""/>'
    )


def _selector(methods: dict[str, tuple[str, list[str]]], *models: str) -> str:
    method_xml = "\n".join(
        f'<method id="{mid}" name="{mid}" provider="{prov}" supports-models="{",".join(ids)}"/>'
        for mid, (prov, ids) in methods.items()
    )
    return (
        '<model-options>\n<tier cost="high">\n'
        + "\n".join(models)
        + "\n</tier>\n</model-options>\n<access-methods>\n"
        + method_xml
        + "\n</access-methods>\n"
    )


OLD = _model("sonnet-old", "Sonnet Old", 2, 10, 40)
NEW = _model("sonnet-new", "Sonnet New", 2, 10, 50)
# The maker's own API lists both; its chat app lists only the old model.
GAP = {
    "maker-api": ("maker", ["sonnet-old", "sonnet-new"]),
    "maker-web": ("maker", ["sonnet-old"]),
}
COVERED = {
    "maker-api": ("maker", ["sonnet-old", "sonnet-new"]),
    "maker-web": ("maker", ["sonnet-old", "sonnet-new"]),
}


def _near(text: str) -> list[supersede.NearMiss]:
    return supersede.near_misses(text, supersede.parse_models(text, {}))


# --------------------------------------------------------------------------- #
# Near-miss detection
# --------------------------------------------------------------------------- #


def test_a_successor_missing_on_one_method_is_a_near_miss() -> None:
    text = _selector(GAP, OLD, NEW)
    assert supersede.successors(text, supersede.parse_models(text, {})) == {}
    found = _near(text)
    assert found == [supersede.NearMiss("sonnet-old", "sonnet-new", ("maker-web",))]
    assert found[0].line() == "NEAR-MISS sonnet-old -> sonnet-new: missing on maker-web"
    assert supersede.parse_near_miss(found[0].line()) == found[0]


def test_full_coverage_supersedes_and_leaves_no_near_miss() -> None:
    text = _selector(COVERED, OLD, NEW)
    assert supersede.successors(text, supersede.parse_models(text, {})) == {
        "sonnet-old": "sonnet-new"
    }
    assert _near(text) == []


def test_a_model_failing_another_test_is_no_near_miss() -> None:
    dearer = _model("sonnet-new", "Sonnet New", 3, 15, 50)
    assert _near(_selector(GAP, OLD, dearer)) == []


def test_the_cli_prints_near_misses_and_keeps_only_lasting_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = tmp_path / "now.txt"
    now.write_text(_selector(GAP, OLD, NEW))
    covered_then = tmp_path / "then-covered.txt"
    covered_then.write_text(_selector(COVERED, OLD, NEW))
    gap_then = tmp_path / "then-gap.txt"
    gap_then.write_text(_selector(GAP, OLD, NEW))

    assert supersede.main(["--near-misses", "--selector", str(now)]) == 0
    assert capsys.readouterr().out.strip() == (
        "NEAR-MISS sonnet-old -> sonnet-new: missing on maker-web"
    )
    # Three days ago the methods covered it: not a lasting near-miss.
    supersede.main(
        ["--near-misses", "--selector", str(now), "--persisted-since", str(covered_then)]
    )
    assert capsys.readouterr().out.strip() == ""
    supersede.main(["--near-misses", "--selector", str(now), "--persisted-since", str(gap_then)])
    assert "NEAR-MISS sonnet-old -> sonnet-new" in capsys.readouterr().out
    # --near-misses never writes.
    assert now.read_text() == _selector(GAP, OLD, NEW)


def test_a_near_miss_issue_closes_once_the_pair_resolves() -> None:
    title = close_resolved_issues.near_miss_title("sonnet-old", "sonnet-new")
    assert title == 'chore(catalog): near-miss supersession "sonnet-old" -> "sonnet-new"'
    resolve = close_resolved_issues.resolution
    assert resolve(title, set(), set(), {("sonnet-old", "sonnet-new")}) is None
    reason = resolve(title, set(), set(), set())
    assert reason is not None and "`sonnet-new`" in reason
    # Without the rule (it failed to evaluate) the issue stays open.
    assert resolve(title, set(), set(), None) is None


def test_the_catalog_pass_gets_targeted_checks_for_each_pair() -> None:
    methods = dict(GAP, openrouter=("openrouter", ["sonnet-old"]))
    block = update_models.near_miss_block(_selector(methods, OLD, NEW), {})
    assert block.startswith("<near_miss_checks>") and block.endswith("</near_miss_checks>")
    assert "- maker-web: sonnet-new (Sonnet New), which would supersede sonnet-old" in block
    # OpenRouter is synced by code after the pass; the pass skips it.
    assert "openrouter:" not in block
    msg = update_models.build_user_message(
        "sel", "cs", [], [], target="selector", near_miss_checks=block
    )
    assert block in msg
    msg = update_models.build_user_message(
        "sel", "cs", [], [], target="cost_scale", near_miss_checks=block
    )
    assert block not in msg
    assert update_models.near_miss_block(_selector(COVERED, OLD, NEW), {}) == ""


def test_the_prompt_runs_targeted_checks_and_keeps_only_ollama_hand_kept() -> None:
    prompt = (UPDATE_DIR / "prompt.md").read_text()
    assert "### Targeted checks (`<near_miss_checks>`)" in prompt
    assert '`ollama` (`billing="local"`) is hand-maintained' in prompt
    assert "`openrouter` is synced by code after this pass" in prompt
    assert "point-in-time snapshot" not in prompt


# --------------------------------------------------------------------------- #
# OpenRouter sync
# --------------------------------------------------------------------------- #

CATALOG_SELECTOR = _selector(
    {"openrouter": ("openrouter", ["opus-4.8"])},
    _model("claude-sonnet-5-5", "Sonnet 5.5", 2, 10, 56),
    _model("opus-4.8", "Opus 4.8", 5, 25, 42),
    _model("claude-4.5-haiku", "Haiku 4.5", 1, 5, 30),
    _model("gemini-3-pro", "Gemini 3 Pro", 2, 12, 41),
    _model("gemini-3-flash", "Gemini 3 Flash", 0.5, 3, 26),
    _model("deepseek-flash", "DeepSeek-V4.1-Flash", 0.1, 0.4, 35),
)


def _entry(ident: str, name: str, outputs: tuple[str, ...] = ("text",)) -> dict[str, Any]:
    return {"id": ident, "name": name, "architecture": {"output_modalities": list(outputs)}}


ENTRIES = [
    _entry("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5"),
    _entry("anthropic/claude-sonnet-5.5:batch", "Anthropic: Claude Sonnet 5.5 (batch)"),
    _entry("~anthropic/claude-sonnet-latest", "Anthropic: Claude Sonnet Latest"),
    _entry("anthropic/claude-opus-4.8", "Anthropic: Claude Opus 4.8"),
    _entry("anthropic/claude-haiku-4.5", "Anthropic: Claude Haiku 4.5"),
    _entry(
        "google/gemini-3-pro-image",
        "Google: Nano Banana Pro (Gemini 3 Pro Image)",
        ("image", "text"),
    ),
    _entry("google/gemini-3-flash-preview", "Google: Gemini 3 Flash Preview"),
    _entry("deepseek/deepseek-v4.1-flash", "DeepSeek: DeepSeek V4.1 Flash"),
    _entry("deepseek/deepseek-v4-flash", "DeepSeek: DeepSeek V4 Flash 0423"),
    _entry("qwen/qwen3.8-max", "Qwen: Qwen3.8 Max"),
]


def test_openrouter_models_map_to_catalog_ids_by_normalized_name() -> None:
    ids = orx.map_models(
        ENTRIES, CATALOG_SELECTOR, {"google/gemini-3-flash-preview": "gemini-3-flash"}
    )
    # Sonnet 5.5 by id, Opus 4.8 with "claude-" dropped, Haiku 4.5 and the
    # DeepSeek flash model by display name, Gemini 3 Flash by the exception map.
    # Left out: the :batch variant, the ~latest alias, the image endpoint, a
    # different DeepSeek model and an uncatalogued one.
    assert ids == [
        "claude-sonnet-5-5",
        "opus-4.8",
        "claude-4.5-haiku",
        "gemini-3-flash",
        "deepseek-flash",
    ]


def test_without_the_exception_a_preview_endpoint_does_not_map() -> None:
    assert "gemini-3-flash" not in orx.map_models(ENTRIES, CATALOG_SELECTOR, {})


def test_the_extractor_fails_open_and_reads_a_local_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sel = tmp_path / "selector.txt"
    sel.write_text(CATALOG_SELECTOR)
    models = tmp_path / "models.json"
    models.write_text(json.dumps({"data": ENTRIES}))
    assert orx.main(["--input", str(models), "--selector", str(sel)]) == 0
    assert "claude-sonnet-5-5" in capsys.readouterr().out.split()
    assert orx.main(["--input", str(tmp_path / "missing.json"), "--selector", str(sel)]) == 0
    assert capsys.readouterr().out == ""


def test_the_exception_map_names_catalogued_models_only() -> None:
    exceptions = orx.load_exceptions()
    assert exceptions, "update/openrouter-model-map.json is empty or unreadable"
    catalogued = {
        m["id"] for m in json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())["models"]
    }
    assert set(exceptions.values()) <= catalogued
    assert all("/" in k and ":" not in k for k in exceptions)


def test_the_catalog_cron_syncs_openrouter_and_flags_lasting_near_misses() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert "python update/extract_openrouter_models.py" in wf
    assert 'python update/merge_catalog.py --sync-method openrouter --ids "${openrouter_ids}"' in wf
    assert "--near-misses" in wf and "--persisted-since /tmp/selector-3d.txt" in wf
    assert 'title="chore(catalog): near-miss supersession' in wf
    # The title the cron files is the title the closer recognizes.
    assert close_resolved_issues._NEAR_MISS_ISSUE.match(
        close_resolved_issues.near_miss_title("a", "b")
    )
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    assert "synced daily from openrouter.ai/models" in selector


def test_a_same_day_rerun_refreshes_the_days_open_pr() -> None:
    # A dispatch after the scheduled run finds the day's branch on origin; a
    # plain push was refused and the re-run opened nothing.
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert 'git ls-remote --exit-code --heads origin "$BRANCH"' in wf
    assert 'git push --force -u origin "$BRANCH"' in wf
    assert 'gh pr list --head "$BRANCH" --state open' in wf
    assert 'gh pr edit "${PR_URL}" --body "${body}"' in wf
    # The human-review gate stays: nothing in the catalog cron merges its PR.
    assert "gh pr merge" not in "\n".join(
        line
        for line in wf.splitlines()
        if not line.lstrip().startswith("#") and "squash-merge:" not in line
    )


def test_each_catalogued_model_carries_its_largest_listed_context_window(tmp_path: Path) -> None:
    entries = [
        {
            **_entry("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5"),
            "context_length": 200000,
        },
        {
            **_entry("anthropic/claude-sonnet-5.5:extended", "Anthropic: Claude Sonnet 5.5"),
            "context_length": 1000000,
        },
        {
            **_entry("anthropic/claude-haiku-4.5", "Anthropic: Claude Haiku 4.5"),
            "top_provider": {"context_length": 200000},
        },
        {**_entry("qwen/qwen3.8-max", "Qwen: Qwen3.8 Max"), "context_length": 128000},
    ]
    windows = orx.context_windows(entries, CATALOG_SELECTOR, {})
    # The largest of a model's routes; an uncatalogued model is left out.
    assert windows == {"claude-4.5-haiku": 200000, "claude-sonnet-5-5": 1000000}
    path = tmp_path / "context-windows.json"
    path.write_text(json.dumps({"models": {"opus-4.8": 1000000, "claude-4.5-haiku": 100000}}))
    assert orx.write_context_windows(path, windows) is True
    # A model no longer listed keeps its last known window; a listed one is refreshed.
    assert json.loads(path.read_text())["models"] == {
        "claude-4.5-haiku": 200000,
        "claude-sonnet-5-5": 1000000,
        "opus-4.8": 1000000,
    }
    assert orx.write_context_windows(path, windows) is False


def test_the_catalog_cron_refreshes_the_context_windows() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert "extract_openrouter_models.py --context-windows docs/context-windows.json" in wf
    assert "docs/context-windows.json" in wf.split("git add", 1)[1].split("\n", 1)[0]
    committed = json.loads((REPO_ROOT / "docs" / "context-windows.json").read_text())["models"]
    catalogued = {
        m["id"] for m in json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())["models"]
    }
    assert committed and set(committed) <= catalogued
