"""update/split_identity.py — a new model no longer stalls the typed refresh.

From 2026-10-14 every catalog refresh failed: one decline line for Gemini 4
Argon made automation_integrity refuse the whole candidate, so the prices and
letters in the same run never shipped either (#1120). The split keeps the part
the gate admits and holds the rest for a reviewed PR.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))


def _load(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, UPDATE_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ai = _load("automation_integrity")
build_catalog = _load("build_catalog")
dd = _load("dispose_discoveries")
render_md = _load("render_md")
si = _load("split_identity")

DAY = dt.date(2026, 10, 19)
GOOGLE = "update/catalog-google.json"
PATHS = [ai.SELECTOR, ai.MARKDOWN, ai.COST, ai.CATALOG, GOOGLE]
NOVA = dd.Flag("google", "Gemini 9 Nova", 2.0, 10.0, "provider page", "us")
DECLINE = "- google/Gemini 9 Test — a test decline (declined 2026-10-19)\n"


def _tree(root: Path) -> None:
    for path in {*ai.INPUTS, *PATHS}:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / path, root / path)
    for snapshot in UPDATE_DIR.glob("catalog-*.json"):
        shutil.copyfile(snapshot, root / "update" / snapshot.name)


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    base, head, hold = tmp_path / "base", tmp_path / "work", tmp_path / "hold"
    _tree(base)
    _tree(head)
    hold.mkdir()
    monkeypatch.setattr(si, "ROOT", head)
    monkeypatch.setattr(si, "UPDATE", head / "update")
    monkeypatch.setattr(si, "REPORT", head / "update" / ".last-held.md")
    monkeypatch.setattr(build_catalog, "SELECTOR_PATH", head / ai.SELECTOR)
    monkeypatch.setattr(build_catalog, "COST_SCALE_PATH", head / ai.COST)
    monkeypatch.setattr(build_catalog, "_UPDATE_DIR", head / "update")
    return {"base": base, "work": head, "hold": hold}


def _regenerate(root: Path) -> None:
    """What the refresh does after editing the selector and the cost scale."""
    selector = (root / ai.SELECTOR).read_text()
    (root / ai.MARKDOWN).write_text(render_md.render(selector))
    (root / ai.CATALOG).write_text(build_catalog.render_json(build_catalog.build_catalog()))


def _reader(root: Path) -> Any:
    return lambda path: (root / path).read_text(encoding="utf-8")


def _muse_price(text: str) -> str:
    rows, _ = ai.models(text)
    return str(rows["muse-spark-1.3"]["output-price-per-1m"])


def test_a_typed_refresh_ships_as_it_is(work: dict[str, Path]) -> None:
    root = work["work"]
    selector = (root / ai.SELECTOR).read_text()
    (root / ai.SELECTOR).write_text(
        selector.replace(
            'id="muse-spark-1.3" name="Muse Spark 1.3"\n             input-price-per-1m="$1.25" output-price-per-1m="$4.25"',
            'id="muse-spark-1.3" name="Muse Spark 1.3"\n             input-price-per-1m="$1.25" output-price-per-1m="$4.50"',
        )
    )
    _regenerate(root)
    before = {p: (root / p).read_text() for p in PATHS}
    assert si.split(work["base"], work["hold"], PATHS, DAY) is None
    assert {p: (root / p).read_text() for p in PATHS} == before
    assert not any(work["hold"].iterdir())


def test_a_new_model_is_held_and_the_typed_part_ships(work: dict[str, Path]) -> None:
    root = work["work"]
    selector = (root / ai.SELECTOR).read_text()
    selector, model_id = dd.add_model(selector, NOVA, None)
    selector = selector.replace('output-price-per-1m="$4.25"', 'output-price-per-1m="$4.50"', 1)
    (root / ai.SELECTOR).write_text(selector)
    cost = (root / ai.COST).read_text()
    cost = cost.replace("| $0.15      | $4.25  | Low  |", "| $0.15      | $4.50  | Low  |", 1)
    (root / ai.COST).write_text(cost + DECLINE)
    snapshot = json.loads((root / GOOGLE).read_text())
    snapshot["unexpected_slugs"] = ["Gemini 9 Nova"]
    (root / GOOGLE).write_text(json.dumps(snapshot, indent=2) + "\n")
    _regenerate(root)
    assert model_id == "gemini-9-nova"
    # The decline line alone made the gate refuse every run from 2026-10-14.
    with pytest.raises(ValueError, match="costscale_structure_requires_review"):
        ai.validate_documents(_reader(work["base"]), _reader(root), DAY)

    reason = si.split(work["base"], work["hold"], PATHS, DAY)

    assert reason == "costscale_structure_requires_review"
    # The typed part: the gate admits it, and it keeps the price edit only.
    ai.validate_documents(_reader(work["base"]), _reader(root), DAY)
    shipped = (root / ai.SELECTOR).read_text()
    assert "gemini-9-nova" not in shipped
    assert _muse_price(shipped) == "$4.50"
    assert "| $0.15      | $4.50  | Low  |" in (root / ai.COST).read_text()
    assert DECLINE not in (root / ai.COST).read_text()
    assert (root / GOOGLE).read_text() == (work["base"] / GOOGLE).read_text()
    # The held part: the whole candidate, for the review PR.
    hold = work["hold"]
    assert "gemini-9-nova" in (hold / ai.SELECTOR).read_text()
    assert DECLINE in (hold / ai.COST).read_text()
    assert "Gemini 9 Nova" in (hold / GOOGLE).read_text()
    report = (root / "update" / ".last-held.md").read_text()
    assert "- new model `gemini-9-nova` (Gemini 9 Nova, $2.00/$10.00)" in report
    assert "- `google-api` adds `gemini-9-nova`" in report
    assert "- decline line: google/Gemini 9 Test" in report
    assert f"- `{GOOGLE}` changed (outside the typed data set)" in report


def test_a_provider_price_waits_with_its_snapshot(work: dict[str, Path]) -> None:
    # Tests hold the selector to the committed snapshot, and the snapshot is
    # outside the typed data set: a provider's own price change is reviewed.
    root = work["work"]
    snapshot = json.loads((root / GOOGLE).read_text())
    row = next(m for m in snapshot["models"] if m["id"] == "gemini-3.1-pro")
    row["output_price_per_1m"] = 13.0
    (root / GOOGLE).write_text(json.dumps(snapshot, indent=2) + "\n")
    selector = (root / ai.SELECTOR).read_text()
    (root / ai.SELECTOR).write_text(
        selector.replace(
            'id="gemini-3.1-pro" name="Gemini 3.1 Pro"\n             input-price-per-1m="$2.00" output-price-per-1m="$12.00"',
            'id="gemini-3.1-pro" name="Gemini 3.1 Pro"\n             input-price-per-1m="$2.00" output-price-per-1m="$13.00"',
        )
    )
    _regenerate(root)

    assert si.split(work["base"], work["hold"], PATHS, DAY) == (
        "files outside the typed data set changed"
    )
    for path in PATHS:
        assert (root / path).read_text() == (work["base"] / path).read_text(), path
    assert 'output-price-per-1m="$13.00"' in (work["hold"] / ai.SELECTOR).read_text()


def test_new_benchmark_rows_wait_and_known_rows_ship() -> None:
    base = json.dumps({"model_count": 1, "models": {"a": {"aa_name": "A", "evaluations": {}}}})
    proposed = {
        "model_count": 2,
        "models": {
            "a": {"aa_name": "A", "evaluations": {"hle": 0.5}},
            "b": {"aa_name": "B", "evaluations": {}},
        },
    }
    typed = json.loads(si.typed_benchmarks(base, json.dumps(proposed)))
    assert typed["models"] == {"a": {"aa_name": "A", "evaluations": {"hle": 0.5}}}
    assert typed["model_count"] == 1
    renamed = {"model_count": 1, "models": {"a": {"aa_name": "Z", "evaluations": {}}}}
    assert (
        json.loads(si.typed_benchmarks(base, json.dumps(renamed)))["models"]["a"]["aa_name"] == "A"
    )


def test_both_refresh_workflows_split_before_the_gate() -> None:
    for name in ("update-models.yml", "update-benchmarks.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / name).read_text()
        assert text.index("update/split_identity.py") < text.index(
            "python update/automation_integrity.py"
        ), name
        assert "chore/catalog-review" in text, name
