"""Guards on the Groq lane's drift check and its discovery flag.

Two things had gone wrong at once.

**The drift check was pointed at a page with no models on it.** `groq.com/pricing`
went fully client-rendered: it returns a ~55 KB shell with zero model names,
zero prices and no JSON island. Name-presence matched nothing, so the check
reported BOTH committed models as drifted on every run — and, worse, could no
longer distinguish that from a real delisting. It now reads
`console.groq.com/docs/models`, which is server-rendered and carries the ids.

**`unexpected_slugs` was a hardcoded `[]`** (issue #652), so the lane could not
surface a model Groq prices that the catalog does not carry. It now reports
them, scoped to the gpt-oss family — the only family roadmodel pins Groq as the
host for.

Discovery is only useful if it is quiet when it should be. Groq's docs page
gives each model its own `-limits` and `-price` section anchors, all sharing
the real id's `openai/` prefix, so a loose pattern flags nine slugs where three
exist. These tests pin the signal and the silence together.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "update" / "extract_groq_catalog.py"
SNAPSHOT = REPO_ROOT / "update" / "catalog-groq.json"

# The shapes Groq's docs page actually uses: the model id, and the two section
# anchors derived from it that a loose pattern mistakes for models.
PAGE = """
  <a href="#openai/gpt-oss-120b">openai/gpt-oss-120b</a>
  <a href="#openai/gpt-oss-120b-limits">Limits</a>
  <a href="#openai/gpt-oss-120b-price">Pricing</a>
  <a href="#openai/gpt-oss-20b">openai/gpt-oss-20b</a>
  <a href="#openai/gpt-oss-20b-limits">Limits</a>
  <h2>gpt-oss models on Groq</h2>
"""


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extract_groq_catalog", SCRIPT)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_committed_models_are_found_on_the_docs_page(mod: ModuleType) -> None:
    """The false-positive drift: both committed ids appear, so nothing drifts."""
    assert mod.names_missing_from_page(PAGE) == []


def test_a_shell_page_with_no_models_still_reads_as_drift(mod: ModuleType) -> None:
    """What groq.com/pricing now returns. Reporting drift here is correct — the
    bug was pointing the check at this page, not how it reads it."""
    assert set(mod.names_missing_from_page("<html><body>fast inference</body></html>")) == {
        "gpt-oss-120b",
        "gpt-oss-20b",
    }


def test_section_anchors_are_not_mistaken_for_models(mod: ModuleType) -> None:
    """`-limits` and `-price` carry the same `openai/` prefix as the real id.
    A gpt-oss id always ends in its parameter count, which is the difference."""
    assert mod.unexpected_on_page(PAGE) == []


def test_a_new_family_member_is_surfaced(mod: ModuleType) -> None:
    page = PAGE + '<a href="#openai/gpt-oss-480b">openai/gpt-oss-480b</a>'
    assert mod.unexpected_on_page(page) == ["gpt-oss-480b"]


def test_a_declined_model_stays_quiet(mod: ModuleType) -> None:
    """gpt-oss-safeguard-20b is on the live page and deliberately not
    catalogued. A slug that is neither promoted nor declined re-flags every
    run and trains the reader to ignore the flag."""
    page = PAGE + '<a href="#openai/gpt-oss-safeguard-20b">openai/gpt-oss-safeguard-20b</a>'
    assert "gpt-oss-safeguard-20b" in mod.DECLINED
    assert mod.DECLINED["gpt-oss-safeguard-20b"].strip(), "a decline must state why"
    assert mod.unexpected_on_page(page) == []


def test_discovery_reaches_the_snapshot(mod: ModuleType) -> None:
    """unexpected_slugs was a hardcoded []; it must now carry what was found."""
    assert mod.build_snapshot(["gpt-oss-480b"])["unexpected_slugs"] == ["gpt-oss-480b"]
    assert mod.build_snapshot()["unexpected_slugs"] == []


def test_the_committed_snapshot_points_at_the_readable_page(mod: ModuleType) -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["source_url"] == mod.DOCS_URL == "https://console.groq.com/docs/models"
    assert mod.PRICE_URL == "https://groq.com/pricing", "prices are still read by eye there"
    assert "unexpected_slugs" in snapshot
