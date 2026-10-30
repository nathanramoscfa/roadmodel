"""A roadmap's Settings ladder as Markdown, and the converter that brings
the ladders older releases wrote to it.

The ladder is one table: Cost, Balanced and Quality are its columns, and each
rank (Pick, Runner-up, Backup) names the first of its field rows from a column
of its own, so the field names stand indented beside it:

    |          |          | Cost            | Balanced           | Quality      |
    | -------- | -------- | --------------- | ------------------ | ------------ |
    | **Pick** | Model    | **GPT-6.1 Sol** | **Gemini 4 Argon** | **Opus 5.5** |
    |          | Platform | Codex           | Antigravity        | Claude Code  |
    |          | Level    | High            | High               | XHigh        |
    |          | AA       | 50.2            | 52.6               | 56           |
    |          | Price    | $2.18/1M        | $4.00/1M*          | $8.46/1M     |

The operator chose the table on 2026-10-24 after reading candidates in an
editor's Markdown preview 400–520px wide: 0.2.93's table gave each field a row
with nothing marking where an option ended, and 0.2.94's lists dropped the
table. 0.2.95–0.2.97 put each rank on a row of its own over fields indented
with `&nbsp;`, which some viewers draw as a highlighted blob; ordinary cells
indent the same in every viewer (2026-10-25). Level is the bare level (the
platform names its dial: Codex's
Intelligence, Claude Code's and Antigravity's Effort), and Thinking has no row:
a ladder only ever recommends it On, and every AA Index and price already
assumes it, so /roadmap-step states the rule once instead. Since 2026-10-29
the ladder names no column to run (its Runs paragraph is gone): the operator
picks the option, and a pool's state never steers it.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

TIERS: Final[tuple[str, ...]] = ("cost", "balanced", "quality")
# Each rank's group label and its key in a column. The label's hyphen is
# U+2011, which does not break, so "Runner-up" stays on one line at 400px.
RANKS: Final[tuple[tuple[str, str], ...]] = (
    ("Pick", "pick"),
    ("Runner‑up", "runner_up"),
    ("Backup", "backup"),
)
FIELDS: Final[tuple[str, ...]] = ("Model", "Platform", "Level", "AA", "Price")
RUNS_MARK: Final[str] = "✓"
STEP_MARK: Final[str] = "↓"
# A figure estimated from the model's measured levels, not measured at this one.
ESTIMATE_MARK: Final[str] = "≈"
WIDTH: Final[int] = 80
NONE: Final[str] = "—"
_SEP: Final[str] = " · "
# Level words as a dial names them, by the scorer's level.
LEVEL_WORDS: Final[dict[str, str]] = {
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "XHigh",
    "max": "Max",
    "ultra": "Ultra",
}
_LEVEL_KEYS: Final[dict[str, str]] = {
    **{word.lower(): key for key, word in LEVEL_WORDS.items()},
    "extra high": "xhigh",
}
_DIALS: Final[tuple[str, ...]] = ("Intelligence ", "Effort ")

# Prices a model at a level: (USD per 1M blended tokens at that level's token
# use, whether that use was measured); None when the model is unknown.
PriceFn = Callable[[str, str], tuple[float, bool] | None]


@dataclass(frozen=True)
class Option:
    """One ranked option as the ladder prints it."""

    model: str
    platform: str
    # The bare level (`High`, `XHigh`), or — where the surface has no dial.
    level: str = NONE
    # The AA Index there (`52.6`, `≈51.4` estimated, `not measured` in an
    # older ladder); None in a ladder written before it carried one.
    aa: str | None = None
    # USD per 1M blended tokens at the level's token use; None when unknown.
    price: float | None = None
    # False when the level's token use is estimated, not measured.
    price_measured: bool = True
    # The Pick's own model a level or two lower, filling a rank no other
    # maker could (marked ↓).
    stepped_down: bool = False


def level_key(word: str) -> str | None:
    """The scorer's level a level word names (`XHigh` → `xhigh`)."""
    return _LEVEL_KEYS.get(word.strip().lower())


def price_cell(option: Option) -> str:
    if option.price is None:
        return NONE
    return ("" if option.price_measured else ESTIMATE_MARK) + f"${option.price:.2f}/1M"


def _cells(option: Option | None) -> list[str]:
    if option is None:
        return ["none", NONE, NONE, NONE, NONE]
    return [
        f"**{option.model}**",
        option.platform,
        option.level + (f" {STEP_MARK}" if option.stepped_down else ""),
        NONE if option.aa is None else option.aa,
        price_cell(option),
    ]


def _grid(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)) + " |"

    return [line(rows[0]), "| " + " | ".join("-" * w for w in widths) + " |", *map(line, rows[1:])]


def ladder_markdown(
    columns: Mapping[str, Mapping[str, Option | None]],
    *,
    conversation: str | None,
    ranked_for: str | None = None,
) -> str:
    """The ladder's table, its note, then its Conversation line. A rank is
    printed when any column carries it (a ladder older than the Runner-up has
    none), and a field row only when some option of that rank has a value
    there (an older backup has no AA Index; a rank with no option in any
    column reads `none` alone)."""
    head = ["", "", *(t.capitalize() for t in TIERS)]
    rows = [head]
    priced = unmeasured = stepped = False
    for label, key in RANKS:
        if not any(key in columns[t] for t in TIERS):
            continue
        opts = [columns[t].get(key) for t in TIERS]
        cells = [_cells(o) for o in opts]
        rank_cell = f"**{label}**"
        for i, field in enumerate(FIELDS):
            values = [c[i] for c in cells]
            if field != "Model" and all(v == NONE for v in values):
                continue
            # The rank names its first row only; the empty cells under it read
            # as one merged cell, and its field names stand indented beside it.
            rows.append([rank_cell, field, *values])
            rank_cell = ""
        priced |= any(o is not None and o.price is not None for o in opts)
        unmeasured |= any(
            o is not None
            and (
                (o.price is not None and not o.price_measured)
                or (o.aa or "").startswith(ESTIMATE_MARK)
            )
            for o in opts
        )
        stepped |= any(o is not None and o.stepped_down for o in opts)
    notes = [f"Ranked for {ranked_for}."] if ranked_for else []
    if stepped:
        notes.append(f"{STEP_MARK} the Pick one level lower: no other maker is funded.")
    if priced:
        notes.append(
            "Price: list $ per 1M tokens (3 in : 1 out), the output part scaled by "
            "the tokens the model writes at that level."
        )
    if unmeasured:
        notes.append(f"{ESTIMATE_MARK} estimated from the model's measured levels.")
    parts = ["\n".join(_grid(rows))]
    if notes:
        parts.append(textwrap.fill(" ".join(notes), width=WIDTH, break_long_words=False))
    if conversation:
        parts.append(f"**Conversation:** {conversation}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Converting the ladders older releases wrote
# --------------------------------------------------------------------------- #

_HEAD_RE: Final = re.compile(
    r"^\|\s*(Rank|Setting)\s*\|\s*Cost\s*\|\s*Balanced\s*\|\s*Quality\s*\|\s*$"
)
_RULE_RE: Final = re.compile(r"^\|[\s:|-]+\|\s*$")
_RUNS_RE: Final = re.compile(r"^\*\*Runs:\*\* (Cost|Balanced|Quality)\b")
_TIER_HEAD_RE: Final = re.compile(r"^\*\*(Cost|Balanced|Quality)\*\*( — runs by default)?\s*$")
_ITEM_RE: Final = re.compile(r"^- (Pick|Runner-up|Backup): (.*)$")
_CONVERSATION_RE: Final = re.compile(r"^\*\*Conversation:\*\* (.+?)\s*$")
_STEP_RE: Final = re.compile(r"^## Step\b")
_PHASE_RE: Final = re.compile(r"^### Phase\s+([0-9A-Za-z.]+)")
_STATUS_RE: Final = re.compile(r"^\*\*Status:\*\*\s*(.*)$")
# The ranked table's (0.2.93) rank rows and the field rows under each.
_RANK_ROWS: Final[dict[str, str]] = {
    "1 · Pick": "pick",
    "2 · Runner-up": "runner_up",
    "3 · Backup": "backup",
}
_LIST_RANKS: Final[dict[str, str]] = {"Pick": "pick", "Runner-up": "runner_up", "Backup": "backup"}
_FIELD_ROWS: Final[frozenset[str]] = frozenset({"Platform", "Effort", "Thinking", "AA Index"})
# The single-pick ladder's (0.2.86–0.2.92) rows.
_PICK_ROWS: Final[frozenset[str]] = frozenset(
    {"Model", "Backup", "Backup on", "Backup effort", *_FIELD_ROWS, "Conversation"}
)


def _level_word(effort: str) -> str:
    """The bare level of an Effort cell (`Intelligence High` → `High`)."""
    effort = effort.strip()
    for dial in _DIALS:
        if effort.startswith(dial):
            return effort[len(dial) :].strip()
    return effort or NONE


def _priced(option: Option, price: PriceFn | None) -> Option:
    found = None if price is None else price(option.model, option.level)
    if found is None:
        return option
    value, measured = found
    return Option(option.model, option.platform, option.level, option.aa, value, measured)


def _option(fields: Mapping[str, str], model: str) -> Option | None:
    if model in {"None", "none"}:
        return None
    return Option(
        model=model.strip("*"),
        platform=fields.get("Platform", NONE),
        level=_level_word(fields.get("Effort", NONE)),
        aa=fields.get("AA Index"),
    )


def _one_cell_backup(cell: str) -> Option | None:
    """A backup written in one cell: ``GPT-6.1 Sol — Codex · Intelligence
    Medium``, ``Model — Platform`` where the surface has no dial, or None."""
    if cell == "None":
        return None
    model, _, rest = cell.partition(" — ")
    platform, _, effort = rest.partition(_SEP)
    return Option(model=model, platform=platform or NONE, level=_level_word(effort or NONE))


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


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
                {"Platform": fields["Backup on"], "Effort": fields.get("Backup effort", NONE)},
                fields["Backup"],
            )
        elif "Backup" in by:
            col["backup"] = _one_cell_backup(fields["Backup"])
        out[tier] = col
    return out


def _table_conversation(rows: list[list[str]]) -> str | None:
    cells = next((cells for label, *cells in rows if label == "Conversation"), None)
    if cells is None:
        return None
    plain = [c.replace("**", "").strip() for c in cells]
    if len(set(plain)) == 1:
        return plain[0]
    return ", ".join(f"{t.capitalize()} {c}" for t, c in zip(TIERS, plain, strict=True))


def _list_option(rest: str) -> Option | None:
    """A 0.2.94 list item's option: ``**Model** · Platform · Effort High ·
    Thinking On · AA 52.6``, or ``none``."""
    if rest.strip() == "none":
        return None
    model, platform, *more = [f.strip() for f in rest.split(_SEP)]
    level, aa = NONE, None
    for field in more:
        if field.startswith("AA "):
            aa = field[3:]
        elif not field.startswith("Thinking "):
            level = _level_word(field)
    return Option(model=model.strip("*"), platform=platform, level=level, aa=aa)


def _list_ladder(
    lines: list[str], start: int
) -> tuple[int, dict[str, dict[str, Option | None]], str | None, str | None] | None:
    """The 0.2.94 lists starting at ``lines[start]`` (a `**Cost**` heading):
    the index past their last line, the columns, the column that runs and the
    Conversation value; None when the lines are not such a ladder."""
    columns: dict[str, dict[str, Option | None]] = {}
    runs = conversation = None
    tier = ""
    i = start
    while i < len(lines):
        line = lines[i]
        if head := _TIER_HEAD_RE.match(line):
            tier = head.group(1).lower()
            columns[tier] = {}
            if head.group(2):
                runs = tier
        elif (item := _ITEM_RE.match(line)) and tier:
            rest = item.group(2)
            while i + 1 < len(lines) and lines[i + 1].startswith("  · "):
                i += 1
                rest += _SEP + lines[i][4:]
            columns[tier][_LIST_RANKS[item.group(1)]] = _list_option(rest)
        elif conv := _CONVERSATION_RE.match(line):
            conversation = conv.group(1)
            i += 1
            break
        elif line.strip() and not _RUNS_RE.match(line):
            return None
        elif _RUNS_RE.match(line):
            break
        i += 1
    if set(columns) != set(TIERS):
        return None
    return i, columns, runs, conversation


# A ladder found by relayout: the index past it, its columns, its
# Conversation value, the classification its note names, and whether
# converting it is a display fix that reaches every section.
_Found = tuple[int, dict[str, dict[str, "Option | None"]], str | None, str | None, bool]
# The 0.2.95–0.2.98 table: one empty header cell before Cost (0.2.95–0.2.97)
# or two with a ✓ in the header or note (0.2.98).
_INDENT_HEAD_RE: Final = re.compile(r"^\|\s*\|(?:\s*\|)?\s*Cost\b")
# A price cell: `$2.18/1M`; estimated, `≈$7.75/1M` (before 0.2.107, `$7.75/1M*`).
_PRICE_RE: Final = re.compile(r"^(≈?)\$([0-9]+(?:\.[0-9]+)?)/1M(\*?)$")


def _indented_ladder(
    lines: list[str], start: int
) -> tuple[int, dict[str, dict[str, Option | None]], str | None, str | None] | None:
    """A 0.2.95–0.2.98 ladder table starting at ``lines[start]`` (rank rows
    over `&nbsp;`-indented fields, or a 0.2.98 table still carrying ✓): the
    index past its note and Conversation line (relayout handles a Runs
    paragraph after it), its columns with every cell read back, its
    Conversation value and the classification its note names; None when a row
    is not one those releases wrote or the table is already in the current
    layout."""
    head = _table_cells(lines[start])
    tier_cells = head[-len(TIERS) :]
    runs = next(
        (t for t, cell in zip(TIERS, tier_cells, strict=False) if cell.endswith(RUNS_MARK)), None
    )
    cells, j = _table_rows(lines, start + 2)
    keys = {label.replace("\u2011", "-"): key for label, key in RANKS}
    columns: dict[str, dict[str, Option | None]] = {t: {} for t in TIERS}
    for rank, fields in cells.items():
        key = keys.get(rank.replace("\u2011", "-"))
        if key is None or not set(fields) <= set(FIELDS) or "Model" not in fields:
            return None
        for i, tier in enumerate(TIERS):
            model = fields["Model"][i].strip("*")
            if model == "none":
                columns[tier][key] = None
                continue
            level = fields.get("Level", [NONE] * len(TIERS))[i]
            price = _PRICE_RE.match(fields.get("Price", [NONE] * len(TIERS))[i])
            aa = fields.get("AA", [NONE] * len(TIERS))[i]
            columns[tier][key] = Option(
                model=model,
                platform=fields.get("Platform", [NONE] * len(TIERS))[i],
                level=level.replace(f" {STEP_MARK}", ""),
                aa=None if aa == NONE else aa,
                price=float(price.group(2)) if price else None,
                price_measured=not (price and (price.group(1) or price.group(3))),
                stepped_down=level.endswith(f" {STEP_MARK}"),
            )
    end = j
    k = _skip_blank(lines, j)
    note = ""
    if k < len(lines) and lines[k].startswith(
        ("Ranked for ", f"{RUNS_MARK} ", "Price: ", f"{STEP_MARK} ", f"{ESTIMATE_MARK} ")
    ):
        n = k
        while n < len(lines) and lines[n].strip():
            n += 1
        note = " ".join(" ".join(lines[k:n]).split())
        end = n
    if len(head) == 2 + len(TIERS) and runs is None and f"{RUNS_MARK} runs by default." not in note:
        return None
    k = _skip_blank(lines, end)
    conversation = None
    if k < len(lines) and (conv := _CONVERSATION_RE.match(lines[k])):
        conversation = conv.group(1)
        end = k + 1
    found = _RANKED_FOR_RE.search(note)
    ranked_for = None
    if found:
        ranked_for = f"{found.group(1)}, {found.group(2)} complexity" + (
            ", novel" if found.group(3) else ""
        )
    return end, columns, conversation, ranked_for


def relayout(
    text: str,
    *,
    price: PriceFn | None = None,
    phase_written: Callable[[str], bool] | None = None,
) -> tuple[str, int, int]:
    """``text`` with each Settings ladder roadmodel 0.2.86–0.2.94 wrote (a
    table with Cost / Balanced / Quality columns, or 0.2.94's lists) rewritten
    as the ladder table, every model, platform, level and AA Index kept as
    written and each option's price filled in by ``price``. A ladder under a
    step that is Complete or In progress, or under a phase whose roadmap
    ``phase_written`` says exists, is the record of what ran or is running
    and stays as it is. A ladder no longer names a column to run
    (2026-10-29): the Runs paragraph under any other ladder goes, the table's
    own layout current or not. Returns the text, the ladders rewritten and
    the ladders kept. A table with a row this release does not know is left
    alone and not counted."""
    lines = text.split("\n")
    out: list[str] = []
    converted = kept = 0
    done = False
    # A ladder just rewritten owns the Runs paragraph after it: one count.
    owner = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _STEP_RE.match(line):
            done = "✅" in line
        elif phase := _PHASE_RE.match(line):
            written = phase_written(phase.group(1)) if phase_written else False
            done = "✅" in line or written
        elif re.match(r"^#{1,2} ", line):
            done = False
        elif status := _STATUS_RE.match(line):
            done = done or status.group(1).startswith(("Complete", "In progress"))

        if not done and _RUNS_RE.match(line):
            while i < len(lines) and lines[i].strip():
                i += 1
            if out and not out[-1].strip():
                out.pop()
            converted += 0 if owner else 1
            owner = False
            continue

        found: _Found | None = None
        head = _HEAD_RE.match(line)
        if head and i + 1 < len(lines) and _RULE_RE.match(lines[i + 1]):
            end = i + 2
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            rows = [_table_cells(ln) for ln in lines[i + 2 : end]]
            columns = None
            if rows and all(len(r) == 1 + len(TIERS) for r in rows):
                parse = _ranked_columns if head.group(1) == "Rank" else _pick_columns
                columns = parse(rows)
            if columns is None:
                out.extend(lines[i:end])
                i = end
                continue
            found = (end, columns, _table_conversation(rows), None, False)
        elif _INDENT_HEAD_RE.match(line) and i + 1 < len(lines) and _RULE_RE.match(lines[i + 1]):
            indented = _indented_ladder(lines, i)
            if indented is not None:
                found = (*indented, True)
        elif _TIER_HEAD_RE.match(line) and line.startswith("**Cost**"):
            listed = _list_ladder(lines, i)
            if listed is not None:
                end, columns, _, conversation = listed
                found = (end, columns, conversation, None, False)

        if found is None:
            out.append(line)
            owner = owner and not line.strip()
            i += 1
            continue
        end, columns, conversation, ranked_for, display_fix = found
        # The `&nbsp;` indent is a display defect (some viewers draw each
        # non-breaking space as a highlighted blob), and its fix changes no
        # value, so it reaches every ladder, Complete steps included.
        if done and not display_fix:
            kept += 1
            out.extend(lines[i:end])
            i = end
            continue
        priced = {
            tier: {
                k: None if o is None else (o if display_fix else _priced(o, price))
                for k, o in col.items()
            }
            for tier, col in columns.items()
        }
        md = ladder_markdown(priced, conversation=conversation, ranked_for=ranked_for)
        if out and out[-1].strip():
            out.append("")
        out.extend(md.split("\n"))
        if end < len(lines) and lines[end].strip():
            out.append("")
        converted += 1
        owner = True
        i = end
    return "\n".join(out), converted, kept


# --------------------------------------------------------------------------- #
# Re-ranking the tables this release writes
# --------------------------------------------------------------------------- #

# A ladder table's header: 0.2.95–0.2.97 (`|  | Cost |`, fields indented
# with `&nbsp;`) or 0.2.98 on (`|  |  | Cost |`, the rank in its own column).
_TABLE_RE: Final = re.compile(r"^\|\s*\|(?:\s*\|)?\s*Cost\b")
_RANKED_FOR_RE: Final = re.compile(
    r"Ranked for ([a-z-]+), (low|medium|high) complexity(, novel)?\."
)
_SECTION_RE: Final = re.compile(r"^(?:## (Step \S+)|### (Phase [0-9A-Za-z.]+)|### (\S+))")


@dataclass(frozen=True)
class TableLadder:
    """A ladder table (0.2.95 on) in a roadmap, with the lines it spans: the
    table, its note, its Conversation line and its Runs paragraph."""

    start: int
    end: int
    section: str
    phase: bool
    done: bool
    picks: tuple[tuple[str, str], ...]
    ranks: tuple[tuple[str, ...], ...]
    ranked_for: tuple[str, str, bool] | None
    conversation: str | None


def _skip_blank(lines: list[str], i: int) -> int:
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i


def _block_end(lines: list[str], i: int) -> int:
    """The index past a ladder's note paragraph, Conversation line and Runs
    paragraph (each optional, in that order), from just past its table."""
    k = _skip_blank(lines, i)
    if k < len(lines) and lines[k].startswith(
        ("Ranked for ", f"{RUNS_MARK} ", "Price: ", f"{STEP_MARK} ", f"{ESTIMATE_MARK} ")
    ):
        while k < len(lines) and lines[k].strip():
            k += 1
        i = k
    k = _skip_blank(lines, i)
    if k < len(lines) and lines[k].startswith("**Conversation:**"):
        i = k + 1
    k = _skip_blank(lines, i)
    if k < len(lines) and lines[k].startswith("**Runs:**"):
        while k < len(lines) and lines[k].strip():
            k += 1
        i = k
    return i


def _table_rows(lines: list[str], j: int) -> tuple[dict[str, dict[str, list[str]]], int]:
    """A ladder table's cells by rank and field, read from its first body row
    ``lines[j]``, and the index past the table. Reads both layouts: the rank
    in its own column (0.2.98 on: `| **Pick** | Model | …`, then `|  |
    Platform | …`) and a rank row over `&nbsp;`-indented fields (0.2.95–0.2.97:
    `| **Pick** |  |  |  |`, then `| &nbsp;…Model | …`)."""
    cells: dict[str, dict[str, list[str]]] = {}
    rank = ""
    while j < len(lines) and lines[j].startswith("|"):
        row = _table_cells(lines[j])
        if len(row) == 2 + len(TIERS):
            head, name, *values = row
            if head.startswith("**"):
                rank = head.strip("*")
                cells[rank] = {}
            if rank and name:
                cells[rank][name] = values
        else:
            label, *values = row
            name = label.replace("&nbsp;", "").strip()
            if name.startswith("**"):
                rank = name.strip("*")
                cells[rank] = {}
            elif rank:
                cells[rank][name] = values
        j += 1
    return cells, j


def table_ladders(
    text: str, *, phase_written: Callable[[str], bool] | None = None
) -> list[TableLadder]:
    """Every ladder table in ``text``, each with its section (`Step 5`,
    `Phase 32`), whether it sits under a phase heading, whether its step or
    phase is done (Complete, In progress, or a written phase), its Picks and
    every rank's models, the classification its note names, and its
    Conversation value."""
    lines = text.split("\n")
    out: list[TableLadder] = []
    section, phase, done = "", False, False
    i = 0
    while i < len(lines):
        line = lines[i]
        if m := _SECTION_RE.match(line):
            section = m.group(1) or m.group(2) or m.group(3)
            phase = m.group(2) is not None
            done = "✅" in line or bool(
                phase and phase_written and phase_written(section.split(" ", 1)[1])
            )
        elif re.match(r"^#{1,2} ", line):
            section, phase, done = "", False, False
        elif status := _STATUS_RE.match(line):
            done = done or status.group(1).startswith(("Complete", "In progress"))
        elif line.startswith("**Phase roadmap settings**"):
            # The session that writes a phase roadmap, under any heading
            # (pyfinlab's `### F1 —` workstreams): a phase ladder.
            phase = True
        if not (_TABLE_RE.match(line) and i + 1 < len(lines) and _RULE_RE.match(lines[i + 1])):
            i += 1
            continue
        j = i + 2
        raw, j = _table_rows(lines, j)
        cells = {
            rank: {
                name: [v.strip("*").replace(f" {STEP_MARK}", "") for v in values]
                for name, values in fields.items()
            }
            for rank, fields in raw.items()
        }
        end = _block_end(lines, j)
        block = "\n".join(lines[j:end])
        found = _RANKED_FOR_RE.search(" ".join(block.split()))
        conv = next((m.group(1) for ln in lines[j:end] if (m := _CONVERSATION_RE.match(ln))), None)
        pick = cells.get("Pick", {})
        picks = tuple(zip(pick.get("Model", []), pick.get("Level", []), strict=False))
        ranks = tuple(tuple(cells[r].get("Model", [])) for r in cells)
        out.append(
            TableLadder(
                start=i,
                end=end,
                section=section,
                phase=phase,
                done=done,
                picks=picks,
                ranks=ranks,
                ranked_for=(
                    (found.group(1), found.group(2), bool(found.group(3))) if found else None
                ),
                conversation=conv,
            )
        )
        i = end
    return out


def replace_ladders(text: str, replacements: Mapping[int, tuple[int, str]]) -> str:
    """``text`` with each ladder starting at line ``start`` (a key) replaced,
    through its ``end`` line, by the given Markdown."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if i in replacements:
            end, md = replacements[i]
            out.extend(md.split("\n"))
            i = end
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)
