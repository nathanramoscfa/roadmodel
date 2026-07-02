"""Tests for update/verify_availability.py (Phase 4.9 B5).

The live web-search call is integration (exercised via workflow dispatch); these
pin the pure grounded-flip policy — decide() — and the reconcile adjudicator wiring
in probe_availability. The policy is the safety valve on "fully autonomous", so its
thresholds are worth locking down.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_ROOT = REPO_ROOT / "update"
if str(UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(UPDATE_ROOT))

from probe_availability import reconcile  # noqa: E402
from verify_availability import (  # noqa: E402
    _is_export_controlled,
    _normalize,
    decide,
)


def _verdict(status="available", conf=0.95, evidence=("https://a",), rtype="none"):
    return {
        "model_id": "m",
        "status": status,
        "restriction_type": rtype,
        "confidence": conf,
        "evidence_urls": list(evidence),
        "summary": "",
        "as_of": "2026-07-01",
    }


# --- decide(): un-bench (currently benched) --------------------------------


def test_unbench_plain_restored_grounded() -> None:
    action, _ = decide(_verdict(), {"id": "m", "source": "probe"})
    assert action == "unbench"


def test_unbench_blocked_on_low_confidence() -> None:
    action, _ = decide(_verdict(conf=0.5), {"id": "m"})
    assert action == "hold"


def test_unbench_blocked_without_evidence() -> None:
    action, _ = decide(_verdict(evidence=()), {"id": "m"})
    assert action == "hold"


def test_unbench_blocked_when_ai_still_sees_a_restriction() -> None:
    # High confidence + evidence, but restriction_type != none => not fully clear.
    action, _ = decide(_verdict(rtype="capacity_or_rate"), {"id": "m"})
    assert action == "hold"


def test_restricted_verdict_holds_a_benched_model() -> None:
    action, _ = decide(_verdict(status="restricted"), {"id": "m"})
    assert action == "hold"


# --- decide(): export-control higher bar -----------------------------------


def test_export_control_needs_higher_confidence_and_more_evidence() -> None:
    entry = {"id": "claude-fable-5", "restriction_type": "export_control_or_jurisdictional"}
    # Would clear the plain bar (0.85, 1 source) but not the export bar (0.90, 2).
    action, _ = decide(_verdict(conf=0.85, evidence=("https://a",)), entry)
    assert action == "hold"
    action, _ = decide(_verdict(conf=0.95, evidence=("https://a", "https://b")), entry)
    assert action == "unbench"


def test_export_control_detected_from_reason_text() -> None:
    entry = {"id": "m", "reason": "US export-control directive; foreign-national access"}
    assert _is_export_controlled(entry) is True
    # One source at 0.9 clears the plain bar but not the export bar.
    action, _ = decide(_verdict(conf=0.95, evidence=("https://a",)), entry)
    assert action == "hold"


# --- decide(): bench (not currently benched) -------------------------------


def test_bench_on_confident_cited_restriction() -> None:
    action, _ = decide(_verdict(status="restricted", conf=0.7, rtype="deprecated_or_pulled"), None)
    assert action == "bench"


def test_no_bench_when_available_or_low_confidence() -> None:
    assert decide(_verdict(status="available"), None)[0] == "hold"
    assert decide(_verdict(status="restricted", conf=0.4), None)[0] == "hold"


def test_unknown_status_always_holds() -> None:
    assert decide(_verdict(status="unknown"), {"id": "m"})[0] == "hold"
    assert decide(_verdict(status="unknown"), None)[0] == "hold"


# --- _normalize(): garbled verdict degrades safely -------------------------


def test_normalize_clamps_and_defaults() -> None:
    out = _normalize({"status": "bogus", "confidence": "n/a", "evidence_urls": ["", " x "]}, "m")
    assert out["status"] == "unknown"
    assert out["confidence"] == 0.0
    assert out["evidence_urls"] == ["x"]
    assert out["model_id"] == "m"


# --- reconcile() adjudicator wiring ----------------------------------------


def test_reconcile_adjudicator_unbench_removes() -> None:
    current = [{"id": "claude-fable-5", "source": "manual"}]

    def adjudicate(entry):
        return "unbench", {"decision_reason": "grounded"}

    new, added, removed = reconcile({}, current, "2026-07-01", adjudicate=adjudicate)
    assert removed == ["claude-fable-5"]
    assert new == []


def test_reconcile_adjudicator_hold_keeps_and_records_audit() -> None:
    current = [{"id": "claude-fable-5", "source": "manual"}]

    def adjudicate(entry):
        return "hold", {
            "verdict": "restricted",
            "confidence": 0.3,
            "decision_reason": "still gated",
        }

    new, added, removed = reconcile({}, current, "2026-07-01", adjudicate=adjudicate)
    assert removed == []
    (held,) = new
    assert held["verdict"] == "restricted"
    assert held["verified_at"] == "2026-07-01"


def test_reconcile_adjudicator_ignores_cheap_available_status() -> None:
    # Cheap probe says available, but the adjudicator holds -> NOT removed.
    current = [{"id": "claude-fable-5", "restriction_type": "export_control_or_jurisdictional"}]

    def adjudicate(entry):
        return "hold", {"decision_reason": "export gate unverified"}

    new, added, removed = reconcile(
        {"claude-fable-5": "available"}, current, "2026-07-01", adjudicate=adjudicate
    )
    assert removed == []
    assert {e["id"] for e in new} == {"claude-fable-5"}


def test_reconcile_without_adjudicator_keeps_cheap_selfheal() -> None:
    # Backward-compat: no adjudicator => a bare 'available' still self-heals.
    current = [{"id": "claude-fable-5", "source": "manual"}]
    new, added, removed = reconcile({"claude-fable-5": "available"}, current, "2026-07-01")
    assert removed == ["claude-fable-5"]
