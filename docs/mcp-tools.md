# MCP Tool Reference

`roadmodel-mcp` exposes three tools over the
[Model Context Protocol](https://modelcontextprotocol.io/). This
document is the schema reference — signatures, parameters, return
shapes, and worked examples. For installation and per-client
registration walk-throughs, see [docs/mcp-setup.md](mcp-setup.md).

## Tools

- [`recommend_model`](#recommend_model) — recommend a model /
  platform / settings block for a single task description.
- [`generate_phase_roadmap`](#generate_phase_roadmap) — generate
  a phase-roadmap Markdown block from a project brief.
- [`read_catalog`](#read_catalog) — return the bundled
  selector, tier-cost-scale doc, and catalog JSON verbatim.

Every tool reads provider configuration and the user-context file
through the same resolution chain the CLI uses
([docs/byo-key-setup.md](byo-key-setup.md),
[docs/user-context-setup.md](user-context-setup.md)). The MCP
transport adds no extra configuration surface.

## `recommend_model`

Recommend a model, platform, and settings for a single task.
Equivalent to `roadmodel recommend --json PROMPT` on the CLI side.

### Signature

```python
def recommend_model(
    task_description: str,
    context: str | None = None,
) -> dict
```

### Parameters

| Name               | Type          | Required | Description                                                                                                                                                  |
| ------------------ | ------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `task_description` | `str`         | yes      | The prompt the recommendation is for. Free-form natural language; the selection algorithm reads task category and complexity from this string.               |
| `context`          | `str \| None` | no       | Optional project / codebase context appended to the system prompt under `Project context:` and to the user prompt. Use to disambiguate ambiguous task types. |

### Returns

`dict` with the structured-recommendation payload:

| Key                     | Type            | Description                                                                                                                                       |
| ----------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model`                 | `str`           | The recommended model ID (e.g. `claude-opus-4-7`).                                                                                                |
| `platform`              | `str`           | The recommended access platform (e.g. `Claude Code`, `Cursor`, `Anthropic API direct`).                                                           |
| `settings`              | `dict[str, str]`| Per-platform settings dict, carrying **only the dials the chosen platform exposes** — a dial the surface lacks is absent from the dict, never present with `Off` or `N/A`. Claude Code → `{effort, thinking}` (no Max Mode on that surface); Codex → `{intelligence}` (Codex's UI name for the effort dial); Cursor → `{max_mode}` (Cursor exposes no reasoning dial). The full surface-by-surface mapping is [docs/settings-display.md](settings-display.md). |
| `rationale`             | `str`           | Justification from the selection algorithm as three labelled segments — `TASK: … PICK: … EFFORT: …` — citing benchmark tiers and justifying only the setting fields the chosen platform emits. |
| `conversation`          | `str`           | Suggested conversation handling (`New`, `Continue`, etc.) per the `<output-format>` spec in `model-selector.txt`.                                 |
| `session_cost_estimate` | `null`          | Always `null` over the MCP transport — cost estimation requires token counts not exposed by the tool surface.                                     |
| `comparison_table`      | `null`          | Always `null` over the MCP transport, for the same reason.                                                                                        |

### Example

Call:

```json
{
  "task_description": "build a SQL agent that translates natural-language questions into PostgreSQL queries"
}
```

Response excerpt:

```json
{
  "model": "claude-opus-4-7",
  "platform": "Claude Code",
  "settings": {
    "effort": "High",
    "thinking": "On"
  },
  "rationale": "TASK: Agentic coding — a SQL agent translating natural language to PostgreSQL. PICK: Opus 4.7 is S-tier on coding-agent benchmarks ... EFFORT: High effort with thinking on fits multi-step query planning ...",
  "conversation": "New",
  "session_cost_estimate": null,
  "comparison_table": null
}
```

Note what the `settings` dict does **not** contain: no `max_mode` key.
Claude Code has no Max Mode control, so the dial is omitted rather than
reported as off. A Cursor recommendation is the mirror image —
`{"max_mode": "ON"}` with no `effort` or `thinking`, because Cursor
exposes no reasoning dial. Consumers should treat every settings key as
optional and render whatever is present.

## `generate_phase_roadmap`

Generate a phase-roadmap Markdown document for a given project
brief and phase number, using the bundled
`phase-roadmap-template.md` as the system prompt.

### Signature

```python
def generate_phase_roadmap(
    project_brief: str,
    phase_number: int,
    prior_phases: list[str] | None = None,
) -> str
```

### Parameters

| Name            | Type                | Required | Description                                                                                                                                          |
| --------------- | ------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `project_brief` | `str`               | yes      | The short project description. Becomes the lead paragraph of the user prompt.                                                                        |
| `phase_number`  | `int`               | yes      | Which phase to generate (e.g. `2` for "Phase 2"). Appended to the user prompt as `Phase number: N`.                                                  |
| `prior_phases`  | `list[str] \| None` | no       | Brief one-line summaries of phases already shipped. Empty or whitespace-only entries are dropped. Provides continuity context for the generated phase. |

### Returns

`str` — the raw Markdown phase-roadmap from the provider, following
the structure of the bundled `phase-roadmap-template.md`. Unlike
`recommend_model`, this tool does not parse the response; the caller
gets the full block to render or persist as-is.

### Example

Call:

```json
{
  "project_brief": "Open-source CLI that recommends which AI model on which platform.",
  "phase_number": 2,
  "prior_phases": [
    "Phase 1 — public PyPI release of the CLI with BYO-key support."
  ]
}
```

Response excerpt (truncated):

```markdown
# Phase 2 — MCP server

## Goal
Ship `roadmodel-mcp`, a stdio Model Context Protocol server that
exposes the recommendation engine to Cursor, Claude Code, and any
other MCP-compatible client...

## Steps
1. Wire the `[mcp]` extra and the `roadmodel-mcp` console script.
2. ...
```

## `read_catalog`

Return the bundled selector text, tier-cost-scale doc, and catalog
JSON verbatim — no provider call. Useful when an MCP client wants
to surface the catalog alongside a recommendation, or to pin a
recommendation against a specific catalog hash.

### Signature

```python
def read_catalog() -> dict
```

### Parameters

None.

### Returns

`dict` with the bundled-doc payload:

| Key                        | Type            | Description                                                                                                                                                                                       |
| -------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model_selector_txt`       | `str`           | Verbatim contents of the bundled `model-selector.txt` — the selection algorithm and per-model access-methods catalog.                                                                              |
| `model_tier_cost_scale_md` | `str`           | Verbatim contents of the bundled `model-tier-cost-scale.md` — per-token prices and tier ratings.                                                                                                  |
| `catalog_json`             | `dict`          | Parsed `catalog.json` payload: provider/model metadata plus benchmark scores. The full schema lives in [docs/catalog.json](catalog.json).                                                          |
| `source_doc_sha256`        | `str \| null`   | SHA-256 of the source `model-selector.txt` at catalog build time, pulled from `catalog_json["source_doc_sha256"]`. Lets callers detect drift between the catalog and the live selector text.       |

### Example

Call:

```json
{}
```

Response excerpt (truncated):

```json
{
  "model_selector_txt": "<model-selector>\n  <selection-algorithm>...",
  "model_tier_cost_scale_md": "# Model Tier and Cost Scale\n...",
  "catalog_json": {
    "version": "2026-05",
    "providers": [ ... ],
    "source_doc_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  "source_doc_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```
