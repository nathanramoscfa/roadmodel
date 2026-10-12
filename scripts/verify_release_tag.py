#!/usr/bin/env python3
"""Verify a release against main's reviewed SSH signer policy before execution."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path


class ReleaseRejected(ValueError):
    """The tag does not satisfy the release trust policy."""


def git(*args: str) -> str:
    return subprocess.check_output(  # noqa: S603 - validated argv, no shell
        ["git", *args],  # noqa: S607 - system Git
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def release_version(tag: str) -> str:
    match = re.fullmatch(r"v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))", tag)
    if not match:
        raise ReleaseRejected("Use a stable vMAJOR.MINOR.PATCH release tag.")
    return match[1]


def remote_object(tag: str) -> str:
    release_version(tag)
    rows = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}").splitlines()
    if len(rows) != 1:
        raise ReleaseRejected("Release tag is missing from origin.")
    oid, ref = rows[0].split()
    if ref != f"refs/tags/{tag}" or not re.fullmatch(r"[0-9a-f]{40}", oid):
        raise ReleaseRejected("Invalid remote tag reference.")
    return oid


def require_ssh_signature(payload: str) -> None:
    # Git autodetects the verification format, irrespective of gpg.format.
    # Require the actual terminal signature, not a marker in the tag message.
    marker = "\n-----BEGIN SSH SIGNATURE-----\n"
    if (
        payload.count(marker) != 1
        or "-----BEGIN PGP" in payload
        or "-----BEGIN SIGNED MESSAGE-----" in payload
        or not re.search(
            r"\n-----BEGIN SSH SIGNATURE-----\n[A-Za-z0-9+/=\n]+\n"
            r"-----END SSH SIGNATURE-----\Z",
            payload,
        )
    ):
        raise ReleaseRejected("Release requires an approved SSH signature.")


def verify(tag: str, *, local: bool = False) -> dict[str, str]:
    version = release_version(tag)
    # Capture main once; neither the signer policy nor version check comes
    # from a candidate worktree. No candidate code is imported or executed.
    main = git("rev-parse", "refs/remotes/origin/main^{commit}")
    expected = None if local else remote_object(tag)
    if not local:
        git("fetch", "--no-tags", "origin", f"refs/tags/{tag}")
        oid = git("rev-parse", "FETCH_HEAD")
        if oid != expected:
            raise ReleaseRejected("Release tag changed during verification.")
    else:
        oid = git("rev-parse", f"refs/tags/{tag}")
    if git("cat-file", "-t", oid) != "tag":
        raise ReleaseRejected("Release requires an annotated signed tag.")
    payload = git("cat-file", "tag", oid)
    require_ssh_signature(payload)
    headers = dict(line.split(" ", 1) for line in payload.split("\n\n", 1)[0].splitlines())
    commit = headers.get("object", "")
    if (
        headers.get("type") != "commit"
        or headers.get("tag") != tag
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise ReleaseRejected("Tag must name this release and directly target a commit.")
    policy = git("show", f"{main}:.github/release-allowed-signers")
    with tempfile.TemporaryDirectory(prefix="roadmodel-release-policy-") as directory:
        signers = Path(directory) / "allowed-signers"
        signers.write_text(policy + "\n")
        git(
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.allowedSignersFile={signers}",
            "verify-tag",
            oid,
        )
    git("merge-base", "--is-ancestor", commit, main)
    project = tomllib.loads(git("show", f"{commit}:pyproject.toml"))
    if project["project"]["version"] != version:
        raise ReleaseRejected("Tag and package version differ.")
    if not local and remote_object(tag) != oid:
        raise ReleaseRejected("Release tag changed during verification.")
    return {"tag": tag, "tag_object": oid, "commit": commit, "main": main}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--local", action="store_true", help="verify before the first push")
    parser.add_argument("--expect-object", help="only check origin still has this verified object")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    try:
        if args.expect_object:
            if not re.fullmatch(r"[0-9a-f]{40}", args.expect_object):
                raise ReleaseRejected("Invalid expected tag object.")
            if remote_object(args.tag) != args.expect_object:
                raise ReleaseRejected("Release tag changed after verification.")
            return 0
        result = verify(args.tag, local=args.local)
        if args.github_output:
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.writelines(f"{key}={value}\n" for key, value in result.items())
        else:
            print(json.dumps(result))
    except (ReleaseRejected, subprocess.SubprocessError, OSError, ValueError, KeyError):
        # Git may include identities or local paths in its diagnostic output.
        print("Release verification failed; no build or publication is authorized.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
