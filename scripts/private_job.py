#!/usr/bin/env python3
"""Run one fixed local job after opening its private append log."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_private import private_files

JOBS = {
    "gate": ("gate-alert-watcher.py", ()),
    "pools": ("roll_pool_status.py", ("--sync-web",)),
}


def run_job(job: str, directory: Path | None = None) -> int:
    if job not in JOBS:
        return 64
    script, arguments = JOBS[job]
    root = directory if directory is not None else Path.home() / ".cache/roadmodel/job-logs"
    try:
        private = private_files()
        private.private_directory(root)
        with private.open_private_append(root / f"{job}.log") as output:
            result = subprocess.run(  # noqa: S603 — fixed, allowlisted checkout jobs
                [
                    sys.executable,
                    "-I",
                    "-X",
                    "utf8",
                    str(Path(__file__).with_name(script)),
                    *arguments,
                ],
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
            )
        return result.returncode
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Local job could not open its private log or start safely.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_job(sys.argv[1]) if len(sys.argv) == 2 else 64)
