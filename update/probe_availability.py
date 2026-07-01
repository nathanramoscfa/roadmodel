"""Daily model-availability probe (Phase 4.9 B4 + multi-provider extension).

Checks each watched catalog model against its provider's live API and, when a
model becomes not-found (pulled) or callable again (restored), edits
``infra/model-availability.json`` so the recommender stops / resumes picking it
WITHOUT a package release. The daily cron runs this and, on a change, opens an
auto-PR for a human glance before it auto-merges + syncs to the table the web
recommend path reads.

Per-provider strategy (each provider gated on its key — a missing key SKIPS that
provider, never errors):
  - anthropic: INVOCATION (1-token call). Its model LIST still showed Fable 5
    after the 2026-06-12 suspension, so only an actual call was definitive.
  - google / openai: MODEL LIST + longest-prefix match. Their ids carry version /
    preview / variant suffixes (gemini-3-pro -> gemini-3-pro-preview), so an exact
    id is brittle; matching each API id to its longest catalog-id prefix is robust
    and free, and these providers have no export-control-suspension concern.

FAIL-SAFE: only an explicit not-found (invoke) or absence-from-the-list benches a
model; auth / rate-limit / 5xx / network / a failed list fetch classify
'ambiguous' and never change the file. The auto-PR's human glance is the backstop.
A US-keyed probe can't see a purely foreign-national export gate, so Fable 5 also
stays baked in <availability-context>.

GROUNDED UN-BENCH: the cheap 'available' status is trusted to BENCH but not to
UN-BENCH. When ANTHROPIC_API_KEY is set, every currently-benched entry is re-run
through an AI web-search verification (verify_availability.py) — the daily
restricted sweep — and a model is only un-benched on a grounded verdict (cited
evidence, above a confidence bar that is higher for export-control entries). This
is what lets an export-control model be restored autonomously without a US-keyed
200 lifting a foreign-national gate it can't observe.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
AVAILABILITY_JSON = REPO_ROOT / "infra" / "model-availability.json"

# provider -> {"env", "strategy", "models"}. For "invoke", models maps catalog id
# -> exact API id. For "list", models is the catalog ids (matched against the
# provider's model list by longest prefix). Keep in sync with <model-options>
# (a test asserts every id is a real catalog model).
PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "strategy": "invoke",
        "models": {
            "claude-fable-5": "claude-fable-5",
            "opus-4.8": "claude-opus-4-8",
            "opus-4.7": "claude-opus-4-7",
            "sonnet-4.6": "claude-sonnet-4-6",
            "claude-4.5-haiku": "claude-haiku-4-5",
        },
    },
    "google": {
        "env": "GOOGLE_API_KEY",
        "strategy": "list",
        "models": [
            "gemini-2.5-flash",
            "gemini-3-flash",
            "gemini-3-pro",
            "gemini-3.1-pro",
            "gemini-3.5-flash",
        ],
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "strategy": "list",
        "models": [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5.1-codex",
            "gpt-5.2",
            "gpt-5.3-codex",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.5",
        ],
    },
}


def watch_ids() -> list[str]:
    """Every catalog id the probe watches, across providers."""
    out: list[str] = []
    for cfg in PROVIDERS.values():
        models = cfg["models"]
        out.extend(models if isinstance(models, list) else list(models))
    return out


# --- invocation (Anthropic) ---


def classify_probe(status: int, body: str) -> str:
    """Map an invocation response to available|unavailable|ambiguous.

    Only an explicit not-found is 'unavailable'; everything else non-200 (auth,
    rate-limit, 5xx, malformed) is 'ambiguous' — never bench on uncertainty.
    """
    if status == 200:
        return "available"
    low = body.lower()
    if (
        status == 404
        or "not_found_error" in low
        or "not found" in low
        or "does not exist" in low
        or "is not available" in low
    ):
        return "unavailable"
    return "ambiguous"


def probe_invoke(api_id: str, key: str) -> str:
    """Anthropic 1-token invocation -> availability class."""
    payload = json.dumps(
        {"model": api_id, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    ).encode()
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    req = urllib.request.Request(  # noqa: S310
        "https://api.anthropic.com/v1/messages", data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return classify_probe(resp.status, "")
    except urllib.error.HTTPError as exc:
        return classify_probe(exc.code, exc.read().decode(errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError):
        return "ambiguous"


# --- model list (Google / OpenAI) ---


def _http_get_json(url: str, headers: dict[str, str]) -> Any | None:
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def fetch_model_list(provider: str, key: str) -> set[str] | None:
    """Return the provider's live set of API model ids, or None on any error."""
    if provider == "google":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=1000"
        data = _http_get_json(url, {})
        if not isinstance(data, dict):
            return None
        return {
            str(m["name"]).removeprefix("models/")
            for m in data.get("models", [])
            if isinstance(m, dict) and m.get("name")
        }
    if provider == "openai":
        data = _http_get_json(
            "https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"}
        )
        if not isinstance(data, dict):
            return None
        return {str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")}
    return None


def _best_match(api_id: str, catalog_ids: list[str]) -> str | None:
    """The longest catalog id that ``api_id`` belongs to (exact, or id + '-suffix').

    Longest-match disambiguates e.g. 'gpt-5-mini-2026' -> 'gpt-5-mini' (not 'gpt-5')
    and 'gemini-3-pro-preview' -> 'gemini-3-pro'.
    """
    best: str | None = None
    for cid in catalog_ids:
        if api_id == cid or api_id.startswith(cid + "-"):
            if best is None or len(cid) > len(best):
                best = cid
    return best


def availability_from_list(catalog_ids: list[str], api_ids: set[str]) -> dict[str, str]:
    """Classify each catalog id available/unavailable by membership in the API list."""
    covered: set[str] = set()
    for api_id in api_ids:
        match = _best_match(api_id, catalog_ids)
        if match is not None:
            covered.add(match)
    return {cid: ("available" if cid in covered else "unavailable") for cid in catalog_ids}


def probe_provider(provider: str, cfg: dict[str, Any], key: str) -> dict[str, str]:
    """Return {catalog_id: class} for one provider's watched models."""
    if cfg["strategy"] == "invoke":
        models: dict[str, str] = cfg["models"]
        return {cid: probe_invoke(api_id, key) for cid, api_id in models.items()}
    catalog_ids: list[str] = cfg["models"]
    listed = fetch_model_list(provider, key)
    if listed is None:
        return dict.fromkeys(catalog_ids, "ambiguous")  # fail-safe: list fetch failed
    return availability_from_list(catalog_ids, listed)


# --- reconcile (provider-agnostic, driven by probe results) ---


def reconcile(
    results: dict[str, str],
    current: list[Any],
    today: str,
    *,
    adjudicate: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]] | None = None,
) -> tuple[list[Any], list[str], list[str]]:
    """Apply probe results to the current ``unavailable`` entries.

    Driven by ``results`` (only probed models), so a skipped provider (no key)
    leaves its models untouched.
      - probed 'unavailable' and not listed -> ADD (source=probe)
      - currently benched -> REMOVE only if grounded (see below)
      - 'ambiguous' / not probed / non-watch entries -> left as-is

    ``adjudicate`` gates the un-bench (removal) direction. When None (unit tests,
    or no ANTHROPIC_API_KEY), removal falls back to the cheap self-heal: a bare
    'available' status un-benches. When provided (the daily restricted sweep), the
    cheap status is NOT trusted on its own — every currently-benched entry is
    re-verified with web search, and only a grounded 'unbench' verdict removes it;
    a 'hold' keeps the entry and records the fresh audit metadata. This is what
    stops a US-keyed 200 from lifting an export-control gate it can't see.
    """
    listed = {e["id"] for e in current if isinstance(e, dict) and e.get("id")}
    removed: list[str] = []
    new_list: list[Any] = []
    for entry in current:
        mid = entry.get("id") if isinstance(entry, dict) else None
        if mid is None:
            new_list.append(entry)
            continue
        if adjudicate is not None:
            action, meta = adjudicate(entry)
            print(f"  [verify] {mid:18} -> {action}: {meta.get('decision_reason', '')}")
            if action == "unbench":
                removed.append(mid)
                continue
            held = dict(entry)
            held.update(meta)
            held["verified_at"] = today
            new_list.append(held)
            continue
        if results.get(mid) == "available":
            removed.append(mid)
            continue  # re-enabled (cheap self-heal — no adjudicator)
        new_list.append(entry)
    added: list[str] = []
    for mid in sorted(results):
        if results[mid] == "unavailable" and mid not in listed:
            new_list.append(
                {
                    "id": mid,
                    "reason": (
                        f"Auto-detected unavailable by the daily availability probe on "
                        f"{today} (provider API reported not-found)."
                    ),
                    "since": today,
                    "source": "probe",
                }
            )
            added.append(mid)
    return new_list, sorted(added), sorted(removed)


def _provider_of_map() -> dict[str, str]:
    """catalog id -> provider name, from the PROVIDERS watch table."""
    out: dict[str, str] = {}
    for provider, cfg in PROVIDERS.items():
        models = cfg["models"]
        for cid in models:  # dict (invoke) iterates keys; list iterates items
            out[cid] = provider
    return out


def _build_adjudicator(
    env: dict[str, str], results: dict[str, str]
) -> Callable[[dict[str, Any]], tuple[str, dict[str, Any]]] | None:
    """AI adjudicator for the daily restricted sweep, or None (falls back to cheap).

    Gated on ANTHROPIC_API_KEY (already a probe secret). Any import/client failure
    degrades to the cheap self-heal rather than blocking the probe.
    """
    if not env.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        from verify_availability import make_adjudicator

        client = anthropic.Anthropic()
        provider_of = _provider_of_map()
        return make_adjudicator(
            client,
            provider_of=lambda m: provider_of.get(m, "unknown"),
            cheap_of=lambda m: results.get(m),
        )
    except Exception as exc:  # noqa: BLE001 — never let verification break the probe
        print(
            f"[verify] AI adjudicator unavailable ({exc!r}); using cheap self-heal.",
            file=sys.stderr,
        )
        return None


def run(path: Path, env: dict[str, str], today: str, *, dry_run: bool) -> int:
    results: dict[str, str] = {}
    for provider, cfg in PROVIDERS.items():
        key = env.get(cfg["env"], "")
        if not key:
            print(f"[{provider}] no {cfg['env']} — skipped")
            continue
        provider_results = probe_provider(provider, cfg, key)
        results.update(provider_results)
        for cid, cls in sorted(provider_results.items()):
            print(f"  [{provider}] {cid:18} -> {cls}")

    data = json.loads(path.read_text(encoding="utf-8"))
    adjudicate = _build_adjudicator(env, results)
    if adjudicate is not None and data.get("unavailable"):
        print("[verify] AI-adjudicating the restricted sweep (grounded un-bench)…")
    new_list, added, removed = reconcile(
        results, data.get("unavailable", []), today, adjudicate=adjudicate
    )
    print(f"add (now unavailable): {added or '(none)'}")
    print(f"remove (re-enabled):   {removed or '(none)'}")
    if not added and not removed:
        print("No availability changes.")
        return 0
    if dry_run:
        print("DRY RUN — model-availability.json not written.")
        return 0
    data["unavailable"] = new_list
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path.name}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe model availability across providers.")
    parser.add_argument("--dry-run", action="store_true", help="Probe + print plan; do not write.")
    parser.add_argument("--json", type=Path, default=AVAILABILITY_JSON)
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if not any(env.get(cfg["env"]) for cfg in PROVIDERS.values()):
        keys = [cfg["env"] for cfg in PROVIDERS.values()]
        print(f"No provider API key present (need at least one of {keys}).", file=sys.stderr)
        return 2
    today = datetime.datetime.now(tz=datetime.timezone.utc).date().isoformat()
    return run(args.json, env, today, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
