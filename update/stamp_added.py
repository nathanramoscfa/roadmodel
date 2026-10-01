#!/usr/bin/env python3
"""Stamp the day a model joins the catalog: ``added-on="YYYY-MM-DD"``.

/models tags a model New for its first 14 days, counted from its release date
on Artificial Analysis. A model AA has yet to list has no release date, so the
catalog's newest models went untagged: GPT-6.1 Sol joined on 2026-10-01 and sat
unannounced at the foot of the table, in its "Not measured" group. The web now
counts from ``added-on`` until AA dates the release.

The catalog cron runs this with the committed selector as ``--base``. A
``<model>`` the base lacks gets ``added-on`` set to today; an ``added-on`` the
curation pass dropped comes back from the base. A model already in the base
without a stamp keeps none, so the first run tags only what that run adds.

    python update/stamp_added.py --write --base /tmp/base-selector.txt [--today YYYY-MM-DD]
    python update/stamp_added.py --base /tmp/base-selector.txt          # report only
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

UPDATE_DIR = Path(__file__).resolve().parent
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

from build_catalog import _parse_attrs  # noqa: E402
from selector_re import MODEL_RE  # noqa: E402

REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)


def _models(selector_text: str) -> list[tuple[int, int, dict[str, str]]]:
    """Each ``<model>`` in ``<model-options>``: its span in the whole text and
    its attributes."""
    options = _OPTIONS_RE.search(selector_text)
    if options is None:
        raise ValueError("<model-options> block not found in selector text")
    base = options.start(1)
    return [
        (base + m.start(), base + m.end(), _parse_attrs(m.group(1)))
        for m in MODEL_RE.finditer(options.group(1))
    ]


def stamps(selector_text: str) -> dict[str, str | None]:
    """Every model id in the selector, with its ``added-on`` date or None."""
    return {a.get("id", ""): a.get("added-on") or None for _, _, a in _models(selector_text)}


def stamp(selector_text: str, base_text: str, today: dt.date) -> tuple[str, dict[str, str]]:
    """The selector with every model the base lacks stamped ``today`` and every
    dropped stamp restored. Returns the text and the stamps it wrote."""
    base = stamps(base_text)
    written: dict[str, str] = {}
    text = selector_text
    # Edit from the end so earlier spans stay valid.
    for start, end, attrs in sorted(_models(selector_text), key=lambda m: -m[0]):
        mid = attrs.get("id", "")
        if attrs.get("added-on"):
            continue
        if mid not in base:
            day = today.isoformat()
        elif base[mid]:
            day = str(base[mid])
        else:
            continue
        element = text[start:end]
        # At the end of the element, just before "/>": the element's head
        # (id, name, prices), which other tools anchor on, stays unchanged.
        close = element.rstrip().rfind("/>")
        element = f'{element[:close].rstrip()} added-on="{day}"{element[close:]}'
        text = text[:start] + element + text[end:]
        written[mid] = day
    return text, dict(sorted(written.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", type=Path, required=True, help="the committed selector")
    parser.add_argument("--write", action="store_true", help="write the stamps into the selector")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    today = args.today or dt.datetime.now(dt.UTC).date()
    text, written = stamp(SELECTOR_PATH.read_text(), args.base.read_text(), today)
    for mid, day in written.items():
        print(f"added-on {day}: {mid}")
    if args.write and written:
        SELECTOR_PATH.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
