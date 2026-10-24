"""A roadmap's Settings ladder as Markdown, and the converter that brings
the tables older releases wrote to it.

The ladder is three short lists, Cost, Balanced and Quality, each ranking a
Pick, a Runner-up and a Backup, one option a line:

    **Balanced** — runs by default

    - Pick: **Gemini 4 Argon** · Antigravity · Effort High · Thinking On · AA 52.6
    - Runner-up: **Opus 5.5** · Claude Code · Effort High · AA 53.6
    - Backup: **GPT-6.1 Sol** · Codex · Intelligence XHigh · AA 51

The operator reads roadmaps in an editor's Markdown preview about 400–520px
wide. A table of three columns and one field a row (0.2.93) spread each option
over five rows, and a table with one option a row needs six columns, so it
wrapped every cell at that width. One option a line reads as a sentence and
wraps cleanly. A dial or toggle the surface lacks gets no field, as in a
selection block, and each line wraps at 80 columns on a field boundary, so
the source fits the roadmap's prose.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

TIERS: Final[tuple[str, ...]] = ("cost", "balanced", "quality")
# Each rank's label in the list and its key in a column.
RANKS: Final[tuple[tuple[str, str], ...]] = (
    ("Pick", "pick"),
    ("Runner-up", "runner_up"),
    ("Backup", "backup"),
)
WIDTH: Final[int] = 80
NONE: Final[str] = "—"
_SEP: Final[str] = " · "


@dataclass(frozen=True)
class Option:
    """One ranked option as the ladder prints it."""

    model: str
    platform: str
    # The dial and level (`Effort High`, `Intelligence XHigh`), or — where the
    # surface has no reasoning dial.
    effort: str = NONE
    # `On` where the surface has a Thinking toggle for the model, else —.
    thinking: str = NONE
    # The AA Index there (`52.6`, `not measured`); None in a ladder written
    # before it carried one.
    aa: str | None = None


def option_line(rank: str, option: Option | None, width: int = WIDTH) -> str:
    """``option`` as a list item, wrapped at ``width`` between fields:
    ``- Pick: **Opus 5.5** · Claude Code · Effort XHigh · AA 56``. A rank with
    no option reads ``- Backup: none``."""
    if option is None:
        return f"- {rank}: none"
    fields = [f"{rank}: **{option.model}**", option.platform]
    if option.effort != NONE:
        fields.append(option.effort)
    if option.thinking != NONE:
        fields.append(f"Thinking {option.thinking}")
    if option.aa is not None:
        fields.append(f"AA {option.aa}")
    lines = [f"- {fields[0]}"]
    for field in fields[1:]:
        if len(lines[-1]) + len(_SEP) + len(field) <= width:
            lines[-1] += _SEP + field
        else:
            lines.append(f"  · {field}")
    return "\n".join(lines)


def ladder_markdown(
    columns: Mapping[str, Mapping[str, Option | None]],
    *,
    runs: str | None,
    conversation: str | None,
) -> str:
    """The ladder's lists, then its Conversation line: each tier's bold name
    (the column ``runs`` names marked `runs by default`) over a line per rank
    it carries. A rank missing from a column is left out (a ladder older than
    the Runner-up has none); one present as None reads ``none``."""
    blocks = []
    for tier in TIERS:
        col = columns[tier]
        head = f"**{tier.capitalize()}**" + (" — runs by default" if tier == runs else "")
        items = [option_line(label, col[key]) for label, key in RANKS if key in col]
        blocks.append(head + "\n\n" + "\n".join(items))
    if conversation:
        blocks.append(f"**Conversation:** {conversation}")
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Converting the tables older releases wrote
# --------------------------------------------------------------------------- #

_HEAD_RE: Final = re.compile(
    r"^\|\s*(Rank|Setting)\s*\|\s*Cost\s*\|\s*Balanced\s*\|\s*Quality\s*\|\s*$"
)
_RULE_RE: Final = re.compile(r"^\|[\s:|-]+\|\s*$")
_RUNS_RE: Final = re.compile(r"^\*\*Runs:\*\* (Cost|Balanced|Quality)\b")
# The ranked table's (0.2.93) rank rows and the field rows under each.
_RANK_ROWS: Final[dict[str, str]] = {
    "1 · Pick": "pick",
    "2 · Runner-up": "runner_up",
    "3 · Backup": "backup",
}
_FIELD_ROWS: Final[frozenset[str]] = frozenset({"Platform", "Effort", "Thinking", "AA Index"})
# The single-pick ladder's (0.2.86–0.2.92) rows.
_PICK_ROWS: Final[frozenset[str]] = frozenset(
    {"Model", "Backup", "Backup on", "Backup effort", *_FIELD_ROWS, "Conversation"}
)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _option(fields: Mapping[str, str], model: str) -> Option | None:
    if model == "None":
        return None
    return Option(
        model=model,
        platform=fields.get("Platform", NONE),
        effort=fields.get("Effort", NONE),
        thinking=fields.get("Thinking", NONE),
        aa=fields.get("AA Index"),
    )


def _one_cell_backup(cell: str) -> Option | None:
    """A backup written in one cell: ``GPT-6.1 Sol — Codex · Intelligence
    Medium``, ``Model — Platform`` where the surface has no dial, or None."""
    if cell == "None":
        return None
    model, _, rest = cell.partition(" — ")
    platform, _, effort = rest.partition(_SEP)
    return Option(model=model, platform=platform or NONE, effort=effort or NONE)


def _ranked_columns(rows: list[list[str]]) -> dict[str, dict[str, Option | None]] | None:
    per: dict[str, list[tuple[str, dict[str, str]]]] = {t: [] for t in TIERS}
    rank = ""
    for label, *cells in rows:
        if label in _RANK_ROWS:
            rank = _RANK_ROWS[label]
            for tier, model in zip(TIERS, cells, strict=True):
                per[tier].append((rank, {"model": model}))
        elif label in _FIELD_ROWS and rank:
            for tier, cell in zip(TIERS, cells, strict=True):
                per[tier][-1][1][label] = cell
        elif label != "Conversation":
            return None
    return {
        tier: {key: _option(fields, fields["model"]) for key, fields in opts}
        for tier, opts in per.items()
    }


def _pick_columns(rows: list[list[str]]) -> dict[str, dict[str, Option | None]] | None:
    if any(label not in _PICK_ROWS for label, *_ in rows):
        return None
    by = {label: cells for label, *cells in rows}
    if "Model" not in by:
        return None
    out: dict[str, dict[str, Option | None]] = {}
    for i, tier in enumerate(TIERS):
        fields = {label: cells[i] for label, cells in by.items()}
        col: dict[str, Option | None] = {"pick": _option(fields, fields["Model"])}
        if "Backup on" in by:
            col["backup"] = _option(
                {
                    "Platform": fields["Backup on"],
                    "Effort": fields.get("Backup effort", NONE),
                },
                fields["Backup"],
            )
        elif "Backup" in by:
            col["backup"] = _one_cell_backup(fields["Backup"])
        out[tier] = col
    return out


def _conversation(rows: list[list[str]]) -> str | None:
    cells = next((cells for label, *cells in rows if label == "Conversation"), None)
    if cells is None:
        return None
    plain = [c.replace("**", "").strip() for c in cells]
    if len(set(plain)) == 1:
        return plain[0]
    return ", ".join(f"{t.capitalize()} {c}" for t, c in zip(TIERS, plain, strict=True))


def relayout(text: str) -> tuple[str, int]:
    """``text`` with every Settings ladder table (Cost / Balanced / Quality
    columns, as roadmodel 0.2.86–0.2.93 wrote them) rewritten as the ladder's
    lists, every value kept as written; and how many it rewrote. A table
    with a row it does not know is left as it is."""
    lines = text.split("\n")
    out: list[str] = []
    converted = 0
    i = 0
    while i < len(lines):
        head = _HEAD_RE.match(lines[i])
        if not head or i + 1 >= len(lines) or not _RULE_RE.match(lines[i + 1]):
            out.append(lines[i])
            i += 1
            continue
        end = i + 2
        while end < len(lines) and lines[end].startswith("|"):
            end += 1
        rows = [_cells(ln) for ln in lines[i + 2 : end]]
        columns = None
        if rows and all(len(r) == 1 + len(TIERS) for r in rows):
            parse = _ranked_columns if head.group(1) == "Rank" else _pick_columns
            columns = parse(rows)
        if columns is None:
            out.extend(lines[i:end])
            i = end
            continue
        after = next((ln for ln in lines[end:] if ln.strip()), "")
        runs = _RUNS_RE.match(after)
        md = ladder_markdown(
            columns,
            runs=runs.group(1).lower() if runs else None,
            conversation=_conversation(rows),
        )
        if out and out[-1].strip():
            out.append("")
        out.extend(md.split("\n"))
        if end < len(lines) and lines[end].strip():
            out.append("")
        converted += 1
        i = end
    return "\n".join(out), converted
