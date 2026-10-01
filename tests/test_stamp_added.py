"""The day a model joins the catalog (update/stamp_added.py).

/models tags a model New for 14 days from its release on Artificial Analysis.
GPT-6.1 Sol joined on 2026-10-01, before AA listed it, so it had no release date
and no tag, and it sat in the table's "Not measured" group at the foot of the
page. The catalog cron now stamps ``added-on`` on every model its run adds, and
the web counts New from it until AA dates the release.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import stamp_added  # noqa: E402

TODAY = dt.date(2026, 10, 2)


def _model(mid: str, extra: str = "") -> str:
    return (
        f'      <model id="{mid}" name="{mid.upper()}"\n'
        '             input-price-per-1m="$1.00" output-price-per-1m="$4.00"\n'
        '             best-for="x"' + (f" {extra}" if extra else "") + " />"
    )


def _selector(*models: str) -> str:
    body = "\n".join(models)
    return f'<selector>\n<model-options>\n    <tier cost="low">\n{body}\n    </tier>\n</model-options>\n</selector>\n'


BASE = _selector(_model("old"), _model("kept", 'added-on="2026-09-30"'))


def test_a_model_the_base_lacks_is_stamped_today() -> None:
    text, written = stamp_added.stamp(
        _selector(_model("old"), _model("kept", 'added-on="2026-09-30"'), _model("new")),
        BASE,
        TODAY,
    )
    assert written == {"new": "2026-10-02"}
    assert stamp_added.stamps(text) == {"old": None, "kept": "2026-09-30", "new": "2026-10-02"}
    # At the end of the element: its head, which other tools anchor on, is unchanged.
    assert '<model id="new" name="NEW"\n' in text
    assert 'best-for="x" added-on="2026-10-02"/>' in text
    # A second run changes nothing.
    assert stamp_added.stamp(text, text, TODAY) == (text, {})


def test_a_model_already_catalogued_is_never_stamped() -> None:
    # The first run must not tag the whole catalog New.
    text, written = stamp_added.stamp(BASE, BASE, TODAY)
    assert (text, written) == (BASE, {})


def test_a_stamp_the_curation_pass_dropped_comes_back() -> None:
    text, written = stamp_added.stamp(_selector(_model("old"), _model("kept")), BASE, TODAY)
    assert written == {"kept": "2026-09-30"}
    assert stamp_added.stamps(text)["kept"] == "2026-09-30"


def test_the_catalog_carries_the_stamp_to_the_web() -> None:
    catalog = json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())
    by_id = {m["id"]: m for m in catalog["models"]}
    assert all("added_on" in m for m in catalog["models"])
    assert by_id["gpt-6.1-sol"]["added_on"] == "2026-10-01"
    web = (REPO_ROOT / "web" / "lib" / "catalog-models.ts").read_text()
    assert "newUntil(bench?.release_date ?? m.added_on, now)" in web


def test_the_catalog_cron_stamps_after_the_lifecycle_tags() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    at = wf.index("python update/stamp_added.py --write --base /tmp/base-selector.txt")
    assert wf.index("python update/dispose_discoveries.py --write") < at
    assert wf.index("python update/supersede.py --write --base") < at
    assert (
        at
        < wf.index("python update/model_prose.py --write")
        < wf.index("python update/render_md.py")
    )
    prompt = (UPDATE_DIR / "prompt.md").read_text()
    assert re.search(r"`added-on`.*?copy it verbatim", prompt, re.S)
