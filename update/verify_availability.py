"""AI availability verification (Phase 4.9 B5) — the grounded adjudicator.

The cheap daily probe (``probe_availability.py``) invokes each model with a
1-token call from a US-keyed API key. That is enough to *bench* a model (an
explicit not-found is fail-safe), but it is NOT enough to *un-bench* one: a
US-keyed 200 cannot prove a foreign-national export gate has been lifted, and it
can't read a news headline. This module adds a second, grounded opinion — Claude
with the ``web_search`` server tool — that reads primary sources and returns a
structured verdict, so the reconcile step can flip a model autonomously *with
evidence* instead of on a bare status code.

Two public surfaces:

  * :func:`verify_model` — the IO half: one Messages API call (web search +
    structured output) returning a validated verdict dict. Needs
    ``ANTHROPIC_API_KEY``.
  * :func:`decide` — the pure half: given a verdict and the model's current
    availability entry, returns ``unbench`` / ``bench`` / ``hold``. This is the
    grounded-autonomy policy and is unit-tested without any network.

Un-benching is deliberately harder than benching, and un-benching an
export-control / jurisdictional model is hardest of all (higher confidence + more
cited evidence + the AI must affirmatively see *no* remaining restriction). That
bar is the safety valve on "fully autonomous": no human approves the flip, but a
naive signal can't cause it either.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

# Cost-conscious: Sonnet 4.6 supports web_search_20260209 (dynamic filtering) and
# structured outputs, at $3/$15 per MTok. A verification run is a few K input +
# server-side search results + a small JSON verdict — well under $0.20/model (see
# infra/AVAILABILITY_AUTOMATION.md for the arithmetic). Bump to opus only if the
# verdict quality proves insufficient.
VERIFY_MODEL = "claude-sonnet-4-6"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}
MAX_SERVER_TOOL_TURNS = 4  # pause_turn continuations before we give up (-> unknown)

# --- grounded-flip policy thresholds ---------------------------------------
# Benching (restricting) is the fail-safe direction -> a lower bar.
BENCH_MIN_CONFIDENCE = 0.60
# Un-benching re-exposes a model to users -> a higher bar, and a higher one still
# for export-control / jurisdictional restrictions a US-keyed probe can't see.
UNBENCH_MIN_CONFIDENCE = 0.80
UNBENCH_MIN_EVIDENCE = 1
EXPORT_UNBENCH_MIN_CONFIDENCE = 0.90
EXPORT_UNBENCH_MIN_EVIDENCE = 2

_EXPORT_TYPES = {"export_control_or_jurisdictional"}
_EXPORT_HINTS = ("export", "jurisdiction", "foreign", "sanction", "ear", "itar")

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model_id": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["available", "restricted", "unknown"],
            "description": (
                "available = any developer can call it through its provider API today; "
                "restricted = access is pulled, gated, or limited for some/all users; "
                "unknown = the sources don't clearly say."
            ),
        },
        "restriction_type": {
            "type": "string",
            "enum": [
                "none",
                "deprecated_or_pulled",
                "capacity_or_rate",
                "export_control_or_jurisdictional",
                "policy_or_safety",
                "other",
            ],
        },
        "confidence": {
            "type": "number",
            "description": "0.0-1.0 — your calibrated confidence in `status`.",
        },
        "evidence_urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Primary-source URLs (provider docs, status page, official news) that back the verdict.",
        },
        "summary": {
            "type": "string",
            "description": "One or two sentences, citing what the sources say.",
        },
        "as_of": {
            "type": "string",
            "description": "The date the evidence reflects (ISO 8601 if known).",
        },
    },
    "required": [
        "model_id",
        "status",
        "restriction_type",
        "confidence",
        "evidence_urls",
        "summary",
        "as_of",
    ],
    "additionalProperties": False,
}

_SYSTEM = (
    "You verify the CURRENT real-world access status of a specific AI model's "
    "provider API, for a model-recommendation service that must never recommend a "
    "model users cannot actually call. Use web_search to consult primary sources — "
    "the provider's model docs, pricing page, status/changelog, and official "
    "announcements — before judging. Weigh recency: a restriction can be imposed or "
    "lifted at any time, so prefer the most recent authoritative source and record "
    "its date in `as_of`.\n\n"
    "Be conservative and calibrated. If a model was restricted for export-control or "
    "jurisdictional reasons, treat `status: available` as true ONLY when a primary "
    "source clearly states general access is restored — a model merely reappearing "
    "in an API list, or a single US-region success, is NOT sufficient, because a "
    "foreign-national or regional gate can persist invisibly. When the evidence is "
    "thin or conflicting, return `status: unknown` rather than guessing. Populate "
    "`evidence_urls` with the specific pages you relied on."
)


def build_prompt(
    model_id: str, *, display_name: str, provider: str, cheap_signal: str | None
) -> str:
    """The user turn: what to verify, plus the cheap probe's hint (not proof)."""
    hint = ""
    if cheap_signal:
        hint = (
            f"\n\nA cheap US-keyed API probe just classified this model "
            f"'{cheap_signal}'. Treat that as one weak signal, not proof — corroborate "
            f"it (or refute it) against primary sources, and remember a US-keyed probe "
            f"cannot observe a foreign-national or regional access gate."
        )
    return (
        f"Verify the current access status of the model '{display_name}' "
        f"(catalog id '{model_id}', provider '{provider}'). Is it callable by "
        f"developers through the provider's API right now, or is access "
        f"restricted in any way (deprecated/pulled, capacity/rate-limited, "
        f"export-control or jurisdictional, policy/safety)?{hint}"
    )


def _extract_verdict(content: list[Any]) -> dict[str, Any] | None:
    """Pull the JSON verdict from the response's final text block."""
    for block in content:
        if getattr(block, "type", None) == "text":
            try:
                obj = json.loads(block.text)
            except (json.JSONDecodeError, AttributeError):
                continue
            if isinstance(obj, dict):
                return obj
    return None


def _normalize(verdict: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Coerce to safe types; an out-of-range/garbled verdict degrades to 'unknown'."""
    status = str(verdict.get("status", "unknown"))
    if status not in {"available", "restricted", "unknown"}:
        status = "unknown"
    try:
        confidence = float(verdict.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    evidence = [str(u).strip() for u in verdict.get("evidence_urls", []) if str(u).strip()]
    return {
        "model_id": str(verdict.get("model_id") or model_id),
        "status": status,
        "restriction_type": str(verdict.get("restriction_type", "other")),
        "confidence": confidence,
        "evidence_urls": evidence,
        "summary": str(verdict.get("summary", "")).strip(),
        "as_of": str(verdict.get("as_of", "")).strip(),
    }


def verify_model(
    client: Any,
    model_id: str,
    *,
    display_name: str | None = None,
    provider: str = "unknown",
    cheap_signal: str | None = None,
) -> dict[str, Any]:
    """Run one web-search-grounded verification; return a normalized verdict dict.

    A refusal, an exhausted server-tool loop, or an unparseable response all
    degrade to ``status: unknown`` (which :func:`decide` treats as ``hold``) —
    verification failure must never itself flip a model.
    """
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": build_prompt(
                model_id,
                display_name=display_name or model_id,
                provider=provider,
                cheap_signal=cheap_signal,
            ),
        }
    ]
    response = None
    for _ in range(MAX_SERVER_TOOL_TURNS):
        response = client.messages.create(
            model=VERIFY_MODEL,
            max_tokens=2048,
            system=_SYSTEM,
            thinking={"type": "adaptive"},
            tools=[WEB_SEARCH_TOOL],
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": VERDICT_SCHEMA},
            },
            messages=messages,
        )
        if response.stop_reason == "refusal":
            return _normalize({"status": "unknown", "summary": "verification refused"}, model_id)
        if response.stop_reason == "pause_turn":
            # Server-tool loop hit its per-request cap; re-send to resume.
            messages = [messages[0], {"role": "assistant", "content": response.content}]
            continue
        break
    if response is None:
        return _normalize({"status": "unknown", "summary": "no response"}, model_id)
    verdict = _extract_verdict(response.content)
    if verdict is None:
        return _normalize({"status": "unknown", "summary": "unparseable verdict"}, model_id)
    return _normalize(verdict, model_id)


def _is_export_controlled(entry: dict[str, Any] | None) -> bool:
    """Was this model benched for an export-control / jurisdictional reason?"""
    if not entry:
        return False
    if str(entry.get("restriction_type", "")) in _EXPORT_TYPES:
        return True
    reason = str(entry.get("reason", "")).lower()
    return any(hint in reason for hint in _EXPORT_HINTS)


def decide(verdict: dict[str, Any], entry: dict[str, Any] | None) -> tuple[str, str]:
    """Pure grounded-flip policy → ('unbench' | 'bench' | 'hold', human reason).

    ``entry`` is the model's current ``model-availability.json`` entry, or None if
    the model is not currently benched. Un-benching requires the AI to affirmatively
    see NO remaining restriction, with confidence + cited evidence above threshold;
    the bar is higher for export-control models a US-keyed probe can't clear.
    Benching is the fail-safe direction and carries a lower bar.
    """
    status = verdict.get("status")
    confidence = float(verdict.get("confidence", 0.0))
    evidence = verdict.get("evidence_urls", []) or []

    if entry is not None:  # currently benched -> the only way out is a grounded un-bench
        if status != "available" or verdict.get("restriction_type") != "none":
            return "hold", f"still restricted/unclear (status={status}, conf={confidence:.2f})"
        if _is_export_controlled(entry):
            if (
                confidence >= EXPORT_UNBENCH_MIN_CONFIDENCE
                and len(evidence) >= EXPORT_UNBENCH_MIN_EVIDENCE
            ):
                return (
                    "unbench",
                    f"export-control lifted, grounded (conf={confidence:.2f}, {len(evidence)} sources)",
                )
            return "hold", (
                f"export-control un-bench needs conf>={EXPORT_UNBENCH_MIN_CONFIDENCE} and "
                f">={EXPORT_UNBENCH_MIN_EVIDENCE} sources (got {confidence:.2f}, {len(evidence)})"
            )
        if confidence >= UNBENCH_MIN_CONFIDENCE and len(evidence) >= UNBENCH_MIN_EVIDENCE:
            return (
                "unbench",
                f"access restored, grounded (conf={confidence:.2f}, {len(evidence)} sources)",
            )
        return (
            "hold",
            f"un-bench needs conf>={UNBENCH_MIN_CONFIDENCE} + a source (got {confidence:.2f}, {len(evidence)})",
        )

    # not currently benched -> bench only on a confident, cited restriction
    if status == "restricted" and confidence >= BENCH_MIN_CONFIDENCE and len(evidence) >= 1:
        return (
            "bench",
            f"restriction confirmed (conf={confidence:.2f}, {verdict.get('restriction_type')})",
        )
    return "hold", f"no confident restriction (status={status}, conf={confidence:.2f})"


def make_adjudicator(
    client: Any,
    *,
    provider_of: Callable[[str], str] | None = None,
    name_of: Callable[[str], str] | None = None,
    cheap_of: Callable[[str], str | None] | None = None,
) -> Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]:
    """Build the reconcile adjudicator: entry -> ('unbench'|'hold', audit meta).

    Used by ``probe_availability.reconcile`` for the daily restricted sweep — every
    currently-benched entry is re-verified with web search, and only a grounded
    verdict un-benches it.
    """

    def adjudicate(entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        mid = str(entry.get("id", ""))
        verdict = verify_model(
            client,
            mid,
            display_name=(name_of(mid) if name_of else mid),
            provider=(provider_of(mid) if provider_of else "unknown"),
            cheap_signal=(cheap_of(mid) if cheap_of else None),
        )
        action, reason = decide(verdict, entry)
        meta = {
            "verdict": verdict["status"],
            "restriction_type": verdict["restriction_type"],
            "confidence": verdict["confidence"],
            "evidence_urls": verdict["evidence_urls"],
            "ai_summary": verdict["summary"],
            "ai_as_of": verdict["as_of"],
            "decision_reason": reason,
        }
        return action, meta

    return adjudicate


def main(argv: list[str] | None = None) -> int:
    """Standalone: verify one model and print the verdict + decision (manual/debug)."""
    parser = argparse.ArgumentParser(description="AI-verify one model's access status.")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--provider", default="unknown")
    parser.add_argument(
        "--cheap-signal", default=None, choices=["available", "unavailable", "ambiguous"]
    )
    parser.add_argument(
        "--currently-benched",
        action="store_true",
        help="Treat the model as currently benched (evaluate the un-bench decision).",
    )
    args = parser.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required.", file=sys.stderr)
        return 2
    import anthropic

    client = anthropic.Anthropic()
    verdict = verify_model(
        client,
        args.model_id,
        display_name=args.display_name,
        provider=args.provider,
        cheap_signal=args.cheap_signal,
    )
    entry = {"id": args.model_id} if args.currently_benched else None
    action, reason = decide(verdict, entry)
    print(json.dumps({"verdict": verdict, "action": action, "reason": reason}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
