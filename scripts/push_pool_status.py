#!/usr/bin/env python3
"""Push fresh normalized meters to the signed-in user's profile, using Keychain.

Stdlib only; no admin credential, personal context document or raw response is
uploaded. --dry-run is cache-only. --import-refresh-token reads a user session's
refresh token from stdin (or a hidden terminal prompt), verifies it, and stores
it in Keychain. Normal runs rotate that per-user token and update only pools.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import getpass
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))
from app.pools import ORDER, merge, normalize
from pool_usage import CACHE, decide, load

KEYCHAIN_SERVICE = "roadmodel/POOL_SYNC_REFRESH_TOKEN"


def observations(snapshots: dict[str, dict[str, Any]], now: float) -> list[dict[str, Any]]:
    rows = []
    for source, snapshot in snapshots.items():
        groups = [(m.get("name"), [m]) for m in snapshot.get("windows", []) if isinstance(m, dict)]
        if source == "antigravity":
            groups = [("all", snapshot.get("windows", []))]
        if source == "openrouter":
            groups = [("credits", [None])]
        for name, meters in groups:
            decisions = [decide(snapshot, meter, now) for meter in meters]
            if not decisions or any(state is None for state in decisions):
                continue
            state = max((s for s in decisions if s is not None), key=ORDER.__getitem__)
            selected = [m for m, s in zip(meters, decisions, strict=True) if s == state and m]
            resets = [m["resets_at"] for m in selected if m.get("resets_at") is not None]
            if source == "openrouter":
                extra = snapshot["extra"]
                used = max(0, min(100, 100 * (1 - extra["limit_remaining"] / extra["limit"])))
                minutes = 0
            else:
                used = max(m["used_percent"] for m in selected)
                minutes = max(m["window_minutes"] for m in selected)
            rows.append(
                dict(
                    pool=f"{source}:{name}",
                    state=state,
                    observed_at=snapshot["observed_at"],
                    resets_at=max(resets) if resets else None,
                    used_percent=used,
                    window_minutes=minutes,
                )
            )
    return normalize(rows, now)


def keychain(service: str) -> str:
    return (
        subprocess.run(  # noqa: S603 — fixed executable, no shell
            ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            check=True,
            timeout=15,
        )
        .stdout.decode()
        .strip()
    )


def store_token(token: str) -> None:
    # Feed security's interactive command parser over stdin; never put a token
    # in shell history, a process's argv, a cache file or output.
    command = shlex.join(
        ["add-generic-password", "-U", "-a", getpass.getuser(), "-s", KEYCHAIN_SERVICE, "-w", token]
    )
    subprocess.run(
        ["/usr/bin/security", "-i"],
        input=command + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    if keychain(KEYCHAIN_SERVICE) != token:
        raise ValueError("credential storage failed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> None:
        return None


def request(
    url: str, public_key: str, token: str | None = None, body: Any = None, method: str | None = None
) -> Any:
    headers = {
        "apikey": public_key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(  # noqa: S310 — validated HTTPS Supabase origin
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(req, timeout=25) as response:
        return json.load(response)


def credentials(refresh: str) -> tuple[str, str, str, str]:
    url = keychain("roadmodel/SUPABASE_URL").rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not (parsed.hostname or "").endswith(".supabase.co")
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port
    ):
        raise ValueError("unsupported Supabase URL")
    public = keychain("roadmodel/NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if not public.startswith("sb_publishable_"):
        claims = json.loads(base64.urlsafe_b64decode(public.split(".")[1] + "=="))
        if claims.get("role") != "anon":
            raise ValueError("publishable key required")
    session = request(
        url + "/auth/v1/token?grant_type=refresh_token", public, body={"refresh_token": refresh}
    )
    access = session["access_token"]
    claims = json.loads(base64.urlsafe_b64decode(access.split(".")[1] + "=="))
    if claims.get("role") != "authenticated":
        raise ValueError("per-user session required")
    store_token(session["refresh_token"])  # persist rotation before any subsequent request
    user = request(url + "/auth/v1/user", public, access)
    return url, public, access, user["id"]


def push(rows: list[dict[str, Any]], auth: tuple[str, str, str, str], now: float) -> int:
    url, public, token, user_id = auth
    endpoint = url + "/rest/v1/profiles?"
    for _ in range(3):
        query = {"user_id": f"eq.{user_id}", "select": "pool_states,updated_at"}
        existing = request(endpoint + urllib.parse.urlencode(query), public, token)
        if len(existing) != 1:
            raise ValueError("sign in and save a profile before syncing")
        previous = existing[0]["pool_states"]
        updated = merge(previous, rows, now)
        if updated == previous:
            return len(updated)
        # Optimistic concurrency also protects an in-flight settings save.
        query["updated_at"] = "eq." + existing[0]["updated_at"]
        result = request(
            endpoint + urllib.parse.urlencode(query),
            public,
            token,
            {"pool_states": updated},
            "PATCH",
        )
        if result:
            if result[0]["pool_states"] != updated:
                raise ValueError("profile roundtrip mismatch")
            return len(updated)
    raise ValueError("profile changed concurrently; retry next run")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=CACHE)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--import-refresh-token", action="store_true")
    args = ap.parse_args()
    try:
        args.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (args.cache / ".sync.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            now = time.time()
            rows = observations(load(args.cache), now)
            if args.dry_run:
                print(json.dumps(rows, indent=2))
                return 0
            if args.import_refresh_token:
                refresh = (
                    getpass.getpass("Per-user refresh token: ")
                    if sys.stdin.isatty()
                    else sys.stdin.read().strip()
                )
            else:
                refresh = keychain(KEYCHAIN_SERVICE)
            auth = credentials(refresh)
            if args.import_refresh_token:
                print("pool sync: per-user session verified and stored in Keychain")
            else:
                count = push(rows, auth, now)
                print(f"pool sync: authenticated profile roundtrip verified ({count} pools)")
    except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
        # Network/credential exceptions can contain sensitive request metadata.
        print(
            "pool sync: unavailable; saved profile retained (check per-user Keychain session)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
