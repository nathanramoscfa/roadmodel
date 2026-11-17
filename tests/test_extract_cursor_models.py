"""Cursor's and the Claude apps' access lists are synced, not hand-kept.

Claude Fable 5.2 launched on Cursor and in the Claude apps on 2026-11-09, but
the catalog listed only Fable 5.1 on both, so update/supersede.py's coverage
test kept 5.1 in the table. update/extract_cursor_models.py maps Cursor's
pricing tables onto catalog ids, the claude-web method gains the ids Claude
Code runs, and the catalog cron adds both (merge_catalog.py --sync-method).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import extract_cursor_models as cx  # noqa: E402
import merge_catalog  # noqa: E402

PAGE = """# Models & Pricing

### Cursor models

| Model                                       | Provider | Input |
| ------------------------------------------- | -------- | ----- |
| [Grok 4.7](https://x.ai/news/grok-4-7)      | Cursor   | $2    |
| [Grok 4.7 (Fast)](https://x.ai/news/grok-4-7) | Cursor | $4    |

### Model pricing

| Model                                                     | Provider  | Input |
| --------------------------------------------------------- | --------- | ----- |
| [Claude 4.7 Opus](https://www.anthropic.com/claude/opus)  | Anthropic | $5    |
| [Claude Opus 4.7 (fast mode)](https://www.anthropic.com/) | Anthropic | $30   |
| [Claude 4 Sonnet 1M](https://www.anthropic.com/)          | Anthropic | $6    |
| [Claude Fable 5.1](https://www.anthropic.com/claude/fable) | Anthropic | $10  |
| [Claude Fable 5.2](https://www.anthropic.com/claude/fable) | Anthropic | $8   |
| [GPT-5.1 Codex](https://platform.openai.com/)             | OpenAI    | $1.25 |
| [GPT-5.1 Codex Max](https://platform.openai.com/)         | OpenAI    | $1.25 |
| [Old Model 1](https://example.com/)                       | Other     | $1    |

See [the docs](https://cursor.com/docs) for more.
"""


def _model(mid: str, name: str, extra: str = "") -> str:
    return f'<model id="{mid}" name="{name}" input-price-per-1m="$1.00"{extra}/>'


SELECTOR = (
    "<model-options>\n"
    + "\n".join(
        [
            _model("grok-4.7", "Grok 4.7"),
            _model("opus-4.7", "Opus 4.7"),
            _model("claude-fable-5.1", "Claude Fable 5.1"),
            _model("claude-fable-5.2", "Claude Fable 5.2"),
            _model("gpt-5.1-codex", "GPT-5.1 Codex"),
            _model("gpt-5.1-codex-max", "GPT-5.1 Codex Max"),
            _model("old-model-1", "Old Model 1", ' retired-on="2026-10-01"'),
        ]
    )
    + "\n</model-options>\n<access-methods>\n"
    '<method id="cursor" name="Cursor" supports-models="claude-fable-5.1,opus-4.7"/>\n'
    "</access-methods>\n"
)


def test_cursor_rows_map_to_catalog_ids_in_page_order() -> None:
    assert cx.cursor_ids(PAGE, SELECTOR) == [
        "grok-4.7",
        "opus-4.7",  # "Claude 4.7 Opus": the words in another order
        "claude-fable-5.1",
        "claude-fable-5.2",
        "gpt-5.1-codex",
        "gpt-5.1-codex-max",
    ]


def test_mode_and_context_rows_name_no_separate_model() -> None:
    names = cx.listed_names(PAGE)
    assert "Grok 4.7 (Fast)" not in names and "Claude Opus 4.7 (fast mode)" not in names
    assert "Claude 4 Sonnet 1M" in names  # listed, but it matches no catalog model
    assert "the docs" not in names  # a link outside a table row


def test_a_retired_or_ambiguous_name_is_skipped() -> None:
    twin = SELECTOR.replace(
        "</model-options>", _model("opus-4-7-alias", "Claude Opus 4.7") + "\n</model-options>"
    )
    ids = cx.cursor_ids(PAGE, twin)
    assert "old-model-1" not in ids
    assert "opus-4.7" not in ids and "opus-4-7-alias" not in ids


def test_the_sync_adds_only_what_cursor_newly_lists() -> None:
    text, added = merge_catalog.ensure_supported(SELECTOR, "cursor", cx.cursor_ids(PAGE, SELECTOR))
    assert added == ["grok-4.7", "claude-fable-5.2", "gpt-5.1-codex", "gpt-5.1-codex-max"]
    assert (
        'supports-models="grok-4.7,claude-fable-5.2,gpt-5.1-codex,gpt-5.1-codex-max,claude-fable-5.1,opus-4.7"'
        in text
    )


def test_the_extractor_fails_open_and_reads_a_local_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page, selector = tmp_path / "page.md", tmp_path / "selector.txt"
    page.write_text(PAGE)
    selector.write_text(SELECTOR)
    assert cx.main(["--input", str(page), "--selector", str(selector)]) == 0
    assert capsys.readouterr().out.split() == cx.cursor_ids(PAGE, SELECTOR)
    assert cx.main(["--input", str(tmp_path / "missing.md"), "--selector", str(selector)]) == 0
    assert capsys.readouterr().out == ""


def test_the_source_is_cursors_raw_pricing_markdown() -> None:
    assert cx.pricing_url().endswith("/models-and-pricing.md")


def test_the_catalog_cron_syncs_cursor_and_claude_web() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert 'cursor_ids="$(python update/extract_cursor_models.py | paste -sd, - || true)"' in wf
    assert 'python update/merge_catalog.py --sync-method cursor --ids "${cursor_ids}"' in wf
    assert (
        'python update/merge_catalog.py --sync-method claude-web --ids "${claude_code_ids}"' in wf
    )
    # After the curation pass and the discovery lane, before the lifecycle rule.
    assert wf.index("--sync-method cursor") < wf.index("python update/supersede.py --write")
    assert wf.index("python update/dispose_discoveries.py --write") < wf.index(
        "--sync-method cursor"
    )


def test_the_live_selector_has_both_methods() -> None:
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    for method in ("cursor", "claude-web"):
        assert merge_catalog._method_supports_re(method).search(selector), method


def test_fetch_text_omits_markdown_accept_header_on_dot_md_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cursor.com/docs/models-and-pricing.md already ends in .md; sending
    Accept: text/markdown triggers Mintlify's .md rewrite (.md.md -> 404)."""
    import requests

    seen: dict[str, object] = {}

    class _Resp:
        text = PAGE

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, **kwargs: object) -> _Resp:
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        return _Resp()

    monkeypatch.setattr(requests, "get", _fake_get)
    assert cx.fetch_text(cx.pricing_url()) == PAGE
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert "Accept" not in headers
    assert headers.get("User-Agent") == cx.USER_AGENT
