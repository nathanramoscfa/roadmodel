#!/usr/bin/env python3
"""Resolve and validate data-refresh PRs using authenticated GitHub metadata."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from typing import Any

COMMON = {"docs/model-selector.txt", "docs/model-selector.md", "docs/catalog.json"}
POLICIES: dict[str, tuple[str, set[str]]] = {
    "update-models.yml": (
        "chore/catalog-refresh-",
        COMMON
        | {"docs/model-tier-cost-scale.md", "docs/context-windows.json", "docs/effort-ratings.json"}
        | {
            f"update/catalog-{provider}.json"
            for provider in (
                "anthropic",
                "openai",
                "google",
                "xai",
                "deepseek",
                "zai",
                "mistral",
                "groq",
            )
        },
    ),
    "update-claude-code.yml": (
        "chore/claude-code-refresh-",
        COMMON | {"update/claude-code-effort.json"},
    ),
    "update-codex.yml": (
        "chore/codex-refresh-",
        COMMON | {"update/codex-reasoning.json", "update/codex-reasoning-source.md"},
    ),
    "update-gemini.yml": ("chore/gemini-refresh-", COMMON | {"update/gemini-thinking.json"}),
    "update-deepseek.yml": ("chore/deepseek-refresh-", COMMON | {"update/deepseek-thinking.json"}),
    "update-benchmarks.yml": (
        "chore/benchmarks-refresh-",
        COMMON | {"docs/benchmarks.json", "docs/effort-ratings.json", "update/aa-model-map.json"},
    ),
    "probe-availability.yml": (
        "auto/availability-",
        {"infra/model-availability.json", "docs/model-selector.txt", "docs/model-selector.md"},
    ),
}


def api(repo: str, path: str) -> Any:
    result = subprocess.run(  # noqa: S603 — fixed executable and argument vector
        ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/{path}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    pages = json.loads(result.stdout)
    if pages and isinstance(pages[0], list):
        return [item for page in pages for item in page]
    if len(pages) != 1:
        raise ValueError("unexpected API response")
    return pages[0]


def policy(run: dict[str, Any], repo: str) -> tuple[str, set[str]] | None:
    if (
        run["repository"]["full_name"] != repo
        or run["head_branch"] != "main"
        or run["event"] not in {"schedule", "workflow_dispatch"}
        or run["conclusion"] != "success"
    ):
        raise ValueError("run is not a successful main-branch refresh")
    path = run["path"]
    if not path.startswith(".github/workflows/"):
        raise ValueError("unexpected workflow path")
    workflow = path.removeprefix(".github/workflows/")
    if workflow not in POLICIES:
        return None  # Health and soak jobs never create mergeable PRs.
    prefix, allowed = POLICIES[workflow]
    # Jobs name their branch with the UTC date at commit time. A run crossing
    # midnight can have either date; validation below checks the PR timestamp.
    suffix = f"-{run['id']}" if workflow == "probe-availability.yml" else ""
    dates = {run["created_at"][:10], run["updated_at"][:10]}
    branches = "|".join(re.escape(prefix + day + suffix) for day in sorted(dates))
    return branches, allowed


def validate(
    run: dict[str, Any], pr: dict[str, Any], files: list[dict[str, Any]], repo: str
) -> str:
    selected = policy(run, repo)
    if selected is None:
        raise ValueError("workflow does not create data PRs")
    branches, allowed = selected
    if (
        pr["user"]["login"] != "roadmodel-cron-bot[bot]"
        or pr["user"]["type"] != "Bot"
        or pr["base"]["ref"] != "main"
        or pr["base"]["repo"]["full_name"] != repo
        or pr["head"]["repo"]["full_name"] != repo
        or re.fullmatch(branches, pr["head"]["ref"]) is None
        or pr["draft"]
    ):
        raise ValueError("PR provenance does not match the refresh")
    created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
    start = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
    if not start <= created <= end:
        raise ValueError("PR was not created during this run")
    if not files or len(files) != pr["changed_files"]:
        raise ValueError("incomplete changed-file inventory")
    if any(
        f["filename"] not in allowed
        or ("previous_filename" in f and f["previous_filename"] not in allowed)
        for f in files
    ):
        raise ValueError("PR changes files outside the refresh policy")
    sha = pr["head"]["sha"]
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("invalid PR commit")
    return sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--pr", type=int)
    args = parser.parse_args()
    try:
        run = api(args.repo, f"actions/runs/{args.run}")
        selected = policy(run, args.repo)
        if args.pr is not None:
            pr = api(args.repo, f"pulls/{args.pr}")
            files = api(args.repo, f"pulls/{args.pr}/files?per_page=100")
            print(validate(run, pr, files, args.repo))
        elif selected is not None:
            # Enumerate API records, never interpret workflow logs as commands
            # or as evidence that a privileged operation should target a PR.
            branches, _ = selected
            for pr in api(args.repo, "pulls?state=open&base=main&per_page=100"):
                if re.fullmatch(branches, pr["head"]["ref"]) is None:
                    continue
                detail = api(args.repo, f"pulls/{pr['number']}")
                files = api(args.repo, f"pulls/{pr['number']}/files?per_page=100")
                validate(run, detail, files, args.repo)
                print(pr["number"])
    except (KeyError, TypeError, ValueError, subprocess.SubprocessError):
        print("Cannot validate refresh PR provenance; refusing automated merge.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
