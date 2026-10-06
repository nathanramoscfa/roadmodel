"""Run installed roadmodel updaters on explicitly configured SSH peers.

The private fleet.json lives beside projects.txt; no network discovery or
bootstrap downloads are performed. Peer output is deliberately not relayed:
it can contain private project paths or memory. Each remote updater writes
its normal local log on mutating runs.

This module is also shipped beside the packaged updater. Keep it stdlib-only
and compatible with Python 3.9, like the standalone launcher.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Optional

CONNECT_TIMEOUT_SECONDS = 10
EXECUTION_TIMEOUT_SECONDS = 1800
DEFAULT_LAUNCHER = "~/.config/roadmodel/update_projects.py"
GLOBAL_RULES_CONFLICT = 73
GLOBAL_RULES_DRIFT = 74
GLOBAL_RULES_ERROR = 75

# Sent over SSH stdin, so neither private rules nor large payloads appear in
# command arguments (Windows cmd.exe also has a relatively short command limit).
# The only dynamic input is the JSON payload, never executable source text.
_REMOTE_SCRIPT = r"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile

def atomic(path, content, expected=None, guard=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.fleet-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if guard:
            observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if observed != expected:
                raise SystemExit(73)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

rules = payload.get('global_rules')
if rules is not None:
    try:
        incoming = rules['text'].encode('utf-8')
        digest = hashlib.sha256(incoming).hexdigest()
        if digest != rules['sha256']:
            raise ValueError('invalid content digest')
        target = Path.home() / '.claude' / 'CLAUDE.md'
        state_file = Path.home() / '.config' / 'roadmodel' / 'fleet-global-rules.json'
        current = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        previous = None
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding='utf-8'))
            previous = state.get('sha256')
            if (state.get('version') != 1 or not isinstance(previous, str)
                    or len(previous) != 64 or any(c not in '0123456789abcdef' for c in previous)):
                raise ValueError('invalid replication state')
        if payload['check']:
            if current != digest:
                raise SystemExit(74)
        else:
            if current is not None and current not in (digest, previous):
                raise SystemExit(73)
            if current != digest:
                atomic(target.resolve() if target.is_symlink() else target, incoming,
                       expected=current, guard=True)
            if previous != digest:
                atomic(state_file, (json.dumps({'version': 1, 'sha256': digest}) + '\n').encode('utf-8'))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise SystemExit(75)

p = os.path.expanduser(payload['launcher'])
sys.path.insert(0, os.path.dirname(os.path.abspath(p)))
sys.argv = [p] + payload['args']
runpy.run_path(p, run_name='__main__')
"""


@dataclass(frozen=True)
class Peer:
    name: str
    host: str
    platform: str
    python: str
    launcher: str
    projects: tuple[str, ...]


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must be a nonempty string without control characters")
    return value


def _path(value: Any, field: str, platform: str, *, allow_home: bool = False) -> str:
    value = _string(value, field)
    path = PureWindowsPath(value) if platform == "windows" else PurePosixPath(value)
    if not path.is_absolute() and not (allow_home and value.startswith("~/")):
        raise ValueError(f"{field} must be an absolute path")
    # These characters cannot occur in a Windows executable/file path, and a
    # quote would make native PowerShell executable dispatch ambiguous.
    if platform == "windows" and any(c in value for c in '"<>|?*'):
        raise ValueError(f"{field} contains an invalid Windows path character")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def load_config(config_path: Path) -> tuple[list[Peer], Optional[Path]]:
    """Validate the entire config before allowing any remote updates."""
    if not config_path.exists():
        return [], None
    data = json.loads(config_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) - {"version", "peers", "global_rules_source"}:
        raise ValueError("expected an object containing version and peers")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("version must be 1")
    peers = data.get("peers")
    if not isinstance(peers, dict):
        raise ValueError("peers must be an object keyed by machine name")
    source = None
    if "global_rules_source" in data:
        source = Path(_string(data["global_rules_source"], "global_rules_source"))
        if not source.is_absolute():
            raise ValueError("global_rules_source must be an absolute local path")
    result = []
    for name, raw in peers.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            raise ValueError(
                "peer names must use 1-64 letters, digits, dots, dashes or underscores"
            )
        label = f"peer {name}"
        if not isinstance(raw, dict) or set(raw) - {
            "host",
            "platform",
            "python",
            "launcher",
            "projects",
        }:
            raise ValueError(f"{label}: unexpected peer fields")
        platform = raw.get("platform")
        if platform not in ("posix", "windows"):
            raise ValueError(f"{label}: platform must be posix or windows")
        host = _string(raw.get("host"), f"{label}.host")
        if not re.fullmatch(
            r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9_\[][-A-Za-z0-9_.:\[\]]*",
            host,
        ):
            raise ValueError(
                f"{label}: host must be an SSH alias or hostname, optionally user@host"
            )
        python = _path(raw.get("python"), f"{label}.python", platform)
        launcher = _path(
            raw.get("launcher", DEFAULT_LAUNCHER), f"{label}.launcher", platform, allow_home=True
        )
        projects = raw.get("projects")
        if not isinstance(projects, list) or not projects:
            raise ValueError(f"{label}: projects must be a nonempty list of absolute paths")
        paths = tuple(_path(project, f"{label}.projects", platform) for project in projects)
        result.append(Peer(name, host, platform, python, launcher, paths))
    return result, source


def load_peers(config_path: Path) -> list[Peer]:
    """Compatibility helper for callers inspecting configured peer commands."""
    return load_config(config_path)[0]


def _updater_args(peer: Peer, *, sync_only: bool, check: bool) -> list[str]:
    args = ["--local-only"]  # A peer can have its own fleet: never recurse.
    if check:
        args.append("--check")
    elif sync_only:
        args.append("--sync-only")
    else:
        # A coordinated upgrade repairs context without starting model-backed
        # roadmap sessions on peers, even though it writes a local log.
        args.append("--skip-roadmap-refresh")
    if not check:
        args.extend(["--log", "--add"])
    args.extend(peer.projects)
    return args


def build_command(
    peer: Peer, *, sync_only: bool = False, check: bool = False, stdin_script: bool = False
) -> list[str]:
    """Build one SSH invocation without interpolating paths into executable code.

    Both shells receive a constant Python bootstrap plus an encoded JSON
    payload. The bootstrap expands ~ on the *remote* machine and dispatches
    the installed launcher with the exact argv, including spaces/metacharacters.
    Windows SSH can use either cmd.exe or PowerShell as its configured shell;
    the outer command is ASCII-only PowerShell -EncodedCommand for both.
    """
    payload = base64.b64encode(
        json.dumps(
            {
                "launcher": peer.launcher,
                "args": _updater_args(peer, sync_only=sync_only, check=check),
            }
        ).encode("utf-8")
    ).decode("ascii")
    code = (
        "import base64,json,os,runpy,sys;"
        f"d=json.loads(base64.b64decode('{payload}'));"
        "p=os.path.expanduser(d['launcher']);"
        "sys.path.insert(0,os.path.dirname(os.path.abspath(p)));"
        "sys.argv=[p]+d['args'];"
        "runpy.run_path(p,run_name='__main__')"
    )
    python_args = ["-"] if stdin_script else ["-c", code]
    if peer.platform == "windows":
        quote = lambda s: "'" + s.replace("'", "''") + "'"  # noqa: E731
        script = (
            "$ErrorActionPreference='Stop';"
            f"& {quote(peer.python)} {' '.join(quote(arg) for arg in python_args)};"
            "if ($null -eq $LASTEXITCODE) { exit 1 };exit $LASTEXITCODE"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        remote = "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    else:
        remote = shlex.join([peer.python, *python_args])
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
        "--",
        peer.host,
        remote,
    ]


def build_input(
    peer: Peer, global_rules: dict[str, str], *, sync_only: bool = False, check: bool = False
) -> bytes:
    """Encode data into a constant bootstrap delivered only through SSH stdin."""
    payload = {
        "launcher": peer.launcher,
        "args": _updater_args(peer, sync_only=sync_only, check=check),
        "check": check,
        "global_rules": global_rules,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    prefix = f"import base64,json\npayload=json.loads(base64.b64decode('{encoded}'))\n"
    return (prefix + _REMOTE_SCRIPT).encode("utf-8")


def run_fleet(
    config_path: Path, *, dry_run: bool = False, sync_only: bool = False, check: bool = False
) -> tuple[list[str], bool]:
    """Return concise status lines and whether every configured peer succeeded.

    Missing configuration is an intentional no-op. Dry runs validate the
    config and describe each peer without opening SSH, touching its registry,
    or creating local files. Check mode contacts peers but never registers
    directories or requests remote logging.
    """
    try:
        peers, source = load_config(Path(config_path))
        rules = None
        if source is not None:
            content = source.read_bytes()
            rules = {"text": content.decode("utf-8"), "sha256": hashlib.sha256(content).hexdigest()}
    except (OSError, ValueError) as exc:
        # JSON parser errors can include file content on some runtimes. Only
        # report our schema errors; never echo arbitrary data from the config.
        detail = (
            str(exc) if type(exc) is ValueError else "cannot read valid fleet JSON or global rules"
        )
        return [f"fleet: invalid configuration ({detail})"], False
    lines = []
    success = True
    for peer in peers:
        if dry_run:
            mode = "check" if check else "synchronize" if sync_only else "upgrade"
            lines.append(
                f"fleet {peer.name}: would {mode} {len(peer.projects)} configured project(s)"
            )
            continue
        try:
            input_kwargs = (
                {"input": build_input(peer, rules, sync_only=sync_only, check=check)}
                if rules is not None
                else {"stdin": subprocess.DEVNULL}
            )
            completed = subprocess.run(  # noqa: S603 — validated host and shell-encoded payload
                build_command(
                    peer, sync_only=sync_only, check=check, stdin_script=rules is not None
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=EXECUTION_TIMEOUT_SECONDS,
                check=False,
                **input_kwargs,
            )
            if completed.returncode:
                success = False
                if rules is not None and completed.returncode == GLOBAL_RULES_CONFLICT:
                    detail = "global rules conflict; coordinator and peer versions preserved"
                elif rules is not None and completed.returncode == GLOBAL_RULES_DRIFT:
                    detail = "global rules differ from coordinator; run an upgrade to reconcile"
                elif rules is not None and completed.returncode == GLOBAL_RULES_ERROR:
                    detail = "could not validate or apply global rules and replication state"
                elif completed.returncode == 255:
                    detail = (
                        "SSH connection failed; check reachability, host key and authentication"
                    )
                elif check:
                    detail = (
                        f"updater exited {completed.returncode}; run its local --check for details"
                    )
                else:
                    detail = f"updater exited {completed.returncode}; inspect its local update log"
                lines.append(f"fleet {peer.name}: FAILED ({detail})")
            else:
                lines.append(f"fleet {peer.name}: OK ({len(peer.projects)} configured project(s))")
        except subprocess.TimeoutExpired:
            success = False
            lines.append(
                f"fleet {peer.name}: FAILED (execution exceeded {EXECUTION_TIMEOUT_SECONDS}s)"
            )
        except OSError:
            success = False
            lines.append(f"fleet {peer.name}: FAILED (could not execute SSH)")
    return lines, success
