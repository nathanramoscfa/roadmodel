# tests/test_edits.py
"""Tests for update/edits.py — the crons' find/replace output contract.

The refresh crons return edits instead of re-emitting the ~180 KB selector
(which was ~85% of their API bill). An edit that can't be applied unambiguously
must fail the run: a skipped edit would ship a half-applied refresh.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

UPDATE_DIR = Path(__file__).resolve().parent.parent / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import edits  # noqa: E402

DOC = '<model id="a" price="1"/>\n<model id="b" price="1"/>\n'


def test_edits_apply_in_order() -> None:
    out = edits.apply_edits(
        DOC,
        [
            {"find": 'id="a" price="1"', "replace": 'id="a" price="2"'},
            {"find": 'id="a" price="2"', "replace": 'id="a" price="3"'},
        ],
    )
    assert out == '<model id="a" price="3"/>\n<model id="b" price="1"/>\n'


def test_empty_edit_list_keeps_the_file() -> None:
    assert edits.apply_edits(DOC, []) == DOC


def test_missing_find_fails() -> None:
    with pytest.raises(edits.EditError, match="not found"):
        edits.apply_edits(DOC, [{"find": 'id="c"', "replace": "x"}])


def test_ambiguous_find_fails() -> None:
    with pytest.raises(edits.EditError, match="matches 2 places"):
        edits.apply_edits(DOC, [{"find": 'price="1"', "replace": 'price="9"'}])


@pytest.mark.parametrize(
    "bad",
    [{"find": "", "replace": "x"}, {"find": 'id="a"'}, "not-an-object"],
)
def test_malformed_edit_fails(bad: object) -> None:
    with pytest.raises(edits.EditError):
        edits.apply_edits(DOC, [bad])


def test_resolve_prefers_edits_and_accepts_the_old_full_file_shape() -> None:
    by_edit = {"edits": [{"find": 'id="b" price="1"', "replace": 'id="b" price="5"'}]}
    assert 'id="b" price="5"' in edits.resolve_file(by_edit, "roadmodel_txt", DOC)
    assert edits.resolve_file({"roadmodel_txt": "whole"}, "roadmodel_txt", DOC) == "whole"
    with pytest.raises(edits.EditError, match="neither"):
        edits.resolve_file({"summary": "x"}, "roadmodel_txt", DOC)


def test_real_answer_outranks_a_template_fence() -> None:
    template = {"edits": [{"find": "...", "replace": "..."}]}
    real = {"edits": [{"find": 'id="a" price="1"', "replace": 'id="a" price="2"'}]}
    assert edits.payload_size(real, "roadmodel_txt") > edits.payload_size(template, "roadmodel_txt")


def test_every_cron_prompt_asks_for_edits() -> None:
    """No prompt may drift back to the whole-file contract."""
    for prompt in sorted(UPDATE_DIR.glob("prompt*.md")):
        output_section = prompt.read_text().split("# Output format", 1)[1]
        assert '"edits"' in output_section, prompt.name
        assert "roadmodel_txt" not in output_section, prompt.name
        assert "model_tier_cost_scale_md" not in output_section, prompt.name
