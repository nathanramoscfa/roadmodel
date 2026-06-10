#!/usr/bin/env python3
"""Local watcher for roadmodel pre-launch gate intrusion alerts.

The hosted gate (web/lib/gateGuard.ts) pushes one event onto the Upstash list
`gate:alerts` each time a client is locked out after 3 failed SITE_PASSWORD
attempts. This watcher DRAINS that list and surfaces each event as:
  1. a native macOS desktop notification (always), and
  2. a best-effort email to GATE_ALERT_EMAIL via your existing Mail.app (no
     signup, no new service — uses the account Mail.app already has).

It is meant to run on a short interval via launchd (see
scripts/com.roadmodel.gate-alert-watcher.plist): one drain pass per invocation,
then exit. Needs no extra dependencies (stdlib only) and no new accounts.

Upstash creds come from $UPSTASH_REDIS_URL / $UPSTASH_REDIS_TOKEN, falling back
to the macOS keychain entries `roadmodel/UPSTASH_REDIS_URL` and
`roadmodel/UPSTASH_REDIS_TOKEN` (the same store scripts/with-prod-secrets.sh
uses). If creds are absent the watcher exits quietly (no-op).

Env overrides:
  GATE_ALERT_EMAIL   recipient for the Mail.app email (default below; empty = skip)
  GATE_ALERT_NO_MAIL if set, skip the email and only show the desktop popup
"""

from __future__ import annotations

import json
import subprocess
import sys
from urllib import error, parse, request

DEFAULT_EMAIL = "nramos@nrcapital.finance"
ALERTS_KEY = "gate:alerts"
MAX_DRAIN = 50  # safety cap per pass


def _keychain(name: str) -> str:
    try:
        out = subprocess.run(  # noqa: S603 — fixed binary, literal service name
            ["/usr/bin/security", "find-generic-password", "-s", f"roadmodel/{name}", "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _env_or_keychain(name: str) -> str:
    import os

    return os.environ.get(name, "").strip() or _keychain(name)


def _rest_base(url: str) -> str:
    """Derive the Upstash HTTPS REST base from either an https:// or rediss:// URL."""
    if url.startswith("https://"):
        return url.rstrip("/")
    # rediss://default:<pw>@<host>:<port>  ->  https://<host>
    host = parse.urlsplit(url).hostname or ""
    return f"https://{host}" if host else ""


def _rpop(base: str, token: str) -> str | None:
    """RPOP one element off the alerts list via the Upstash REST API."""
    req = request.Request(  # noqa: S310 — base is a fixed https Upstash host
        f"{base}/rpop/{ALERTS_KEY}",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed https host
            payload = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"[gate-watcher] Upstash RPOP failed: {exc}", file=sys.stderr)
        return None
    # Upstash REST returns {"result": <value-or-null>}
    return payload.get("result")


def _osa(script: str) -> None:
    try:
        subprocess.run(  # noqa: S603 — fixed binary, controlled script
            ["/usr/bin/osascript", "-e", script], capture_output=True, timeout=15
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        print(f"[gate-watcher] osascript failed: {exc}", file=sys.stderr)


def _esc(text: str) -> str:
    """Escape a string for embedding inside an AppleScript double-quoted literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, body: str) -> None:
    _osa(f'display notification "{_esc(body)}" with title "{_esc(title)}" sound name "Sosumi"')


def send_mail(to_addr: str, subject: str, body: str) -> None:
    # Best-effort: uses whatever account Mail.app already has configured. If
    # Mail.app isn't set up / automation isn't granted, this no-ops (the
    # desktop popup already fired).
    script = (
        'tell application "Mail"\n'
        f'  set m to make new outgoing message with properties {{subject:"{_esc(subject)}", '
        f'content:"{_esc(body)}", visible:false}}\n'
        "  tell m\n"
        f'    make new to recipient at end of to recipients with properties {{address:"{_esc(to_addr)}"}}\n'
        "  end tell\n"
        "  send m\n"
        "end tell"
    )
    _osa(script)


def format_event(raw: str) -> tuple[str, str]:
    """Return (short popup body, long email body) for one alert event."""
    try:
        e = json.loads(raw)
    except json.JSONDecodeError:
        return (raw[:180], raw)
    ip = e.get("ip", "unknown")
    ua = e.get("ua", "unknown")
    ts = e.get("ts", "")
    mins = int(e.get("lock_seconds", 300)) // 60
    short = f"{e.get('attempts', 3)} failed attempts from {ip} — locked {mins}m"
    long = (
        "Someone (or something) hit the roadmodel.ai preview gate and was locked "
        f"out after {e.get('attempts', 3)} failed password attempts.\n\n"
        f"When:  {ts}\n"
        f"IP:    {ip}\n"
        f"Agent: {ua}\n"
        f"Lock:  {mins} minutes\n\n"
        "The site stays gated; this is informational. If it was you, ignore it."
    )
    return (short, long)


def main() -> int:
    import os

    url = _env_or_keychain("UPSTASH_REDIS_URL")
    token = _env_or_keychain("UPSTASH_REDIS_TOKEN")
    base = _rest_base(url) if url else ""
    if not base or not token:
        # No creds — nothing to do (quiet no-op so launchd logs stay clean).
        return 0

    to_addr = os.environ.get("GATE_ALERT_EMAIL", DEFAULT_EMAIL).strip()
    do_mail = to_addr and not os.environ.get("GATE_ALERT_NO_MAIL")

    seen = 0
    for _ in range(MAX_DRAIN):
        raw = _rpop(base, token)
        if not raw:
            break
        seen += 1
        short, long = format_event(raw)
        notify("roadmodel: preview-gate auth attempt", short)
        if do_mail:
            send_mail(to_addr, "[roadmodel] Preview-gate auth attempt (locked out)", long)
    if seen:
        print(f"[gate-watcher] surfaced {seen} alert(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
