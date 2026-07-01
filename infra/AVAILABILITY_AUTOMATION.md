# Autonomous model-availability tracking (Phase 4.9 B5)

Goal: a model whose provider access changes — pulled, restored, export-control
suspended, waitlisted — is detected, verified, and propagated to the recommender
**with no manual step**, and a **restored** model becomes recommendable again with
no package release. This doc is the end-to-end map plus the staged deploy order and
the cost.

## The pipeline

```
 daily 21:00 UTC cron (probe-availability.yml)
   │
   ├─ cheap probe (probe_availability.py, US-keyed, stdlib)
   │    • Anthropic: 1-token invoke → available | unavailable | ambiguous
   │    • Google/OpenAI: model-list longest-prefix match
   │    • BENCH direction: an explicit not-found adds an entry (fail-safe)
   │
   ├─ AI grounded sweep (verify_availability.py)  ← the un-bench gate
   │    • for every currently-benched entry: Claude + web_search reads primary
   │      sources → structured verdict {status, restriction_type, confidence,
   │      evidence_urls, summary}
   │    • decide(): un-bench ONLY on a grounded verdict; export-control entries
   │      carry a higher bar. A bare US-keyed 200 is NOT sufficient.
   │
   ├─ writes infra/model-availability.json (git source of truth; + audit fields)
   │    → auto-PR (human glance) → auto-merge
   │
   ├─ sync-availability.yml → sync_availability.py → Supabase model_availability
   │
   └─ web /api/recommend (getModelAvailability):
        • reads the table; forwards { unavailable_models, availability_authoritative }
        • authoritative=true when the read SUCCEEDED
             → service passes it to recommend_structured
             → selector treats the runtime list as the COMPLETE truth and
               SUPERSEDES the bundled <availability-context> fallback
             → a RESTORED model (absent from the list) is recommended again,
               no release
        • read failed → authoritative=false → selector keeps the fail-closed
          static <availability-context> default
```

## Why un-benching is gated (the compliance point)

The cheap probe runs on a **US-keyed** API key. A US-keyed 200 cannot prove a
foreign-national / regional export gate has been lifted, and it can't read a news
headline. So the cheap status is trusted to **bench** (fail-safe) but **not** to
**un-bench**. Un-benching goes through `verify_availability.decide()`:

| Situation | Bar to flip |
|---|---|
| Bench a live model | confidence ≥ 0.60 + ≥1 cited source, restriction confirmed (fail-safe; a bare cheap not-found also benches) |
| Un-bench a plain restriction | status=available, restriction_type=none, confidence ≥ 0.80 + ≥1 source |
| Un-bench an **export-control / jurisdictional** model | confidence ≥ 0.90 + ≥2 sources + AI affirmatively sees no remaining restriction |

Verification failure (refusal, unparseable, network) degrades to `unknown` → **hold**;
verification can never flip a model on its own. This is the safety valve on
"fully autonomous": no human approves the flip, but a naive signal can't cause it.

## Cost (the app engine is real API cash — not Max-funded)

Verifier model: `claude-sonnet-4-6` + `web_search` ($3 / $15 per MTok; search ≈
$0.01/query). Per verification: ~1K prompt + ~2 searches pulling ~20–40K tokens of
results into context + ~500-token JSON verdict.

- input ≈ 30K × $3/MTok = **$0.09**
- output ≈ 0.5K × $15/MTok = **$0.008**
- web search ≈ 2 × $0.01 = **$0.02**
- **≈ $0.12 per model, per run**

The sweep only runs over **currently-benched** models (typically 0–2). So:

| Restricted models | Daily | Monthly |
|---|---|---|
| 0 | $0 (no AI call) | $0 |
| 1 | ~$0.12 | ~$3.6 |
| 2 | ~$0.24 | ~$7.2 |

Worst case is bounded by the benched-set size, not the catalog size. If that set
ever grows large, cap it (verify the N oldest-unverified per day) before worrying
about cost.

## Staged deploy order

**Stage 1 — detection/verification engine (cron only; no release).** Already on
`main`-bound path once merged:
1. Merge the Stage-1 commit (verify_availability.py, probe wiring, cron `pip
   install anthropic`, JSON `restriction_type` tag).
2. `gh workflow run probe-availability.yml -f dry_run=true` and read the log — the
   `[verify]` lines show each benched model's verdict + decision. Confirms the AI
   path works before it can write anything.
3. Nothing recommends differently yet — Stage 1 only makes the JSON/DB layer
   grounded. Fable stays benched (correct).

**Stage 2 — authoritative runtime layer (ONE cutover release, then never again).**
The selector reaches prod only via PyPI + service floor bump; this is the single
release that moves availability fully to runtime:
1. Release `roadmodel` with the `availability_authoritative` param + the reworded
   `<availability-context>` (fallback, not hardcode).
2. Bump the service `roadmodel>=` floor and redeploy the service.
3. Deploy web (forwards `availability_authoritative`).
4. Verify against prod: a request returns the same picks (Fable still benched via
   the runtime table); then, in a scratch, flip the table row and confirm the
   restored model is recommended within the 60 s cache — with the availability
   service **down**, confirm it fails closed (Fable excluded via static fallback).

After Stage 2, un-benching is fully autonomous and release-free: the daily
grounded sweep removes the JSON entry → sync deletes the row → the authoritative
read stops excluding it → it's recommended. No human, no release.

## Files

| Layer | File |
|---|---|
| Cheap probe + reconcile (AI-gated) | `update/probe_availability.py` |
| AI verification + grounded-flip policy | `update/verify_availability.py` |
| Source of truth (+ audit fields) | `infra/model-availability.json` |
| JSON → Supabase | `update/sync_availability.py`, `.github/workflows/sync-availability.yml` |
| Daily cron | `.github/workflows/probe-availability.yml` |
| Web read + forward | `web/lib/availability.ts`, `web/app/api/recommend/route.ts` |
| Service passthrough | `service/app/recommend.py` |
| Selector authoritative override + static fallback | `src/roadmodel/recommend.py`, `docs/model-selector.txt` |
