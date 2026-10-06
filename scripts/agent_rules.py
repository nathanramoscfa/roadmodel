"""Maintain live global instruction adapters without copying private rules.

This module is fetched with ``update_projects.py`` and uses only Python 3.9's
standard library.  Claude's existing global instructions remain authoritative;
client files retain their own content outside the marked adapter block.

The adapters instruct agents to read live sources.  Only Antigravity provides
native inline inclusion here; installing these files does not prove that an
already running client has loaded their contents.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

START = "<!-- roadmodel:global-context:start -->"
END = "<!-- roadmodel:global-context:end -->"
SOURCE_REL = Path(".claude") / "CLAUDE.md"


def _read(path: Path) -> str:
    # read_text translates CRLF; retain all user-owned bytes outside our block.
    return path.read_bytes().decode("utf-8")


def _adapter(agent: str) -> str:
    include = "\n@[Shared global rules](~/.claude/CLAUDE.md)\n" if agent == "antigravity" else ""
    return f"""{START}
## Shared rules and project memory

The authoritative global rules are `~/.claude/CLAUDE.md`. Read that live file
at the start of every session before doing project work. Follow its explicit
file imports, resolving relative paths against the importing file and stopping
cycles. Preserve the scope of imported instructions. A file reference here is
an instruction to read the file; it is not evidence that it was already loaded.
{include}
Also enumerate Markdown rules recursively under `~/.claude/rules/` if it
exists. Inspect each rule's frontmatter: unscoped rules apply globally; rules
with `paths` apply only when working on matching project-relative paths. Read
the full body of applicable rules before editing those paths. Do not flatten
scoped rules into unconditional instructions or bypass the client's permissions.

At project entry, read `.agents/shared-context.md` when present and follow
its instructions for original project rules, scoped Claude rules, and all
memory entries, including imported worktree memories absent from the index.
If `.roadmodel/context.py` exists, run
`python .roadmodel/context.py --session` from the repository root (use `python3`
or `py -3` if needed). This local freshness check calls no model or network.
Report a failed check before relying on the saved context.
Read `.roadmodel/context.json` if present, then the live
`MEMORY.md` index at the memory location it identifies and every linked memory
entry relevant to the task. Read `.roadmodel/HANDOFF.md` for the current objective,
branch, unfinished work, verification results, and next steps. Check the actual
Git state before relying on a handoff. For projects with the older export only,
read `.agents/memory.md`. Use an allowed shell read when a file tool excludes
these Git-ignored files; report access failures rather than silently skipping.

Before each new user task and after compaction, recheck the rules, memory index,
and handoff for changes and read changed applicable content. Record durable
decisions in the shared memory location and keep its index current. Update
`.roadmodel/HANDOFF.md` before ending or switching agents, preserving other ongoing
work and distinguishing completed checks from pending work. Keep private memory
and handoffs out of Git commits. Never store secrets or credentials in memory.

If a source is missing or unreadable, report the exact path and the resulting
context gap. Report which instruction and memory sources you actually read at
the first useful progress update; do not claim a file was loaded merely because
this adapter exists. Client permissions and higher-priority instructions remain
in force. Put shared global rule edits in `~/.claude/CLAUDE.md`; keep only
client-specific guidance outside this managed block.
{END}"""


def _replace_block(text: str, block: str) -> str:
    """Replace exactly one complete block, refusing ambiguous manual damage."""
    starts, ends = text.count(START), text.count(END)
    if not starts and not ends:
        return block + ("\n\n" + text if text else "\n")
    if starts != 1 or ends != 1 or text.index(START) > text.index(END):
        raise ValueError("damaged or duplicate roadmodel global-context markers")
    begin, end = text.index(START), text.index(END) + len(END)
    return text[:begin] + block + text[end:]


def _atomic_write(path: Path, text: str) -> None:
    """Replace the adapter atomically, preserving mode and non-adapter text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _backup_duplicate(path: Path, original: str) -> Path:
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]
    backup = path.with_name(f"{path.name}.roadmodel-backup-{digest}")
    if backup.exists():
        if _read(backup) != original:
            raise ValueError(f"existing backup differs: {backup}")
    else:
        # Exclusive creation never overwrites an older backup.
        with backup.open("xb") as stream:
            stream.write(original.encode("utf-8"))
        backup.chmod(stat.S_IMODE(path.stat().st_mode))
    return backup


def _targets(home: Path, agents: list[str]) -> list[tuple[str, Path]]:
    targets = []
    if "codex" in agents:
        override = home / ".codex" / "AGENTS.override.md"
        # Codex uses the first nonempty file, including an existing override.
        # An unreadable override must be reported, not silently bypassed.
        codex = (
            override
            if override.exists() and override.stat().st_size
            else (home / ".codex" / "AGENTS.md")
        )
        targets.append(("codex", codex))
    if "antigravity" in agents or "gemini" in agents:
        agent = "antigravity" if "antigravity" in agents else "gemini"
        targets.append((agent, home / ".gemini" / "GEMINI.md"))
    if "opencode" in agents:
        targets.append(("opencode", home / ".config" / "opencode" / "AGENTS.md"))
    return targets


def sync_global_rules(
    home: Path,
    agents: list[str],
    dry_run: bool = False,
    check: bool = False,
) -> tuple[list[str], bool]:
    """Install/check global adapters and return report lines plus success.

    ``check`` and ``dry_run`` never write files. Check returns false for drift;
    dry-run accepts planned changes but still reports missing/unreadable sources.
    A missing source is not fabricated: adapters can already point at its future
    location so adding the Claude file later requires no generated snapshot.
    """
    home = Path(home)
    source = home / SOURCE_REL
    report: list[str] = []
    healthy = True
    source_text = None
    try:
        source_text = _read(source)
        report.append(f"global rules: live source {source}")
    except (OSError, UnicodeError) as exc:
        report.append(f"global rules: FAILED to read {source}: {exc}")
        healthy = False

    rules = home / ".claude" / "rules"
    try:
        files = sorted(rules.rglob("*.md")) if rules.exists() else []
        for path in files:
            _read(path)
        report.append(f"global rules: {len(files)} modular rule(s); path scopes retained")
    except (OSError, UnicodeError) as exc:
        report.append(f"global rules: FAILED to read modular rules: {exc}")
        healthy = False

    try:
        targets = _targets(home, agents)
    except OSError as exc:
        return report + [f"global rules: FAILED to resolve client files: {exc}"], False
    for agent, path in targets:
        try:
            # Never write through a symlink into the authoritative source or
            # another user's managed file. A direct link already loads live
            # global rules; per-project adapters provide the memory protocol.
            if path.is_symlink():
                if source_text is not None and path.resolve() == source.resolve():
                    report.append(f"{agent} global rules: live source symlink {path}")
                    continue
                raise ValueError(f"symlink target is not the canonical source: {path}")
            original = _read(path) if path.exists() else ""
            duplicate = (
                source_text is not None
                and bool(source_text.strip())
                and original.strip() == source_text.strip()
                and START not in original
            )
            updated = _replace_block("" if duplicate else original, _adapter(agent))
            if updated == original:
                report.append(f"{agent} global rules: current ({path})")
                continue
            if check:
                report.append(f"{agent} global rules: DRIFT ({path})")
                healthy = False
                continue
            if dry_run:
                action = (
                    "replace duplicate with backed-up live adapter"
                    if duplicate
                    else ("update managed adapter")
                )
                report.append(f"{agent} global rules: would {action} ({path})")
                continue
            if duplicate:
                backup = _backup_duplicate(path, original)
                report.append(f"{agent} global rules: preserved duplicate in {backup}")
            _atomic_write(path, updated)
            report.append(f"{agent} global rules: updated live adapter ({path})")
        except (OSError, UnicodeError, ValueError) as exc:
            report.append(f"{agent} global rules: FAILED ({path}): {exc}")
            healthy = False

    if "claude" in agents:
        report.append("claude global rules: native source retained without modification")
    for agent in sorted(set(agents) - {"claude", "codex", "antigravity", "gemini", "opencode"}):
        report.append(f"{agent} global rules: no global adapter; use project instructions")
    if targets:
        report.append(
            "global rules: file checks only; verify loaded sources in a fresh client session"
        )
    return report, healthy
