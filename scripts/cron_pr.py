#!/usr/bin/env python3
"""Resolve and validate data-refresh PRs using authenticated GitHub metadata."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

UPDATE = Path(__file__).resolve().parents[1] / "update"
if str(UPDATE) not in sys.path:
    sys.path.insert(0, str(UPDATE))

from automation_integrity import INPUTS, validate_documents  # noqa: E402

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
        COMMON | {"infra/model-availability.json"},
    ),
}


def api(repo: str, path: str, *, paginate: bool = True) -> Any:
    flags = ["--paginate", "--slurp"] if paginate else []
    result = subprocess.run(  # noqa: S603 — fixed executable and argument vector
        ["gh", "api", *flags, f"repos/{repo}/{path}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    pages = json.loads(result.stdout)
    if not paginate:
        return pages
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
    run: dict[str, Any],
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    repo: str,
    *,
    committed_at: str | None = None,
    check_time: bool = True,
) -> str:
    selected = policy(run, repo)
    if selected is None:
        raise ValueError("workflow does not create data PRs")
    branches, allowed = selected
    if (
        pr["user"]["login"] != "roadmodel-cron-bot[bot]"
        or pr["user"]["id"] != 293410582
        or pr["user"]["type"] != "Bot"
        or pr["base"]["ref"] != "main"
        or pr["base"]["repo"]["full_name"] != repo
        or pr["head"]["repo"]["full_name"] != repo
        or re.fullmatch(branches, pr["head"]["ref"]) is None
        or pr["draft"]
    ):
        raise ValueError("PR provenance does not match the refresh")
    created = datetime.fromisoformat((committed_at or pr["created_at"]).replace("Z", "+00:00"))
    start = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
    if check_time and not start <= created <= end:
        raise ValueError("PR commit was not produced during this run")
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


def validated_commit(
    run: dict[str, Any],
    pr: dict[str, Any],
    repo: str,
    *,
    check_time: bool = True,
    check_content: bool = True,
) -> str:
    """Check immutable commit/tree objects, including same-day refreshed PRs."""
    head = pr["head"]["sha"]
    base = pr["base"]["sha"]
    if any(re.fullmatch(r"[0-9a-f]{40}", sha) is None for sha in (head, base)):
        raise ValueError("invalid comparison commits")
    comparison = api(repo, f"compare/{base}...{head}")
    files = comparison["files"]
    # GitHub limits comparison files to 300. Refuse a truncated result rather
    # than falling back to the mutable pull-request files endpoint.
    if len(files) >= 300:
        raise ValueError("comparison exceeds the data refresh limit")
    commit = api(repo, f"git/commits/{head}")
    if commit["sha"] != head:
        raise ValueError("unexpected commit response")
    sha = validate(
        run, pr, files, repo, committed_at=commit["committer"]["date"], check_time=check_time
    )
    tree = api(repo, f"git/trees/{head}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("incomplete commit tree")
    entries = {entry["path"]: entry for entry in tree["tree"]}
    for file in files:
        if file["status"] == "removed":
            raise ValueError("refresh must not remove files")
        entry = entries[file["filename"]]
        if entry["type"] != "blob" or entry["mode"] != "100644":
            raise ValueError("refresh data must be regular non-executable files")
    if check_content:
        validate_content(repo, base, head, entries, run["updated_at"])
    return sha


def validate_content(repo: str, base: str, head: str, entries: dict[str, Any], date: str) -> None:
    for path in INPUTS:
        if entries[path]["type"] != "blob" or entries[path]["mode"] != "100644":
            raise ValueError("instruction inputs must be regular data files")
    validate_documents(
        lambda path: content(repo, base, path),
        lambda path: content(repo, head, path),
        datetime.fromisoformat(date.replace("Z", "+00:00")).date(),
    )


def review_candidate(repo: str, pr: dict[str, Any]) -> None:
    """Independent bot path/content check; producer provenance stays in the merger."""
    if pr["user"]["id"] != 293410582:
        return  # Maintainer and dependency PRs use their ordinary review/checks.
    if (
        pr["user"]["login"] != "roadmodel-cron-bot[bot]"
        or pr["user"]["type"] != "Bot"
        or pr["base"]["ref"] != "main"
        or pr["base"]["repo"]["full_name"] != repo
        or pr["head"]["repo"]["full_name"] != repo
    ):
        raise ValueError("unexpected refresh origin")
    allowed = None
    for workflow, (prefix, paths) in POLICIES.items():
        suffix = r"-\d+" if workflow == "probe-availability.yml" else ""
        if re.fullmatch(re.escape(prefix) + r"\d{4}-\d{2}-\d{2}" + suffix, pr["head"]["ref"]):
            allowed = paths
            break
    if allowed is None:
        raise ValueError("unknown refresh producer")
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    if any(re.fullmatch(r"[0-9a-f]{40}", sha) is None for sha in (base, head)):
        raise ValueError("invalid comparison commits")
    files = api(repo, f"compare/{base}...{head}")["files"]
    if not files or len(files) >= 300 or len(files) != pr["changed_files"]:
        raise ValueError("incomplete changed-file inventory")
    tree = api(repo, f"git/trees/{head}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("incomplete tree")
    entries = {item["path"]: item for item in tree["tree"]}
    for file in files:
        path = file["filename"]
        if (
            path not in allowed
            or file.get("previous_filename", path) not in allowed
            or file["status"] == "removed"
            or entries[path]["type"] != "blob"
            or entries[path]["mode"] != "100644"
        ):
            raise ValueError("refresh path policy")
    validate_content(repo, base, head, entries, pr["updated_at"])


def review(repo: str, number: int, *, post_status: bool = False) -> None:
    pr = api(repo, f"pulls/{number}")
    head = pr["head"]["sha"]
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ValueError("invalid status commit")
    state = "failure"
    try:
        review_candidate(repo, pr)
        state = "success"
    finally:
        if post_status:
            # pull_request_target runs in base context. Publish the independent
            # verdict on the exact candidate SHA, never a later mutable PR head.
            subprocess.run(  # noqa: S603 — fixed gh executable, no shell
                ["gh", "api", "--method", "POST", f"repos/{repo}/statuses/{head}", "--input", "-"],  # noqa: S607
                input=json.dumps(
                    {
                        "state": state,
                        "context": "refresh-integrity",
                        "description": "Trusted base policy for automated refresh content",
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )


def content(repo: str, commit: str, path: str) -> str:
    """Read an immutable blob without checking out or executing candidate code."""
    data = api(repo, f"contents/{path}?ref={commit}")
    if data["type"] != "file" or data["size"] > 2_000_000 or data["encoding"] != "base64":
        raise ValueError("invalid data blob")
    return base64.b64decode("".join(data["content"].split()), validate=True).decode("utf-8")


def pending(repo: str) -> list[tuple[int, int]]:
    """Bounded catch-up after checks/rebases finish beyond a producer's run."""
    result: list[tuple[int, int]] = []
    prs = api(repo, "pulls?state=open&base=main&per_page=100")
    for workflow, (prefix, _) in POLICIES.items():
        candidates = [
            pr
            for pr in prs
            if pr["user"]["login"] == "roadmodel-cron-bot[bot]"
            and not pr["draft"]
            and pr["head"]["ref"].startswith(prefix)
        ]
        if not candidates:
            continue
        runs = api(
            repo,
            f"actions/workflows/{workflow}/runs?branch=main&status=success&per_page=100",
            paginate=False,
        )
        for pr in candidates:
            for run in runs["workflow_runs"][:100]:
                try:
                    selected = policy(run, repo)
                except (KeyError, TypeError, ValueError):
                    continue
                if selected and re.fullmatch(selected[0], pr["head"]["ref"]):
                    detail = api(repo, f"pulls/{pr['number']}")
                    try:
                        validated_commit(run, detail, repo, check_time=False, check_content=False)
                    except (KeyError, TypeError, ValueError, subprocess.SubprocessError):
                        print(
                            "Skipping refresh that needs provenance/path review.", file=sys.stderr
                        )
                        break
                    result.append((run["id"], pr["number"]))
                    break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=int)
    mode.add_argument("--pending", action="store_true")
    mode.add_argument("--review", type=int)
    parser.add_argument("--pr", type=int)
    parser.add_argument(
        "--paths-only", action="store_true", help="discovery/rebase only, never merge"
    )
    parser.add_argument(
        "--post-status", action="store_true", help="publish review on its exact head"
    )
    args = parser.parse_args()
    try:
        if args.review:
            review(args.repo, args.review, post_status=args.post_status)
            print("Refresh instruction and path policy passed.")
            return 0
        if args.pending:
            for run_id, number in pending(args.repo):
                print(run_id, number)
            return 0
        run = api(args.repo, f"actions/runs/{args.run}")
        selected = policy(run, args.repo)
        if args.pr is not None:
            pr = api(args.repo, f"pulls/{args.pr}")
            # Discovery already bound this PR to the run. A subsequent trusted
            # rebase changes its commit timestamp; all origin, path, tree and
            # SHA checks still run immediately before every merge attempt.
            print(
                validated_commit(
                    run, pr, args.repo, check_time=False, check_content=not args.paths_only
                )
            )
        elif selected is not None:
            # Enumerate API records, never interpret workflow logs as commands
            # or as evidence that a privileged operation should target a PR.
            branches, _ = selected
            for pr in api(args.repo, "pulls?state=open&base=main&per_page=100"):
                if re.fullmatch(branches, pr["head"]["ref"]) is None:
                    continue
                detail = api(args.repo, f"pulls/{pr['number']}")
                validated_commit(run, detail, args.repo, check_content=False)
                print(pr["number"])
    except (KeyError, TypeError, ValueError, subprocess.SubprocessError):
        print("Cannot validate refresh PR provenance; refusing automated merge.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
