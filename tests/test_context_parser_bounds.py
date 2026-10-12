"""Context parsers retain their grammar while bounding adversarial work."""

from __future__ import annotations

import subprocess
import sys

import pytest

from roadmodel.cost import _canonical_tier_name
from roadmodel.scoring import BASELINE_JURISDICTIONS, allowed_jurisdictions, platform_filters


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (" Max ($200/mo)  ", "max"),
        ("Tier (5x)", "tier"),
        ("Tier (outer (inner))", "tier (outer (inner))"),
        ("Tier (first) (last)", "tier (first)"),
        (" (", "("),
        ("   ", ""),
    ],
)
def test_tier_suffix_grammar(name, expected):
    assert _canonical_tier_name(name) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("**Allowed jurisdictions:** `us, eu`", {"us", "eu"}),
        ("**Allowed jurisdictions** :\n\n\tUS, ca", {"us", "ca"}),
        ("**Allowed jurisdictions** !\n**Allowed jurisdictions** jp", {"jp"}),
        ("**Allowed jurisdictions** !", set(BASELINE_JURISDICTIONS)),
    ],
)
def test_jurisdiction_grammar(text, expected):
    assert allowed_jurisdictions(text) == expected


def test_platform_grammar():
    assert platform_filters(
        "\t**platforms.allowed:** `claude-code`, cursor\nplatforms.excluded: api"
    ) == ({"claude-code", "cursor"}, {"api"})
    assert platform_filters("platforms.allowed: (none declared)") == (set(), set())


def test_large_malformed_context_completes_without_backtracking():
    source = """
from roadmodel.cost import _canonical_tier_name
from roadmodel.scoring import allowed_jurisdictions, platform_filters
assert _canonical_tier_name(' ' * 1_000_000 + 'x') == 'x'
allowed_jurisdictions('**Allowed jurisdictions**' + '\\t' * 1_000_000 + '!')
platform_filters('platforms.allowed:' + '\\t' * 1_000_000 + '!')
"""
    result = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
