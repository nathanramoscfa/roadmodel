#!/usr/bin/env python3
"""Refresh ``docs/model-selector.txt`` and ``docs/model-tier-cost-scale.md``
for roadmodel from upstream pricing and benchmark sources using Opus 4.7."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

import requests
from anthropic import Anthropic
from anthropic.types import TextBlock
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
UPDATE_DIR = REPO_ROOT / "update"

SELECTOR_PATH = DOCS_DIR / "model-selector.txt"
COST_SCALE_PATH = DOCS_DIR / "model-tier-cost-scale.md"

MODEL_ID = "claude-opus-4-7"
MAX_TOKENS = 64000
WEB_SEARCH_MAX_USES = 30
USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30
DEFAULT_MAX_BYTES = 150_000
HTML_SNIFF_BYTES = 1024


def fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        },
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def fetch_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def looks_like_html(content: str) -> bool:
    head = content[:HTML_SNIFF_BYTES].lower()
    return "<!doctype html" in head or "<html" in head


def strip_html(content: str) -> str:
    """Reduce HTML to visible text plus inline-script contents.

    SPA leaderboards frequently inline benchmark data as JSON inside
    <script> tags (e.g. SWE-bench's per-instance results). BeautifulSoup's
    get_text() excludes script bodies, so we extract data-bearing scripts
    separately and append them, letting downstream truncation cap the size.
    Style/link/meta/noscript/svg carry no data and are dropped.
    """
    soup = BeautifulSoup(content, "html.parser")
    data_scripts: list[str] = []
    for s in soup.find_all("script"):
        body = s.string or s.get_text() or ""
        if len(body) > 500 and ("{" in body or "[" in body):
            data_scripts.append(body)
    for tag in soup(["style", "noscript", "svg", "link", "meta", "script"]):
        tag.decompose()
    visible = soup.get_text(separator=" ", strip=True)
    combined = visible + " " + " ".join(data_scripts)
    return re.sub(r"\s+", " ", combined).strip()


def normalize_content(content: str, max_bytes: int) -> str:
    if looks_like_html(content):
        content = strip_html(content)
    if len(content) > max_bytes:
        content = content[:max_bytes]
    return content


def validate_content(content: str, rules: dict[str, Any] | None) -> str | None:
    """Return None if content passes the rules, else a short failure reason.

    Guards against silently feeding empty SPA shells to Opus. A source whose
    fetched body is too small or missing expected markers is treated as a
    fetch failure rather than valid input.
    """
    if not rules:
        return None
    min_bytes = rules.get("min_bytes")
    if min_bytes is not None and len(content) < min_bytes:
        return f"content too small ({len(content)} bytes < {min_bytes})"
    must_contain = rules.get("must_contain_all") or []
    haystack = content.lower()
    missing = [m for m in must_contain if m.lower() not in haystack]
    if missing:
        return f"missing expected markers: {missing}"
    return None


_CURSOR_PROVIDERS_PATTERN = r"(?:Anthropic|OpenAI|Google|xAI|Cursor|Moonshot|Z\s*AI|DeepSeek)"


def _name_tokens(s: str | None) -> set[str]:
    """Tokenize a model display name for fuzzy cross-source matching.

    Lowercase, normalize digit-dash-digit (`claude-opus-4-7`) to
    digit-dot-digit (`claude-opus-4.7`) so versioned variants share
    tokens regardless of formatting, then extract dotted-number runs,
    bare integers, and alphabetic runs. Examples:

      "Claude 4.7 Opus"          → {claude, 4.7, opus}
      "claude-opus-4-7"          → {claude, opus, 4.7}
      "GPT-5.5 (xhigh)"          → {gpt, 5.5, xhigh}
      "Kimi K2.5 (Reasoning)"    → {kimi, k, 2.5, reasoning}
    """
    if not s:
        return set()
    s = re.sub(r"(\d)-(\d)", r"\1.\2", s.lower())
    return set(re.findall(r"\d+(?:\.\d+)+|[a-z]+|\d+", s))


def _cursor_model_token_sets() -> list[set[str]]:
    """Extract a token set per Cursor pricing-table row.

    Anchors on the provider column (column 2) so we capture both
    linked rows (`| [Claude 4.7 Opus](...) | Anthropic | ...`) and
    bare-name rows (`| Kimi K2.5 | Moonshot | ...`). The Cursor URL
    is read from sources.json so this stays in sync with the
    canonical source list.
    """
    cursor_url = json.loads((UPDATE_DIR / "sources.json").read_text())["pricing"]["url"]
    md = fetch(cursor_url)
    rows = re.findall(
        rf"^\|\s*([^|]+?)\s*\|\s*{_CURSOR_PROVIDERS_PATTERN}\s*\|",
        md,
        re.MULTILINE,
    )
    names = [re.sub(r"^\[([^\]]+)\]\([^)]*\)$", r"\1", n) for n in rows]
    return [_name_tokens(n) for n in names if n]


def _transform_aa_api(url: str) -> str:
    """Fetch the Artificial Analysis Insights API model dataset.

    Replaces the artificialanalysis.ai SPA scrape AND the lastexam.ai
    HLE scrape — AA's `/api/v2/data/llms/models` response includes the
    HLE column alongside the Intelligence Index, AA-Omniscience, GPQA,
    AIME, terminalbench_hard, livecodebench, tau2, ifbench, and other
    evaluations the prompt cites.

    Requires `AA_API_KEY` in the environment. The free tier (1000
    req/day) is plenty for a weekly cron. Per AA's TOS, attribution to
    https://artificialanalysis.ai/ is required wherever this data is
    surfaced — model-selector.txt's <benchmark-sources> already names
    Artificial Analysis Intelligence Index as the source for those
    claims.

    The raw API response carries 500+ models, most of which are
    open-weight or legacy entries that aren't in Cursor's pricing
    catalog (and therefore can't appear in <model-options>). We
    intersect the AA list with Cursor's catalog by token-set match
    so the prompt receives only models that could plausibly be
    referenced in the docs. If the Cursor fetch fails for any
    reason, we fall through to the unfiltered payload so the AA
    fetch itself doesn't degrade — better to ship 300 KB than to
    skip AA entirely and lose HLE / Intelligence Index re-checks.
    """
    api_key = os.environ.get("AA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "AA_API_KEY is not set. Sign up at "
            "https://artificialanalysis.ai/login and add the key to "
            "this environment (and to GitHub Actions secrets for the "
            "weekly cron)."
        )
    response = requests.get(
        url,
        headers={
            "x-api-key": api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        timeout=FETCH_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    models = payload.get("data") or []

    try:
        cursor_token_sets = _cursor_model_token_sets()
    except Exception:
        cursor_token_sets = []

    if cursor_token_sets:
        kept = [
            m
            for m in models
            if any(
                cs <= (_name_tokens(m.get("name")) | _name_tokens(m.get("slug")))
                for cs in cursor_token_sets
            )
        ]
        # Sanity guard: if the filter dropped everything (e.g. Cursor
        # markdown shape changed), fall back to the full list rather
        # than silently sending an empty payload to Opus.
        if kept:
            models = kept

    compact = [
        {
            "id": m.get("id"),
            "name": m.get("name"),
            "slug": m.get("slug"),
            "creator": (m.get("model_creator") or {}).get("name"),
            "evaluations": m.get("evaluations"),
            "median_output_tokens_per_second": m.get("median_output_tokens_per_second"),
            "median_time_to_first_token_seconds": m.get("median_time_to_first_token_seconds"),
        }
        for m in models
    ]
    return json.dumps(compact, indent=None)


def _transform_tau2_bench(url: str) -> str:
    """Aggregate τ²-bench submissions from the sierra-research repo.

    The configured `url` is the manifest.json that lists submission
    folders. For each entry we fetch the matching submission.json and
    keep model identifiers, results-by-domain, and methodology metadata
    so the prompt can verify claims like "τ²-bench airline pass^1 84.0".
    `voice_submissions` and `legacy_submissions` are kept too so claims
    about prior models stay verifiable; trim by dropping older runs if
    payload growth becomes a concern.
    """
    base, _, _ = url.rpartition("/manifest.json")
    raw = fetch(url)
    manifest = json.loads(raw)
    out: dict[str, list[dict[str, Any]]] = {}
    for bucket, ids in manifest.items():
        bucket_results: list[dict[str, Any]] = []
        for sid in ids or []:
            sub_url = f"{base}/{sid}/submission.json"
            try:
                sub_raw = fetch(sub_url)
            except Exception:  # noqa: S112 — best-effort sub-source; a failed fetch is intentionally skipped
                continue
            sub = json.loads(sub_raw)
            bucket_results.append(
                {
                    "id": sid,
                    "model_name": sub.get("model_name"),
                    "model_organization": sub.get("model_organization"),
                    "submission_date": sub.get("submission_date"),
                    "reasoning_effort": sub.get("reasoning_effort"),
                    "results": sub.get("results"),
                }
            )
        out[bucket] = bucket_results
    return json.dumps(out, indent=None)


def _transform_livecodebench(url: str) -> str:
    """Aggregate LiveCodeBench's per-question performance JSON.

    The upstream `performances_generation.json` is ~7 MB of per-
    (model, question) rows; the public livecodebench.github.io
    leaderboard computes per-model pass@1 averages client-side. We
    replicate that aggregation here and emit one row per model with
    overall and by-difficulty scores plus question count, so the
    prompt receives a compact leaderboard rather than raw rows.
    """
    raw = fetch(url)
    data = json.loads(raw)
    perfs = data.get("performances") or []
    models = data.get("models") or []

    by_model: dict[str, dict[str, list[float]]] = {}
    for p in perfs:
        m = p.get("model")
        if not m:
            continue
        bucket = by_model.setdefault(m, {"all": [], "easy": [], "medium": [], "hard": []})
        score = p.get("pass@1")
        if score is None:
            continue
        bucket["all"].append(score)
        diff = p.get("difficulty")
        if diff in bucket:
            bucket[diff].append(score)

    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 1) if xs else None

    out: list[dict[str, Any]] = []
    for info in models:
        repr_name = info.get("model_repr")
        scores = by_model.get(repr_name)
        if not scores or not scores["all"]:
            continue
        out.append(
            {
                "model": repr_name,
                "model_name": info.get("model_name"),
                "release_date": info.get("release_date"),
                "pass1_overall": avg(scores["all"]),
                "pass1_easy": avg(scores["easy"]),
                "pass1_medium": avg(scores["medium"]),
                "pass1_hard": avg(scores["hard"]),
                "questions": len(scores["all"]),
            }
        )
    out.sort(key=lambda x: x["pass1_overall"] or 0, reverse=True)
    return json.dumps(out, indent=None)


def _transform_swebench(url: str) -> str:
    """Filter SWE-bench leaderboards.json to Verified + Multilingual splits.

    The full file is ~7 MB (180+ submissions × ~17 fields each, including
    full trajectory URLs and per-instance logs). We keep only the splits
    actually cited in headline-benchmarks and trim each result to the
    fields the prompt cares about — model name, score, date, tags.
    """
    raw = fetch(url)
    data = json.loads(raw)
    keep_splits = {"Verified", "Multilingual"}
    out: dict[str, list[dict[str, Any]]] = {"leaderboards": []}
    for lb in data.get("leaderboards", []):
        if lb.get("name") not in keep_splits:
            continue
        results = [
            {
                "name": r.get("name"),
                "resolved": r.get("resolved"),
                "date": r.get("date"),
                "tags": r.get("tags"),
            }
            for r in lb.get("results", [])
        ]
        out["leaderboards"].append({"name": lb["name"], "results": results})
    return json.dumps(out, indent=None)


def _transform_lmarena(url: str) -> str:
    """Read LMArena parquet snapshots and return a compact JSON view.

    The configured `url` points at the `text` subset; we additionally
    pull `webdev` and `search` from sibling paths because the existing
    `headline-benchmarks` strings cite all three (e.g. "LMArena Text Elo
    1503", "LMArena WebDev Elo 1570", "LMArena Search Elo 1205"). For
    each (subset, category) pair we keep the latest publish date and
    the top N models by rank — that covers the entire frontier cited
    in prompts while staying well under the prompt budget. pyarrow is
    lazy-imported so the rest of the pipeline doesn't pay the import
    cost when LMArena isn't being fetched.
    """
    import io

    import pyarrow.parquet as pq

    # (subset, category) → top-N to keep. Categories chosen to match
    # claims actually cited in headline-benchmarks; expand if a new
    # claim type appears (e.g. "LMArena Vision Elo X").
    keep: dict[tuple[str, str], int] = {
        ("text", "overall"): 60,
        ("text", "coding"): 40,
        ("webdev", "overall"): 40,
        ("search", "overall"): 30,
    }

    base, _, _ = url.rpartition("/text/")
    subset_urls = {
        "text": url,
        "webdev": f"{base}/webdev/latest-00000-of-00001.parquet",
        "search": f"{base}/search/latest-00000-of-00001.parquet",
    }

    snapshot: dict[str, str] = {}
    combined: list[dict[str, Any]] = []
    for subset_label, subset_url in subset_urls.items():
        body = fetch_bytes(subset_url)
        # pyarrow ships no type stubs, so read_table is seen as untyped.
        table = pq.read_table(io.BytesIO(body))  # type: ignore[no-untyped-call]
        rows = table.to_pylist()
        if not rows:
            continue
        latest_date = max(r["leaderboard_publish_date"] for r in rows)
        snapshot[subset_label] = latest_date
        for r in rows:
            if r["leaderboard_publish_date"] != latest_date:
                continue
            limit = keep.get((subset_label, r["category"]))
            if limit is None or int(r["rank"]) > limit:
                continue
            combined.append(
                {
                    "subset": subset_label,
                    "category": r["category"],
                    "rank": int(r["rank"]),
                    "model": r["model_name"],
                    "rating": round(r["rating"], 1),
                    "votes": int(r["vote_count"]),
                }
            )
    combined.sort(key=lambda x: (x["subset"], x["category"], x["rank"]))
    return json.dumps(
        {"snapshot_dates": snapshot, "leaderboard": combined},
        indent=None,
    )


TRANSFORMS = {
    "aa_api": _transform_aa_api,
    "lmarena_parquet": _transform_lmarena,
    "livecodebench_aggregate": _transform_livecodebench,
    "swebench_leaderboards": _transform_swebench,
    "tau2_bench_manifest": _transform_tau2_bench,
}


def gather_sources() -> tuple[list[dict[str, str]], list[str]]:
    sources_config = json.loads((UPDATE_DIR / "sources.json").read_text())
    fetched: list[dict[str, str]] = []
    errors: list[str] = []

    def try_fetch(kind: str, src: dict[str, Any]) -> None:
        transform_name = src.get("transform")
        try:
            if transform_name:
                content = TRANSFORMS[transform_name](src["url"])
            else:
                raw = fetch(src["url"])
                max_bytes = src.get("max_bytes", DEFAULT_MAX_BYTES)
                content = normalize_content(raw, max_bytes)
        except Exception as exc:
            errors.append(f"{src['url']}: fetch failed: {exc}")
            return
        reason = validate_content(content, src.get("validate"))
        if reason is not None:
            errors.append(f"{src['url']}: validation failed: {reason}")
            return
        fetched.append(
            {
                "type": kind,
                "name": src["name"],
                "url": src["url"],
                "content": content,
            }
        )

    try_fetch("pricing", sources_config["pricing"])
    for src in sources_config["benchmarks"]:
        try_fetch("benchmark", src)

    return fetched, errors


def build_user_message(
    selector_text: str,
    cost_scale_text: str,
    fetched: list[dict[str, str]],
    fetch_errors: list[str],
    target: str | None = None,
) -> str:
    """Assemble the Opus user message.

    ``target`` selects which file the model must emit (the refresh is split into
    two single-file Opus calls so neither response approaches the output-token
    ceiling — emitting two full regenerated files in one call overflows when a
    new model family is added). ``None`` keeps the legacy two-file contract.
    For ``"selector"``, ``cost_scale_text`` is the ALREADY-updated cost scale
    from the first call, so ``<model-options>`` is synced to fresh tiers.
    """
    blocks: list[str] = [
        f'<current_file path="docs/model-selector.txt">\n{selector_text}\n</current_file>',
        f'<current_file path="docs/model-tier-cost-scale.md">\n{cost_scale_text}\n</current_file>',
    ]
    for src in fetched:
        blocks.append(
            f'<source type="{src["type"]}" name="{src["name"]}" url="{src["url"]}">\n'
            f"{src['content']}\n"
            f"</source>"
        )
    if fetch_errors:
        blocks.append("<fetch_errors>\n" + "\n".join(fetch_errors) + "\n</fetch_errors>")
    if target is not None:
        blocks.append(f"<emit_target>{target}</emit_target>")
    return "\n\n".join(blocks)


def call_opus(system_prompt: str, user_message: str, api_key: str) -> str:
    """Return assistant text from Opus via streaming (long-request policy).

    The web_search server-side tool is enabled so Opus can adaptively
    look up subscription pricing for the "Subscription Tiers and Access
    Methods" section of model-tier-cost-scale.md. The tool runs entirely
    server-side; the SDK returns interleaved text + server_tool_use +
    web_search_tool_result blocks. We concatenate only the text blocks
    — the final JSON response Opus emits per `# Output format` in
    prompt.md.
    """
    client = Anthropic(api_key=api_key)
    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    user_blocks = [{"role": "user", "content": user_message}]
    tools = [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        }
    ]
    # The SDK accepts these plain dict shapes at runtime; its param types
    # (TextBlockParam / MessageParam / ToolParam) are stricter than what we pass.
    with client.messages.stream(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        system=system_blocks,  # type: ignore[arg-type]
        messages=user_blocks,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
    ) as stream:
        response = stream.get_final_message()
    return "".join(block.text for block in response.content if isinstance(block, TextBlock))


_FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.DOTALL)


def parse_result(raw: str, primary_key: str = "roadmodel_txt") -> dict[str, Any]:
    """Parse the model's JSON response, tolerating prose preamble/epilogue.

    The system prompt asks for a single JSON object with no surrounding
    text, but the model occasionally emits reasoning, sample templates,
    fenced placeholders, AND the real JSON in a separate fence. Strategy:

    1. Strict parse first (clean output is the happy path).
    2. If a markdown fence wraps the entire response (starts AND ends
       with ```), strip the outermost fence and retry.
    3. Scan all embedded fenced code blocks; if any of them parses as
       JSON, return the one with the longest ``primary_key`` value
       (``roadmodel_txt`` by default, ``model_tier_cost_scale_md`` for the
       cost-scale pass). This discriminates the real payload (a full file)
       from sample/template fences (placeholder strings like "...full
       file...").
    4. Strip all fenced blocks and try parsing what remains, then fall
       back to first `{` to last `}`.

    Step 3 fixes the multi-fence failure mode (TODO #5 plus the
    sibling case where the real JSON is itself fenced, observed in
    cron runs 25820190303 and 25820779529): Opus sometimes emits a
    sample fence as preamble AND wraps the real JSON in its own
    fence. The legacy code stripped both, leaving nothing parseable;
    the previous fix stripped both regardless of content.
    """
    text = raw.strip()

    try:
        return cast("dict[str, Any]", json.loads(text))
    except json.JSONDecodeError:
        pass

    if text.startswith("```") and text.endswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            inner = text[first_nl + 1 : -3].rstrip()
            try:
                return cast("dict[str, Any]", json.loads(inner))
            except json.JSONDecodeError:
                pass

    candidates: list[tuple[int, dict[str, Any]]] = []

    def _try_add(candidate_text: str) -> None:
        try:
            parsed = json.loads(candidate_text.strip())
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            payload = parsed.get(primary_key, "")
            length = len(payload) if isinstance(payload, str) else 0
            candidates.append((length, parsed))

    for block in _FENCED_BLOCK_RE.findall(text):
        _try_add(block)

    text_no_fences = _FENCED_BLOCK_RE.sub("", text).strip()
    if text_no_fences:
        _try_add(text_no_fences)
        start = text_no_fences.find("{")
        end = text_no_fences.rfind("}")
        if 0 <= start < end:
            _try_add(text_no_fences[start : end + 1])

    if candidates:
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise json.JSONDecodeError("could not extract JSON object from model output", text, 0)
    return cast("dict[str, Any]", json.loads(text[start : end + 1]))


def load_fixture(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a pre-fetched-sources fixture, bypassing network I/O.

    Shape: {"fetched": [{type, name, url, content}, ...],
            "fetch_errors": ["...", ...]}.
    Used by --fixture to exercise the lifecycle rules in update/prompt.md
    against synthetic Cursor pricing payloads (e.g. "what happens when
    GPT-5.6 appears at $40/M output?") without waiting for upstream
    changes.
    """
    payload = json.loads(path.read_text())
    fetched = payload.get("fetched", [])
    fetch_errors = payload.get("fetch_errors", [])
    return fetched, fetch_errors


def write_dry_run_report(
    selector_before: str,
    selector_after: str,
    cost_scale_before: str,
    cost_scale_after: str,
    summary: str,
    warnings: list[str],
) -> None:
    print(f"=== Summary ===\n{summary}\n")
    if warnings:
        print("=== Warnings ===")
        for w in warnings:
            print(f"  - {w}")
        print()
    print("=== Diff: docs/model-selector.txt ===")
    sys.stdout.writelines(
        difflib.unified_diff(
            selector_before.splitlines(keepends=True),
            selector_after.splitlines(keepends=True),
            fromfile="current/docs/model-selector.txt",
            tofile="proposed/docs/model-selector.txt",
        )
    )
    print("\n=== Diff: docs/model-tier-cost-scale.md ===")
    sys.stdout.writelines(
        difflib.unified_diff(
            cost_scale_before.splitlines(keepends=True),
            cost_scale_after.splitlines(keepends=True),
            fromfile="current/model-tier-cost-scale.md",
            tofile="proposed/model-tier-cost-scale.md",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't write to disk or update .last-summary.txt / "
            ".last-warnings.txt. Print the proposed diff against the "
            "current docs plus the summary and warnings. Useful for "
            "previewing what the next refresh would change."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help=(
            "Path to a JSON file with pre-fetched source content "
            "(skips network fetching). Shape: "
            '{"fetched": [{"type": ..., "name": ..., "url": ..., '
            '"content": ...}, ...], "fetch_errors": [...]}. Useful for '
            "exercising Model lifecycle rules with synthetic pricing "
            "inputs (e.g. test that a hypothetical costlier successor "
            "does not displace the predecessor)."
        ),
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("ANTHROPIC_API_KEY is not set\n")
        return 1

    system_prompt = (UPDATE_DIR / "prompt.md").read_text()
    selector_text = SELECTOR_PATH.read_text()
    cost_scale_text = COST_SCALE_PATH.read_text()

    if args.fixture is not None:
        fetched, fetch_errors = load_fixture(args.fixture)
    else:
        fetched, fetch_errors = gather_sources()
    if not fetched:
        sys.stderr.write(
            "All source fetches failed; refusing to call Opus.\n" + "\n".join(fetch_errors) + "\n"
        )
        return 3

    # Two single-file Opus calls instead of one two-file call. Emitting both
    # full regenerated files in a single response overflows the output-token
    # ceiling when a new model FAMILY is added (the from-scratch tier profile
    # tips it over → truncated, invalid JSON, the refresh fails). The cost-scale
    # is the upstream artifact and the selector's <model-options> is synced FROM
    # it, so run cost-scale first and feed its output into the selector call.
    # Sources are partitioned by what each file needs (pricing → cost-scale;
    # benchmarks → selector), so total input stays ~constant rather than doubling.
    pricing_sources = [s for s in fetched if s["type"] == "pricing"]
    benchmark_sources = [s for s in fetched if s["type"] == "benchmark"]

    def run_call(
        target: str, cost_scale_in: str, srcs: list[dict[str, str]], key: str
    ) -> dict[str, Any] | None:
        msg = build_user_message(selector_text, cost_scale_in, srcs, fetch_errors, target=target)
        raw = call_opus(system_prompt, msg, api_key)
        try:
            return parse_result(raw, primary_key=key)
        except json.JSONDecodeError:
            sys.stderr.write(
                f"Model did not return valid JSON for target={target!r}. Raw output:\n"
            )
            sys.stderr.write(raw + "\n")
            return None

    # Pass: cost-scale (pricing sources only).
    result_cs = run_call("cost_scale", cost_scale_text, pricing_sources, "model_tier_cost_scale_md")
    if result_cs is None:
        return 2
    new_cost_scale_obj = result_cs.get("model_tier_cost_scale_md")
    if not isinstance(new_cost_scale_obj, str) or not new_cost_scale_obj.strip():
        sys.stderr.write("cost_scale pass did not return a model_tier_cost_scale_md string\n")
        return 2
    new_cost_scale: str = new_cost_scale_obj

    # Pass: selector (benchmark sources + the freshly-updated cost-scale).
    result_sel = run_call("selector", new_cost_scale, benchmark_sources, "roadmodel_txt")
    if result_sel is None:
        return 2
    new_selector_obj = result_sel.get("roadmodel_txt")
    if not isinstance(new_selector_obj, str) or not new_selector_obj.strip():
        sys.stderr.write("selector pass did not return a roadmodel_txt string\n")
        return 2
    new_selector: str = new_selector_obj

    # Merge summaries (drop bare "No changes detected.") and warnings.
    summary_parts = [
        s.strip()
        for s in (result_cs.get("summary"), result_sel.get("summary"))
        if isinstance(s, str) and s.strip() and s.strip() != "No changes detected."
    ]
    summary = " | ".join(summary_parts) if summary_parts else "No changes detected."
    warnings: list[str] = []
    for r in (result_cs, result_sel):
        warnings.extend(w for w in (r.get("warnings") or []) if isinstance(w, str))
    if fetch_errors:
        warnings.extend(f"Fetch error: {err}" for err in fetch_errors)

    if args.dry_run:
        write_dry_run_report(
            selector_text,
            new_selector,
            cost_scale_text,
            new_cost_scale,
            summary,
            warnings,
        )
        return 0

    SELECTOR_PATH.write_text(new_selector)
    COST_SCALE_PATH.write_text(new_cost_scale)

    # Regenerate the human-readable mirror from the updated .txt so the two
    # files commit together. render_md.py imports without side effects.
    from render_md import SELECTOR_MD, render

    SELECTOR_MD.write_text(render(SELECTOR_PATH.read_text()))

    (UPDATE_DIR / ".last-summary.txt").write_text(summary)
    if warnings:
        (UPDATE_DIR / ".last-warnings.txt").write_text("\n".join(warnings))

    print(summary)
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
