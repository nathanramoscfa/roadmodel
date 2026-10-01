"""update/rating_guard.py — the rating rules, held in code.

The AI curation passes may move a letter only as update/prompt.md allows; the
guard compares the committed selector with a pass's proposal and reverts any
edit that breaks a rule. Every rule is tested both ways: the edit it allows
survives, the edit it forbids is reverted to the committed (or placeholder)
letter with a reason.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "rating_guard", REPO_ROOT / "update" / "rating_guard.py"
)
assert _spec is not None and _spec.loader is not None
rg = importlib.util.module_from_spec(_spec)
# Dataclasses resolve their string annotations through sys.modules.
sys.modules["rating_guard"] = rg
_spec.loader.exec_module(rg)

LETTERS = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")


def _model(mid: str, name: str, **tiers: str) -> str:
    t = {c: tiers.get(c.replace("-", "_"), "B") for c in LETTERS}
    attrs = " ".join(f'tier-{c}="{t[c]}"' for c in LETTERS)
    return (
        f'      <model id="{mid}" name="{name}" output-price-per-1m="$10" {attrs} best-for="x" />'
    )


def _selector(*elements: str) -> str:
    body = "\n".join(elements)
    return f'<selector>\n<model-options>\n  <tier cost="medium">\n{body}\n  </tier>\n</model-options>\n</selector>\n'


BASE = _selector(
    _model("alpha-2", "Alpha 2", coding="A", planning="A", agentic="A", speed="B"),
    _model("beta-flash", "Beta Flash", planning="B", speed="S"),
)
# alpha-2 is measured on every derived category; beta-flash on none.
BENCH = {
    "alpha-2": {
        "evaluations": {
            "scicode": 0.6,
            "terminalbench_v4_0": 0.4,
            "lcr": 0.8,
            "hle": 0.5,
        }
    }
}


def _tiers(selector: str, mid: str) -> dict[str, str]:
    return rg.models(selector)[mid].tiers


def test_the_committed_selector_passes_its_own_guard() -> None:
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    guarded, reverts = rg.guard(selector, selector, "", {})
    assert reverts == [] and guarded == selector


def test_a_declared_one_step_move_with_its_evidence_survives() -> None:
    proposed = BASE.replace(
        'id="beta-flash" name="Beta Flash" output-price-per-1m="$10" tier-coding="B" tier-planning="B"',
        'id="beta-flash" name="Beta Flash" output-price-per-1m="$10" tier-coding="B" tier-planning="A"',
    )
    decl = "tier rating updated: beta-flash tier-planning B→A — LMArena shows 1402 Elo"
    guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
    assert reverts == [] and _tiers(guarded, "beta-flash")["planning"] == "A"


def test_an_undeclared_or_wrongly_sourced_move_is_reverted() -> None:
    proposed = BASE.replace(
        'tier-planning="B" tier-agentic="B" tier-multimodal="B"',
        'tier-planning="A" tier-agentic="B" tier-multimodal="B"',
    )
    guarded, reverts = rg.guard(BASE, proposed, "", BENCH)
    assert _tiers(guarded, "beta-flash")["planning"] == "B"
    assert "no 'tier rating updated' declaration" in reverts[0].reason
    # Planning moves on LMArena, not on MMMU.
    decl = "tier rating updated: beta-flash tier-planning B→A — MMMU shows 70.1"
    guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
    assert _tiers(guarded, "beta-flash")["planning"] == "B"
    assert "cites no planning evidence" in reverts[0].reason
    # A declaration that disagrees with the edit carries nothing.
    decl = "tier rating updated: beta-flash tier-planning C→B — LMArena shows 1402"
    guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
    assert "its declaration says C→B" in reverts[0].reason


def test_a_letter_moves_one_step_at_most() -> None:
    proposed = BASE.replace(
        'tier-planning="B" tier-agentic="B" tier-multimodal="B"',
        'tier-planning="S" tier-agentic="B" tier-multimodal="B"',
    )
    decl = "tier rating updated: beta-flash tier-planning B→S — LMArena shows 1500 (leader 1502)"
    guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
    assert _tiers(guarded, "beta-flash")["planning"] == "B"
    assert reverts[0].reason == "a letter moves at most one step per run"


def test_a_move_into_s_needs_the_leader_within_five_points() -> None:
    proposed = BASE.replace(
        'tier-coding="A" tier-planning="A"', 'tier-coding="A" tier-planning="S"'
    )
    ok = "tier rating updated: alpha-2 tier-planning A→S — LMArena shows 1499 (leader 1502)"
    assert rg.guard(BASE, proposed, ok, BENCH)[1] == []
    for decl, why in [
        ("tier rating updated: alpha-2 tier-planning A→S — LMArena shows 1499", "leader"),
        (
            "tier rating updated: alpha-2 tier-planning A→S — LMArena shows 1480 (leader 1502)",
            "gap 22",
        ),
    ]:
        guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
        assert _tiers(guarded, "alpha-2")["planning"] == "A"
        assert why in reverts[0].reason


def test_derived_letters_move_only_through_the_derivation() -> None:
    # beta-flash is unmeasured: its coding estimate holds, declared or not.
    proposed = BASE.replace(
        'name="Beta Flash" output-price-per-1m="$10" tier-coding="B"',
        'name="Beta Flash" output-price-per-1m="$10" tier-coding="A"',
    )
    decl = "tier rating updated: beta-flash tier-coding B→A — SWE-bench shows 70.0"
    guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
    assert _tiers(guarded, "beta-flash")["coding"] == "B"
    assert "stays until AA measures it" in reverts[0].reason
    # alpha-2 is measured: the guard leaves it to update/derive_ratings.py.
    proposed = BASE.replace(
        'name="Alpha 2" output-price-per-1m="$10" tier-coding="A"',
        'name="Alpha 2" output-price-per-1m="$10" tier-coding="C"',
    )
    assert rg.guard(BASE, proposed, "", BENCH)[1] == []


def test_a_new_model_starts_from_its_predecessor_found_in_code() -> None:
    new = _model("alpha-3", "Alpha 3", coding="A", planning="A", agentic="A", speed="A")
    proposed = BASE.replace("  </tier>", new + "\n  </tier>")
    # alpha-2 is the same series at a lower version: its letters hold with no
    # declaration at all; the speed change needs grounding.
    guarded, reverts = rg.guard(BASE, proposed, "", BENCH)
    assert [(r.id, r.category, r.kept) for r in reverts] == [("alpha-3", "speed", "B")]
    assert "inherited from `alpha-2`" in reverts[0].reason
    grounded = "tier rating grounded: alpha-3 tier-speed A — Artificial Analysis shows 145 tokens/s"
    guarded, reverts = rg.guard(BASE, proposed, grounded, BENCH)
    assert reverts == [] and _tiers(guarded, "alpha-3")["speed"] == "A"


def test_a_new_model_without_a_same_series_predecessor_starts_at_b() -> None:
    new = _model("gamma-mini", "Gamma Mini", coding="S", planning="S", agentic="S", speed="S")
    proposed = BASE.replace("  </tier>", new + "\n  </tier>")
    # Declaring an unrelated model as the predecessor buys nothing.
    guarded, reverts = rg.guard(
        BASE, proposed, "placeholder tiers inherited from alpha-2: gamma-mini", BENCH
    )
    tiers = _tiers(guarded, "gamma-mini")
    assert tiers == {**{c: "B" for c in LETTERS}, "speed": "S"}  # "Mini" keeps speed S
    assert {r.category for r in reverts} == {"coding", "planning", "agentic"}
    assert "no same-series predecessor" in reverts[0].reason


def test_the_predecessor_is_the_highest_same_series_version_below() -> None:
    base = rg.models(
        _selector(
            _model("claude-sonnet-4.6", "Sonnet 4.6"),
            _model("claude-sonnet-5", "Sonnet 5"),
            _model("claude-opus-5", "Opus 5"),
            _model("gpt-5.6-luna", "GPT-5.6 Luna"),
        )
    )
    assert rg.predecessor("claude-sonnet-5-5", base) == "claude-sonnet-5"
    assert rg.predecessor("claude-opus-5-5", base) == "claude-opus-5"
    assert rg.predecessor("gpt-6-luna", base) == "gpt-5.6-luna"
    assert rg.predecessor("claude-sonnet-4.5", base) is None  # older than every Sonnet here
    assert rg.predecessor("gpt-6-luna-mini", base) is None


def test_long_context_and_knowledge_hold_their_placeholder_until_aa_measures() -> None:
    new = _model("delta-1", "Delta 1", long_context="S")
    proposed = BASE.replace("  </tier>", new + "\n  </tier>")
    decl = "tier rating grounded: delta-1 tier-long-context S — RULER shows 95 (leader 96)"
    guarded, reverts = rg.guard(BASE, proposed, decl, BENCH)
    assert _tiers(guarded, "delta-1")["long-context"] == "B"
    assert "no source outside Artificial Analysis" in reverts[0].reason


def test_a_tracker_pass_moves_no_letter() -> None:
    proposed = BASE.replace('tier-speed="S"', 'tier-speed="A"')
    guarded, reverts = rg.guard(BASE, proposed, "", BENCH)
    assert guarded == BASE and len(reverts) == 1


def test_same_series_reads_name_words() -> None:
    assert rg.same_series("claude-sonnet-5", "claude-sonnet-5-5")
    assert rg.same_series("opus-4.8", "claude-opus-5")
    assert rg.same_series("gpt-5.6-luna", "gpt-6-luna")
    assert not rg.same_series("gpt-5.5", "gpt-5.5-mini")
    assert not rg.same_series("deepseek-v4-pro", "deepseek-flash")


def test_cli_applies_reverts_and_reports(tmp_path: Path) -> None:
    base = tmp_path / "base.txt"
    base.write_text(BASE)
    selector = tmp_path / "selector.txt"
    selector.write_text(BASE.replace('tier-speed="S"', 'tier-speed="A"'))
    report = tmp_path / "report.md"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "update" / "rating_guard.py"),
        "--base",
        str(base),
        "--selector",
        str(selector),
        "--report",
        str(report),
    ]
    check = subprocess.run([*cmd, "--check"], capture_output=True, text=True)
    assert check.returncode == 1 and "proposed A, kept S" in check.stdout
    assert selector.read_text() != BASE  # --check never edits
    applied = subprocess.run([*cmd, "--apply"], capture_output=True, text=True)
    assert applied.returncode == 0
    assert selector.read_text() == BASE
    assert "tier-speed: proposed A, kept S" in report.read_text()
    assert subprocess.run([*cmd, "--check"], capture_output=True, text=True).returncode == 0


def test_the_prompt_documents_the_formats_the_guard_reads() -> None:
    prompt = (REPO_ROOT / "update" / "prompt.md").read_text()
    updated = "tier rating updated: <id> tier-<category> <old>→<new> — <source name> shows <figure>"
    grounded = "tier rating grounded: <id> tier-<category> <letter> — <source name> shows <figure>"
    for fragment in (updated, grounded, "(leader <figure>)", "update/rating_guard.py"):
        assert fragment in prompt, fragment
    # The derived-letter description names the rule agentic follows.
    assert "rank on Terminal-Bench 4.0" in prompt
    # Lines in those formats parse.
    decls = rg.parse_declarations(
        "tier rating updated: m tier-planning B→A — LMArena shows 1402\n"
        "tier rating grounded: m tier-speed A — Artificial Analysis shows 145 tokens/s"
    )
    assert decls[("m", "planning")].old == "B"
    assert decls[("m", "speed")].new == "A" and decls[("m", "speed")].old is None


def test_every_ai_pass_is_guarded() -> None:
    workflows = REPO_ROOT / ".github" / "workflows"
    for name in (
        "update-models",
        "update-claude-code",
        "update-codex",
        "update-gemini",
        "update-deepseek",
    ):
        text = (workflows / f"{name}.yml").read_text()
        assert "python update/rating_guard.py --apply --base /tmp/base-selector.txt" in text, name
    catalog = (workflows / "update-models.yml").read_text()
    # The catalog pass is judged on its own declarations, before the derived
    # overlay sets the measured letters, and its report reaches the PR body.
    assert "--declarations update/.last-warnings.txt" in catalog
    assert catalog.index("rating_guard.py --apply") < catalog.index("derive_ratings.py --write")
    assert "update/.last-rating-guard.md" in catalog


def _bare_defaults_over_a_predecessor(selector: str) -> list[str]:
    models = rg.models(selector)
    stale = []
    for mid, model in models.items():
        pred = rg.predecessor(mid, {k: v for k, v in models.items() if k != mid})
        if pred is None:
            continue
        default, _ = rg.placeholder(model, {})  # the bare B default for this name
        mine = {c: model.tiers[c] for c in rg.ESTIMATED}
        if mine == {c: default[c] for c in rg.ESTIMATED} and mine != {
            c: models[pred].tiers[c] for c in rg.ESTIMATED
        }:
            stale.append(f"{mid} (predecessor {pred})")
    return stale


def test_no_model_keeps_the_b_default_its_predecessor_replaces() -> None:
    """The GPT-6 family entered on 2026-09-25 (#730) with every estimated
    letter at the bare B default, five days before this guard (#794) gave a
    new model its predecessor's letters, and nothing revisited them. GPT-6.1
    Sol then inherited GPT-6 Sol's B. With planning held at B, every backup
    for a planning task went to GPT-5.6 Sol, the model GPT-6 Sol replaces at
    half the price. A model with a same-series predecessor never keeps the
    bare default."""
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    assert _bare_defaults_over_a_predecessor(selector) == []
    # The check sees the case it exists for.
    stale = _selector(
        _model("gpt-5.6-sol", "GPT-5.6 Sol", planning="S", multimodal="A", speed="D"),
        _model("gpt-6-sol", "GPT-6 Sol", coding="S", agentic="S"),
    )
    assert _bare_defaults_over_a_predecessor(stale) == ["gpt-6-sol (predecessor gpt-5.6-sol)"]
