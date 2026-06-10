#!/usr/bin/env python3
"""Local dogfood harness for the roadmodel CLI.

Drives the LOCAL `roadmodel` CLI (your editable build, so your working-tree
edits are exercised) over a curated battery of prompts, N times each, and
scores every result against the same rule-based bar the prod soak uses
(scripts/soak-recommend.ts): no task-execution leak, platform = funded surface,
no thinking-prose on no-thinking surfaces, and tier-stability across runs.

Unlike the soak this needs NO gate, NO Supabase auth, and NO prod traffic — it
calls the local CLI directly, which makes one provider API call per run. Default
engine is google + gemini-2.5-flash (~$0.002/call), so a full default run
(8 prompts x 2 = 16 calls) costs ~$0.03. Pass --model gemini-2.5-pro to dogfood
the signed-in frontier tier instead.

Usage (from the repo root):
    python3 scripts/dogfood_cli.py                  # default battery, 2x each
    python3 scripts/dogfood_cli.py --runs 3         # 3x for stricter determinism
    python3 scripts/dogfood_cli.py --model gemini-2.5-pro
    python3 scripts/dogfood_cli.py --limit 3        # just the first 3 prompts

The Google key is read from $GOOGLE_API_KEY, falling back to the macOS keychain
entry `roadmodel/GOOGLE_API_KEY` (the same one scripts/with-prod-secrets.sh uses).

Run logs accumulate (gitignored) under private/dogfood/:
  - cli-runs.jsonl   one JSON line per (prompt, run) with the full result
  - cli-log.md       a human-readable scorecard appended per invocation
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BIN = Path.home() / ".venvs" / "roadmodel" / "bin" / "roadmodel"
LOG_DIR = REPO_ROOT / "private" / "dogfood"
CATALOG_JSON = REPO_ROOT / "web" / "data" / "catalog.json"

# Rule constants mirrored from scripts/soak-recommend.ts so the local bar
# matches the prod soak. Keep these in sync if the soak's rules change.
LEAK = re.compile(
    r"##\s|\bDay\s*1\b|Morning\s*\(|Step\s*1:|```|\n\s*[-*]\s+\w"
    r"|Majestueuse|ravisse|\n\d+\.\s"
)
THINK_PROSE = re.compile(
    r"thinking is set to|THINKING is set|thinking level|reasoning is set",
    re.IGNORECASE,
)
NO_THINK_PLATFORMS = {"Cursor", "xAI API"}
CLAUDE_RE = re.compile(r"opus|sonnet|haiku|claude", re.IGNORECASE)
GPT_RE = re.compile(r"gpt-", re.IGNORECASE)


@dataclass(frozen=True)
class Probe:
    id: str
    prompt: str
    # What a correct pick looks like, for the human log (not auto-graded — the
    # rule checks below are; the expectation is a reading aid + #185/#189 watch).
    expect: str


# Curated battery: validated picks from docs/test-prompts.md plus two known
# stressors (cheap-speed under-weighting per #185; vacuous prompt determinism).
PROBES: list[Probe] = [
    Probe("opus-proof",
          "Rigorously prove the Cauchy-Schwarz inequality from first principles "
          "and explain the intuition behind each step.",
          "Opus / Claude Code / thinking On"),
    Probe("codex-terminal",
          "Refactor this 30-file Go microservice entirely from the terminal: "
          "extract packages, add unit tests, and fix the build, via the CLI.",
          "GPT Codex / Codex"),
    Probe("cheap-speed",
          "Classify 50,000 short tweets as positive or negative sentiment, as "
          "fast and cheaply as possible; accuracy is secondary.",
          "cheap/fast model (e.g. Nano) — watch for #185 over-escalation"),
    Probe("trivial",
          "What is the capital of France?",
          "cheapest model / thinking N/A"),
    Probe("long-context",
          "Search and cross-reference a 1.8-million-token legal contract corpus "
          "for internal contradictions, keeping cost low.",
          "long-context model (e.g. Grok)"),
    Probe("structured-tooluse",
          "Implement a well-specified multi-step ETL pipeline that makes "
          "reliable tool calls across 10 REST APIs, following the spec exactly.",
          "Sonnet / Cursor"),
    Probe("creative",
          "Write a short whimsical poem about a lighthouse that falls in love "
          "with a passing comet.",
          "top creative tier"),
    Probe("ambiguous-help",
          "help me with my code",
          "vacuous — watch tier stability across runs"),
]


@dataclass
class Result:
    probe_id: str
    run: int
    ok: bool
    model: str = ""
    platform: str = ""
    thinking: str = ""
    rationale: str = ""
    error: str = ""
    raw: dict = field(default_factory=dict)


def _resolve_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if key:
        return key
    try:
        out = subprocess.run(  # noqa: S603 — fixed binary, literal args
            ["/usr/bin/security", "find-generic-password", "-s", "roadmodel/GOOGLE_API_KEY", "-w"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _load_tier_map() -> dict[str, str]:
    """model display-name -> tier_cost bucket, from the web catalog if present.

    Used only for tier-stability scoring; degrades to exact-model comparison
    when the catalog is unavailable.
    """
    if not CATALOG_JSON.exists():
        return {}
    try:
        data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    models = data.get("models", data) if isinstance(data, dict) else data
    out: dict[str, str] = {}
    if isinstance(models, list):
        for m in models:
            if isinstance(m, dict) and "name" in m and "tier_cost" in m:
                out[str(m["name"])] = str(m["tier_cost"])
    return out


def _thinking_of(settings: dict) -> str:
    for key in ("thinking", "intelligence"):
        if key in settings:
            return str(settings[key])
    return "N/A"


def run_probe(bin_path: str, probe: Probe, run: int, provider: str, model: str,
              key: str) -> Result:
    cmd = [bin_path, "recommend", "--provider", provider, "--model", model,
           "--output", "json", probe.prompt]
    env = {**os.environ, "GOOGLE_API_KEY": key}
    try:
        proc = subprocess.run(  # noqa: S603 — roadmodel binary, curated prompts
            cmd, capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired:
        return Result(probe.id, run, ok=False, error="timeout")
    if proc.returncode != 0:
        return Result(probe.id, run, ok=False,
                      error=(proc.stderr or proc.stdout).strip()[:200])
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return Result(probe.id, run, ok=False, error="non-JSON output")
    settings = payload.get("settings") or {}
    return Result(
        probe.id, run, ok=True,
        model=str(payload.get("model") or ""),
        platform=str(payload.get("platform") or ""),
        thinking=_thinking_of(settings),
        rationale=str(payload.get("rationale") or ""),
        raw=payload,
    )


def score(results: list[Result], tier_map: dict[str, str]) -> list[tuple[str, bool, str]]:
    ok = [r for r in results if r.ok]
    checks: list[tuple[str, bool, str]] = []  # (label, pass, detail)

    non_ok = [r for r in results if not r.ok]
    checks.append(("B0 all-ok", len(non_ok) == 0,
                   ", ".join(f"{r.probe_id}:{r.error}" for r in non_ok) or "all returned"))

    leaks = [r for r in ok if LEAK.search(r.rationale)]
    checks.append(("B1 no-task-leak", len(leaks) == 0,
                   ", ".join(r.probe_id for r in leaks) or "clean"))

    plat_err = [r for r in ok
                if (CLAUDE_RE.search(r.model) and r.platform == "Cursor")
                or (GPT_RE.search(r.model) and r.platform == "OpenAI API")]
    checks.append(("B3 platform-funded (watch)", True,
                   ", ".join(f"{r.probe_id}:{r.model}/{r.platform}" for r in plat_err) or "clean"))

    prose = [r for r in ok if r.platform in NO_THINK_PLATFORMS and THINK_PROSE.search(r.rationale)]
    checks.append(("#188 thinking-prose (watch)", True,
                   f"{len(prose)} slips" + (": " + ", ".join(r.probe_id for r in prose) if prose else "")))

    # Determinism: per probe, did the quality TIER stay stable across runs?
    by_probe: dict[str, list[Result]] = defaultdict(list)
    for r in ok:
        by_probe[r.probe_id].append(r)

    def tier_of(model: str) -> str:
        return tier_map.get(model, model)  # fall back to exact model

    tier_flaky = [pid for pid, rs in by_probe.items()
                  if len(rs) >= 2 and len({tier_of(r.model) for r in rs}) > 1]
    model_flaky = [pid for pid, rs in by_probe.items()
                   if len(rs) >= 2 and len({(r.model, r.platform) for r in rs}) > 1]
    checks.append(("B7 tier-stable", len(tier_flaky) == 0,
                   ", ".join(tier_flaky) or "tier-stable"))
    checks.append(("B7 exact-model (watch)", True,
                   ", ".join(model_flaky) or "stable"))
    return checks


def append_logs(results: list[Result], checks: list[tuple[str, bool, str]],
                provider: str, model: str, stamp: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "cli-runs.jsonl").open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({
                "stamp": stamp, "provider": provider, "engine": model,
                "probe": r.probe_id, "run": r.run, "ok": r.ok,
                "model": r.model, "platform": r.platform, "thinking": r.thinking,
                "error": r.error,
            }) + "\n")
    blocking = [c for c in checks if "(watch)" not in c[0]]
    failed = [c for c in blocking if not c[1]]
    lines = [f"\n## {stamp} — {provider}/{model}",
             f"RESULT: {'PASS' if not failed else 'FAIL'} "
             f"({len(blocking) - len(failed)}/{len(blocking)} blocking)"]
    for label, ok_, detail in checks:
        tag = "WATCH" if "(watch)" in label else ("PASS " if ok_ else "FAIL ")
        lines.append(f"- [{tag}] {label}: {detail}")
    (LOG_DIR / "cli-log.md").open("a", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local dogfood harness for the roadmodel CLI.")
    parser.add_argument("--runs", type=int, default=2, help="Runs per prompt (determinism).")
    parser.add_argument("--provider", default="google")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N prompts (0 = all).")
    parser.add_argument("--bin", default=str(DEFAULT_BIN), help="Path to the roadmodel binary.")
    parser.add_argument("--stamp", default="", help="Run label for the log (e.g. a date).")
    args = parser.parse_args()

    bin_path = args.bin if Path(args.bin).exists() else "roadmodel"
    key = _resolve_key()
    if args.provider == "google" and not key:
        print("No GOOGLE_API_KEY in env or keychain (roadmodel/GOOGLE_API_KEY).", file=sys.stderr)
        return 2

    probes = PROBES[: args.limit] if args.limit > 0 else PROBES
    total = len(probes) * args.runs
    print(f"Dogfooding {len(probes)} prompts x {args.runs} = {total} calls "
          f"via {args.provider}/{args.model} (~${total * 0.002:.2f} on flash)\n")

    results: list[Result] = []
    for probe in probes:
        picks = []
        for run in range(1, args.runs + 1):
            res = run_probe(bin_path, probe, run, args.provider, args.model, key)
            results.append(res)
            picks.append(f"{res.model}/{res.platform}" if res.ok else f"ERR:{res.error[:40]}")
        print(f"  {probe.id:<18} {' | '.join(picks)}")
        print(f"  {'':<18} expect: {probe.expect}")

    tier_map = _load_tier_map()
    checks = score(results, tier_map)
    blocking = [c for c in checks if "(watch)" not in c[0]]
    failed = [c for c in blocking if not c[1]]

    print("\n=== CLI DOGFOOD SCORECARD ===")
    for label, ok_, detail in checks:
        tag = "WATCH" if "(watch)" in label else ("PASS " if ok_ else "FAIL ")
        print(f"  [{tag}] {label}: {detail}")
    print(f"\nRESULT: {'PASS' if not failed else 'FAIL'} "
          f"({len(blocking) - len(failed)}/{len(blocking)} blocking checks)")

    stamp = args.stamp or "run"
    append_logs(results, checks, args.provider, args.model, stamp)
    print(f"Logged to {LOG_DIR}/cli-log.md and cli-runs.jsonl")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
