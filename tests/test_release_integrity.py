"""Release trust checks use synthetic repositories and ephemeral signing keys."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_release_tag", ROOT / "scripts/verify_release_tag.py"
)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    command("git", "init", "-b", "main")
    command("git", "config", "user.name", "Release test")
    command("git", "config", "user.email", "release@example.invalid")
    for name in ("signer", "other"):
        command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / name))
    command("git", "config", "gpg.format", "ssh")
    command("git", "config", "user.signingkey", str(tmp_path / "signer"))
    policy = tmp_path / ".github/release-allowed-signers"
    policy.parent.mkdir()
    key = " ".join((tmp_path / "signer.pub").read_text().split()[:2])
    policy.write_text(f'release-test namespaces="git" {key}\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    command("git", "add", ".github", "pyproject.toml")
    command("git", "commit", "-m", "Fixture")
    command("git", "clone", "--bare", ".", str(tmp_path / "origin.git"))
    command("git", "remote", "add", "origin", str(tmp_path / "origin.git"))
    command("git", "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def tag(name: str = "v1.2.3", *extra: str) -> None:
    command("git", "tag", "-s", name, "-m", "Synthetic release", *extra)


def test_signed_tag_local_and_remote(repository: Path) -> None:
    tag()
    local = verifier.verify("v1.2.3", local=True)
    command("git", "push", "origin", "v1.2.3")
    assert verifier.verify("v1.2.3") == local
    assert local["commit"] == command("git", "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "kind",
    [
        "unsigned",
        "lightweight",
        "wrong-key",
        "nested",
        "name",
        "version",
        "off-main",
        "missing-policy",
    ],
)
def test_invalid_tags_rejected(repository: Path, kind: str) -> None:
    if kind == "unsigned":
        command("git", "tag", "-a", "v1.2.3", "-m", "Unsigned")
    elif kind == "lightweight":
        command("git", "tag", "v1.2.3")
    elif kind == "wrong-key":
        command("git", "config", "user.signingkey", str(repository / "other"))
        tag()
    elif kind == "nested":
        tag("v1.2.4")
        tag("v1.2.3", "v1.2.4")
    elif kind == "name":
        tag("v1.2.4")
        command("git", "update-ref", "refs/tags/v1.2.3", "refs/tags/v1.2.4")
    elif kind == "version":
        (repository / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
        command("git", "commit", "-am", "Different version")
        command("git", "update-ref", "refs/remotes/origin/main", "HEAD")
        tag()
    elif kind == "off-main":
        command("git", "commit", "--allow-empty", "-m", "Not reviewed on main")
        tag()
    else:
        command("git", "rm", ".github/release-allowed-signers")
        command("git", "commit", "-m", "No signer policy")
        command("git", "update-ref", "refs/remotes/origin/main", "HEAD")
        tag()
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        verifier.verify("v1.2.3", local=True)


@pytest.mark.parametrize(
    "value",
    [
        "--help",
        "v1.2.3\n",
        "v1.2.3;true",
        "v1.2.3/other",
        "v1.2.3^{}",
        "v01.2.3",
        "v1.2.3-pypi",
        "v1.2.3-phase-2",
    ],
)
def test_release_names_reject_nonstable_input(value: str) -> None:
    with pytest.raises(ValueError):
        verifier.release_version(value)


def test_signer_policy_comes_from_main_not_worktree(repository: Path) -> None:
    (repository / ".github/release-allowed-signers").write_text("invalid\n")
    tag()
    assert verifier.verify("v1.2.3", local=True)["tag"] == "v1.2.3"


def test_signature_tool_failure_is_closed(repository: Path) -> None:
    tag()
    command("git", "config", "gpg.ssh.program", "false")
    with pytest.raises(subprocess.SubprocessError):
        verifier.verify("v1.2.3", local=True)


@pytest.mark.parametrize(
    "marker", ["PGP SIGNATURE", "PGP MESSAGE", "SIGNED MESSAGE", "SSH SIGNATURE"]
)
def test_message_marker_cannot_replace_terminal_ssh_signature(marker: str) -> None:
    fake = "message\n-----BEGIN SSH SIGNATURE-----\nYWJj\n-----END SSH SIGNATURE-----"
    extra = f"\n-----BEGIN {marker}-----\nYWJj\n-----END {marker}-----"
    with pytest.raises(ValueError):
        verifier.require_ssh_signature(fake + extra)


def test_changed_remote_tag_rejected(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tag()
    command("git", "push", "origin", "v1.2.3")
    original = verifier.remote_object
    calls = 0

    def changed(name: str) -> str:
        nonlocal calls
        calls += 1
        return original(name) if calls == 1 else "0" * 40

    monkeypatch.setattr(verifier, "remote_object", changed)
    with pytest.raises(ValueError, match="changed"):
        verifier.verify("v1.2.3")


@pytest.mark.parametrize("existing", [False, True])
def test_release_shell_never_publishes_after_sign_or_verify_failure(
    tmp_path: Path, existing: bool
) -> None:
    script = (ROOT / "scripts/release.sh").read_text()
    # Execute the actual production tag/resume section, using shell functions
    # to isolate all network/signing/publication effects.
    section = script.split(
        "# ---------------------------------------------------------------- 2. tag\n"
    )[1].split("# ------------------------------------------- 2b.")[0]
    marker = tmp_path / "published"
    harness = f"""set -euo pipefail
tag=v1.2.3
version=1.2.3
git() {{ if [ "$1" = ls-remote ]; then return {0 if existing else 1}; fi; return 1; }}
pyproject_version() {{ echo 1.2.3; }}
verify_release() {{ return 1; }}
quiet_push() {{ touch "$MARKER"; }}
log() {{ :; }}
die() {{ exit 1; }}
{section}
touch "$MARKER"
"""
    (tmp_path / "pyproject.toml").write_text("")
    result = subprocess.run(
        ["bash", "-c", harness],
        cwd=tmp_path,
        env={**os.environ, "MARKER": str(marker)},
        capture_output=True,
    )
    assert result.returncode != 0
    assert not marker.exists()


def test_release_health_poll_retries_transient_failure(tmp_path: Path) -> None:
    script = (ROOT / "scripts/release.sh").read_text()
    section = script.split(
        "# ---------------------------------------------------------- 5. production\n"
    )[1]
    harness = f"""set -euo pipefail
version=1.2.3
healthz_version() {{
  if [ ! -e "$MARKER" ]; then touch "$MARKER"; return 1; fi
  echo 1.2.3
}}
sleep() {{ :; }}
log() {{ :; }}
die() {{ exit 1; }}
{section}
"""
    result = subprocess.run(
        ["bash", "-c", harness],
        env={**os.environ, "MARKER": str(tmp_path / "first-poll")},
        capture_output=True,
    )
    assert result.returncode == 0
