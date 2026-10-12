"""Real-updater guard regressions using disposable synthetic Git metadata.

No network, clone, pull or push is performed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

EXPECTED = "fixture-owner/private-context"
PRIVATE_BODY = {"id": 1001, "private": True, "visibility": "private", "full_name": EXPECTED}
SOURCE = b"# Synthetic private fixture\nNo account, provider, credential or live identity.\n"
ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "scripts/update_projects.py"
REAL_RUN = subprocess.run


class GuardFixture:
    def __init__(self, temporary: Path):
        self.root = temporary
        self.clone = temporary / "clone"
        self.source = temporary / "source.md"
        self.source.write_bytes(SOURCE)
        self.config = temporary / "config"
        self.config.mkdir(mode=0o700)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            GIT_CONFIG_COUNT="0",
        )
        self.local_git("init", "--quiet", "--initial-branch=main", str(self.clone), cwd=self.root)
        self.local_git("config", "remote.origin.url", "https://github.com/" + EXPECTED + ".git")
        self.events = []
        self.transports = []
        self.diagnostics = ""
        self.refusal_class = None
        self.clone_failure = False
        self.responses = [PRIVATE_BODY]
        self.gh_calls = 0
        self.after_commit = None
        self.have_gh = True
        self.module = types.ModuleType("_audit_context_updater")
        self.module.__file__ = str(UPDATER)
        sys.modules[self.module.__name__] = self.module
        exec(compile(UPDATER.read_bytes(), str(UPDATER), "exec"), self.module.__dict__)  # noqa: S102
        self.module.CONFIG_DIR = self.config
        self.module.CONTEXT_SYNC_CONFIG = self.config / "context-sync.json"
        self.module.CONTEXT_CLONE = self.clone
        self.module.USER_CONTEXT = self.config / "user-context.md"
        self.write_config(EXPECTED)

    def local_git(self, *args, cwd=None):
        # Only these local, non-network Git metadata commands can execute.
        if args[0] not in {
            "init",
            "config",
            "remote",
            "rev-parse",
            "symbolic-ref",
            "check-ref-format",
        }:
            raise AssertionError("Forbidden real Git command in fixture")
        if args[0] == "remote" and len(args) > 1 and args[1] not in {"get-url", "-v"}:
            raise AssertionError("Forbidden remote mutation command")
        return REAL_RUN(
            ["git", *args],
            cwd=cwd or self.clone,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def write_config(self, repo, role="source"):
        (self.config / "context-sync.json").write_text(
            json.dumps({"repo": repo, "role": role, "source": str(self.source)})
        )

    def run(self, argv, *args, **kwargs):
        if not isinstance(argv, (list, tuple)) or args:
            raise AssertionError("Unexpected subprocess contract")
        executable = Path(argv[0]).name
        command = list(argv[1:])
        if executable in {"gh", "gh.exe"}:
            if command[:2] == ["repo", "clone"]:
                self.events.append("clone")
                return subprocess.CompletedProcess(
                    argv, 1 if self.clone_failure else 0, "", "SYNTHETIC_RAW_DIAGNOSTIC"
                )
            self.events.append("visibility_check")
            self.gh_calls += 1
            if not self.have_gh:
                raise FileNotFoundError("fixture gh unavailable")
            if (
                command[:1] != ["api"]
                or "--hostname" not in command
                or command[command.index("--hostname") + 1] != "github.com"
                or "repos/" + EXPECTED not in command
            ):
                raise AssertionError("Expected explicit-host exact-repository gh API request")
            value = self.responses[min(self.gh_calls - 1, len(self.responses) - 1)]
            if isinstance(value, Exception):
                raise value
            if isinstance(value, tuple):
                return subprocess.CompletedProcess(argv, value[0], value[1], "fixture API failure")
            return subprocess.CompletedProcess(
                argv, 0, value if isinstance(value, str) else json.dumps(value), ""
            )
        if executable not in {"git", "git.exe"}:
            raise AssertionError("Unexpected external process")
        # Allow standard per-command Git controls without executing unknown work.
        while command and command[0] in {"-c", "-C"}:
            command = command[2:]
        if not command:
            raise AssertionError("Missing Git command")
        operation = command[0]
        if operation in {"clone", "fetch", "pull", "push", "add", "commit"}:
            self.events.append(operation)
            self.transports.append(command)
            if operation == "commit" and self.after_commit:
                self.after_commit()
            # Deliberately never delegate transport/index mutations to real Git.
            return subprocess.CompletedProcess(argv, 0, "", "")
        self.events.append("git_metadata")
        if operation == "rev-parse" and "--verify" in command:
            return subprocess.CompletedProcess(argv, 0, "a" * 40 + "\n", "")
        return self.local_git(*command, cwd=kwargs.get("cwd", self.clone))

    def replace(self, path, data):
        path = Path(path)
        if not path.is_relative_to(self.root):
            raise AssertionError("Fixture write escaped")
        self.events.append("private_write")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def invoke(self, *, configure=None, dry=False):
        def directory(path):
            if not Path(path).is_relative_to(self.root):
                raise AssertionError("Fixture directory escaped")
            Path(path).mkdir(parents=True, exist_ok=True, mode=0o700)

        old_read_bytes, old_read_text = Path.read_bytes, Path.read_text

        def read_bytes(path):
            if path == self.source:
                self.events.append("source_read")
            return old_read_bytes(path)

        def read_text(path, *args, **kwargs):
            if path == self.source:
                self.events.append("source_read")
            return old_read_text(path, *args, **kwargs)

        captured_out, captured_err = io.StringIO(), io.StringIO()
        try:
            with (
                patch.object(subprocess, "run", self.run),
                patch.object(
                    self.module.shutil,
                    "which",
                    lambda name: name if self.have_gh or name != "gh" else None,
                ),
                patch.object(self.module, "_private_dir", directory),
                patch.object(self.module, "_replace_bytes", self.replace),
                patch.object(Path, "read_bytes", read_bytes),
                patch.object(Path, "read_text", read_text),
                contextlib.redirect_stdout(captured_out),
                contextlib.redirect_stderr(captured_err),
            ):
                if configure is not None:
                    returned = self.module.configure_context_sync(
                        configure, str(self.source), dry_run=dry
                    )
                    self.diagnostics += str(returned)
                else:
                    returned = self.module.sync_user_context(dry_run=dry)
                    self.diagnostics += str(returned)
        except (SystemExit, ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            self.refusal_class = type(error).__name__
            self.diagnostics += str(error)
        self.diagnostics += captured_out.getvalue() + captured_err.getvalue()


class PrivateContextGuard(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="context-guard-fixture-", dir=None)
        self.f = GuardFixture(Path(self.temporary.name))

    def tearDown(self):
        sys.modules.pop("_audit_context_updater", None)
        self.temporary.cleanup()

    def assert_refused_before_private_work(self):
        self.assertFalse(
            set(self.f.events)
            & {"clone", "pull", "fetch", "source_read", "private_write", "add", "commit", "push"},
            "Guard must refuse before transport or private work",
        )

    def assert_explicit_origin_transports(self):
        for argv in self.f.transports:
            if argv[0] == "pull":
                self.assertIn("origin", argv)
                self.assertIn("main", argv)
            if argv[0] == "push":
                self.assertIn("origin", argv)
                self.assertIn("HEAD:refs/heads/main", argv)

    def test_private_source_success(self):
        self.f.invoke()
        self.assertEqual((self.f.clone / "user-context.md").read_bytes(), SOURCE)
        self.assertEqual(self.f.events.count("push"), 1)
        self.assert_explicit_origin_transports()
        self.assertGreaterEqual(self.f.gh_calls, 2)
        self.assertLess(self.f.events.index("visibility_check"), self.f.events.index("source_read"))

    def test_second_visibility_flip_stops_push(self):
        self.f.responses = [
            PRIVATE_BODY,
            {**PRIVATE_BODY, "private": False, "visibility": "public"},
        ]
        self.f.invoke()
        self.assertNotIn("push", self.f.events)
        self.assertGreaterEqual(self.f.gh_calls, 2)

    def test_second_remote_flip_stops_push(self):
        self.f.after_commit = lambda: self.f.local_git(
            "config", "remote.origin.pushurl", "https://github.com/fixture-other/public-context.git"
        )
        self.f.invoke()
        self.assertNotIn("push", self.f.events)

    def test_missing_gh_refuses(self):
        self.f.have_gh = False
        self.f.invoke()
        self.assert_refused_before_private_work()

    def test_dry_run_has_no_visibility_or_private_work(self):
        self.f.invoke(dry=True)
        self.assertEqual(self.f.gh_calls, 0)
        self.assert_refused_before_private_work()
        self.assertNotIn(EXPECTED, self.f.diagnostics)
        self.assertNotIn(str(self.f.source), self.f.diagnostics)

    def test_replica_guard_precedes_pull(self):
        self.f.write_config(EXPECTED, "replica")
        self.f.responses = [{**PRIVATE_BODY, "private": False, "visibility": "public"}]
        self.f.invoke()
        self.assert_refused_before_private_work()

    def test_configure_output_has_no_private_identity(self):
        self.f.invoke(configure=EXPECTED)
        self.assertNotIn(EXPECTED, self.f.diagnostics)
        self.assertNotIn(str(self.f.source), self.f.diagnostics)

    def test_failed_clone_output_is_fixed(self):
        (self.f.clone / ".git").rename(self.f.clone / "metadata-fixture")
        self.f.clone_failure = True
        self.f.invoke()
        self.assertNotIn("SYNTHETIC_RAW_DIAGNOSTIC", self.f.diagnostics)
        self.assertNotIn(EXPECTED, self.f.diagnostics)
        self.assertNotIn("source_read", self.f.events)

    def test_invalid_current_branch_refuses(self):
        self.f.local_git("symbolic-ref", "HEAD", "refs/heads/-invalid")
        self.f.invoke()
        self.assert_refused_before_private_work()


def add_case(name, callback):
    def case(self):
        callback(self)

    case.__name__ = "test_" + name
    setattr(PrivateContextGuard, case.__name__, case)


BAD_REPOS = [
    "fixture-owner/../private-context",
    "./private-context",
    "/fixture/local.git",
    "file:///fixture/local.git",
    "https://example.invalid/fixture-owner/private-context",
    "http://github.com/" + EXPECTED,
    "https://github.com.evil.invalid/" + EXPECTED,
    "https://credential:canary" + "@github.com/" + EXPECTED,
    "https://github.com:443/" + EXPECTED,
    "https://github.com/" + EXPECTED + "?query=1",
    "https://github.com/" + EXPECTED + "#fragment",
    "ssh://other" + "@github.com/" + EXPECTED,
    "git" + "@elsewhere.invalid:" + EXPECTED,
    "https://github.com/fixture-owner%2Fprivate-context",
    "fixture-owner/..",
    "-fixture/private-context",
]
for index, repo in enumerate(BAD_REPOS):

    def bad(self, repo=repo):
        self.f.invoke(configure=repo)
        self.assertNotIn("private_write", self.f.events)
        self.assertNotIn(repo, self.f.diagnostics)

    add_case("reject_input_" + str(index), bad)

GOOD_REPOS = [
    EXPECTED,
    "https://github.com/" + EXPECTED + ".git",
    "git" + "@github.com:" + EXPECTED + ".git",
    "ssh://git" + "@github.com/" + EXPECTED + ".git",
]
for index, repo in enumerate(GOOD_REPOS):

    def good(self, repo=repo):
        self.f.invoke(configure=repo)
        self.assertIsNone(self.f.refusal_class)
        self.assertIn("private_write", self.f.events)
        cfg = json.loads((self.f.config / "context-sync.json").read_text())
        self.assertEqual(cfg["repo"], EXPECTED)

    add_case("canonical_input_" + str(index), good)

BAD_RESPONSES = [
    {**PRIVATE_BODY, "private": False, "visibility": "public"},
    {**PRIVATE_BODY, "visibility": "internal"},
    {**PRIVATE_BODY, "private": "true"},
    {**PRIVATE_BODY, "private": 1},
    {k: v for k, v in PRIVATE_BODY.items() if k != "private"},
    {**PRIVATE_BODY, "visibility": "PRIVATE"},
    {k: v for k, v in PRIVATE_BODY.items() if k != "visibility"},
    {**PRIVATE_BODY, "full_name": "fixture-other/private-context"},
    {k: v for k, v in PRIVATE_BODY.items() if k != "full_name"},
    {"data": PRIVATE_BODY},
    "malformed JSON",
    [],
    (1, ""),
    subprocess.TimeoutExpired(["fixture-gh"], 1),
]
for index, body in enumerate(BAD_RESPONSES):

    def bad_api(self, body=body):
        self.f.responses = [body]
        self.f.invoke()
        self.assert_refused_before_private_work()

    add_case("reject_api_contract_" + str(index), bad_api)

REMOTE_CASES = [
    [("remote.origin.url", "https://github.com/fixture-other/public-context.git")],
    [("remote.origin.pushurl", "https://github.com/fixture-other/public-context.git")],
    [("remote.origin.url", "https://github.com/" + EXPECTED + ".git", True)],
    [
        ("remote.origin.pushurl", "https://github.com/" + EXPECTED + ".git"),
        ("remote.origin.pushurl", "https://github.com/fixture-other/public-context.git", True),
    ],
    [("url.https://github.com/fixture-other/.insteadOf", "https://github.com/fixture-owner/")],
    [("url.https://github.com/fixture-other/.pushInsteadOf", "https://github.com/fixture-owner/")],
    [
        ("remote.other.url", "https://github.com/fixture-other/public-context.git"),
        ("branch.main.remote", "other"),
        ("branch.main.merge", "refs/heads/main"),
    ],
    [
        ("remote.other.url", "https://github.com/fixture-other/public-context.git"),
        ("remote.pushDefault", "other"),
    ],
]
for index, settings in enumerate(REMOTE_CASES):

    def bad_remote(self, settings=settings, index=index):
        for item in settings:
            argv = ["config"] + (["--add"] if len(item) > 2 else []) + list(item[:2])
            self.assertEqual(self.f.local_git(*argv).returncode, 0)
        if index < 6:
            fetch = self.f.local_git("remote", "get-url", "--all", "origin")
            push = self.f.local_git("remote", "get-url", "--push", "--all", "origin")
            self.assertEqual(fetch.returncode, 0)
            self.assertEqual(push.returncode, 0)
            approved = ["https://github.com/" + EXPECTED + ".git"]
            self.assertTrue(
                fetch.stdout.splitlines() != approved or push.stdout.splitlines() != approved
            )
        self.f.invoke()
        if index >= 6 and "push" in self.f.events:
            # Extra remotes are safe only if explicit transport bypasses them.
            self.assert_explicit_origin_transports()
            self.assertGreaterEqual(self.f.gh_calls, 2)
        else:
            self.assert_refused_before_private_work()

    add_case("reject_effective_remote_" + str(index), bad_remote)
