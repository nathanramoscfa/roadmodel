#!/usr/bin/env python3
"""Live probe: does a REAL engine honour the v2 output contract?

The deterministic half of this verification lives in
``tests/test_user_stack_contract.py`` — it pins the prompt the engine receives
and the parse/display layer's behaviour. What CI cannot prove is the engine's
own judgement: whether, given a flat-funded single-platform stack, it actually
picks Claude Code, holds the capability tier, and emits settings the operator
can set. That needs a real API call, so it runs here rather than in the suite.

Usage (keys come from the macOS keychain, per scripts/with-prod-secrets.sh):

    OPENAI_API_KEY=$(security find-generic-password -s roadmodel/OPENAI_API_KEY -w) \\
      python3 scripts/probe-user-stack-contract.py --provider openai

Exit code 0 = every assertion held on every task.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from roadmodel import recommend as recommend_module  # noqa: E402
from roadmodel.config import Config  # noqa: E402
from test_user_stack_contract import EFFORT_WORDS, TASKS, USER_CONTEXT  # noqa: E402

DEFAULT_MODELS = {"openai": "gpt-5-mini", "google": "gemini-3-flash", "anthropic": None}

# Tiers we consider a cost-motivated down-tier for these tasks. The D4
# regression: on a flat $0 plan, even the trivial task must not be dropped to a
# small model purely to "save" money that is not being spent.
SMALL_MODEL_MARKERS = ("haiku", "flash-lite", "mini", "composer", "small")


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai", choices=sorted(DEFAULT_MODELS))
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    env_key = f"{args.provider.upper()}_API_KEY"
    api_key = os.environ.get(env_key)
    if not api_key:
        print(f"error: {env_key} is not set", file=sys.stderr)
        return 2

    # Write the fixture context to a private temp file, never into the repo:
    # a stray dotfile in the working tree is one `git add -A` away from being
    # committed, and this file mirrors the operator's funding state.
    tmp_dir = tempfile.mkdtemp(prefix="roadmodel-probe-")
    ctx_path = Path(tmp_dir) / "user-context.md"
    ctx_path.write_text(USER_CONTEXT, encoding="utf-8")
    os.chmod(ctx_path, 0o600)
    config = Config(
        provider=args.provider,
        model=args.model or DEFAULT_MODELS[args.provider],
        api_key=api_key,
        user_context_path=ctx_path,
    )

    all_ok = True
    try:
        for key in ("trivial", "mid", "hard"):
            print(f"\n=== {key} task ===\n  {TASKS[key][:90]}...")
            result = recommend_module.recommend_structured(TASKS[key], config)
            settings = result.get("settings", {})
            model = str(result.get("model", ""))
            platform = str(result.get("platform", ""))
            print(f"  -> MODEL={model!r} PLATFORM={platform!r} SETTINGS={settings}")

            ok = True
            # D5: the allowlist is a hard filter.
            ok &= check("platform", "claude code" in platform.lower(), platform)
            # D1: no phantom Max Mode dial.
            ok &= check("no max_mode", "max_mode" not in settings, str(settings.keys()))
            # D2: EFFORT present and at the top of the dial under flat funding.
            effort = str(settings.get("effort", ""))
            ok &= check("effort is Max/Ultracode", effort in {"Max", "Ultracode"}, effort)
            # D2: THINKING is a toggle, never an effort word or a number.
            thinking = str(settings.get("thinking", ""))
            ok &= check(
                "thinking is On/Off",
                thinking in {"On", "Off"} and thinking.lower() not in EFFORT_WORDS,
                thinking,
            )
            # D4: no cost-motivated down-tier on a flat $0 plan.
            lowered = model.lower()
            ok &= check(
                "not down-tiered",
                not any(m in lowered for m in SMALL_MODEL_MARKERS),
                model,
            )
            all_ok &= ok
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
