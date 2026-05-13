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
        "I'll produce the JSON now:\n\n"
        '{"roadmodel_txt": "abc", "model_tier_cost_scale_md": "def"}'
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
        "```json\n{\"sample\": true}\n```\n"
        "Here's the real output:\n"
        '{"roadmodel_txt": "real", "model_tier_cost_scale_md": "real"}'
    )
    parsed = parse_result(raw)
    assert parsed["roadmodel_txt"] == "real"


def test_malformed_raises_json_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_result("not JSON at all, no braces")
