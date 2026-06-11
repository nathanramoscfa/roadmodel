# tests/test_update_parse.py
"""Tests for update/update_models.py::parse_result.

Covers the pathological output shapes Opus emits in production:
- Clean JSON object (happy path).
- JSON wrapped in a single outermost markdown fence.
- Sample/template JSON in a ```json … ``` fence ahead of the real object
  (the failure mode flagged by TODO(#5) and the prior commit
  6224d29 "Flag parse_result fenced-template flake").
- Prose preamble or epilogue around the JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

from update_models import parse_result  # noqa: E402


def test_strict_clean_json() -> None:
    raw = '{"roadmodel_txt": "abc", "model_tier_cost_scale_md": "def", "summary": "s"}'
    parsed = parse_result(raw)
    assert parsed["roadmodel_txt"] == "abc"


def test_outer_fence_only() -> None:
    raw = '```json\n{"roadmodel_txt": "abc", "model_tier_cost_scale_md": "def"}\n```'
    parsed = parse_result(raw)
    assert parsed["roadmodel_txt"] == "abc"


def test_prose_preamble_then_json() -> None:
    raw = (
        'I\'ll produce the JSON now:\n\n{"roadmodel_txt": "abc", "model_tier_cost_scale_md": "def"}'
    )
    parsed = parse_result(raw)
    assert parsed["roadmodel_txt"] == "abc"


def test_sample_fenced_template_then_real_json() -> None:
    """The TODO(#5) failure mode — Opus emits a fenced sample with
    placeholder values, then the real JSON below it. The legacy
    first-`{`-to-last-`}` fallback lands on the sample's `{` and
    chokes on `"..."` placeholders."""
    raw = (
        "```json\n"
        '{"roadmodel_txt": "...full file...", "model_tier_cost_scale_md": "...full file...", "summary": "...", "warnings": []}\n'
        "```\n"
        "\n"
        "Given the size, I'll produce the JSON now:\n"
        "\n"
        '{"roadmodel_txt": "<actual content>", "model_tier_cost_scale_md": "<actual content>", "summary": "Refreshed catalog", "warnings": []}'
    )
    parsed = parse_result(raw)
    assert parsed["roadmodel_txt"] == "<actual content>"
    assert parsed["summary"] == "Refreshed catalog"


def test_multiple_sample_fences_then_real_json() -> None:
    raw = (
        "```python\nprint('not JSON')\n```\n"
        '```json\n{"sample": true}\n```\n'
        "Here's the real output:\n"
        '{"roadmodel_txt": "real_content_long_enough", "model_tier_cost_scale_md": "real"}'
    )
    parsed = parse_result(raw)
    assert parsed["roadmodel_txt"] == "real_content_long_enough"


def test_real_json_inside_second_fence() -> None:
    """The cron's actual failure mode in run 25820779529: Opus emits
    a sample fence with placeholder values ("..."), then prose, then
    wraps the REAL JSON in another fence. Both blocks parse as JSON,
    so the discriminator is `roadmodel_txt` length — placeholder is
    short ("..."), real is the entire selector.txt (KB-scale).
    """
    real_content = "<model-selector>" + "x" * 500 + "</model-selector>"
    raw = (
        "Now I'll write the final output:\n\n"
        "```json\n"
        '{"roadmodel_txt": "...", "model_tier_cost_scale_md": "...", "summary": "...", "warnings": []}\n'
        "```\n"
        "\n"
        "Building the real files:\n\n"
        "```json\n"
        '{"roadmodel_txt": "'
        + real_content
        + '", "model_tier_cost_scale_md": "real-content-2", "summary": "Refreshed", "warnings": []}\n'
        "```"
    )
    parsed = parse_result(raw)
    assert parsed["summary"] == "Refreshed"
    assert parsed["roadmodel_txt"] == real_content
    assert "<model-selector>" in parsed["roadmodel_txt"]


def test_malformed_raises_json_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_result("not JSON at all, no braces")


# --------------------------------------------------------------------------- #
# Split-call (two single-file Opus passes) — see update_models.main()
# --------------------------------------------------------------------------- #


def test_cost_scale_pass_discriminates_by_its_own_key() -> None:
    """The cost-scale pass response has NO roadmodel_txt; the real payload must
    be discriminated by `model_tier_cost_scale_md` length, not roadmodel_txt."""
    real = "# Model tier cost scale " + "y" * 500
    raw = (
        "```json\n"
        '{"model_tier_cost_scale_md": "...", "summary": "...", "warnings": []}\n'
        "```\n\nReal output:\n\n"
        '{"model_tier_cost_scale_md": "' + real + '", "summary": "CS refreshed", "warnings": []}'
    )
    parsed = parse_result(raw, primary_key="model_tier_cost_scale_md")
    assert parsed["model_tier_cost_scale_md"] == real
    assert parsed["summary"] == "CS refreshed"
    assert "roadmodel_txt" not in parsed


def test_build_user_message_emit_target_directive() -> None:
    from update_models import build_user_message

    msg = build_user_message("SEL", "CS", [], [], target="cost_scale")
    assert "<emit_target>cost_scale</emit_target>" in msg
    msg_sel = build_user_message("SEL", "CS", [], [], target="selector")
    assert "<emit_target>selector</emit_target>" in msg_sel
    # Legacy two-file contract: no directive when target is omitted.
    assert "<emit_target>" not in build_user_message("SEL", "CS", [], [])


def test_prompt_documents_emit_target() -> None:
    prompt = (UPDATE_DIR / "prompt.md").read_text()
    assert "<emit_target>cost_scale</emit_target>" in prompt
    assert "<emit_target>selector</emit_target>" in prompt
