# Settings display — turning the selector's output into a surface's real controls

`model-selector.txt` emits **platform-neutral axes**:

```text
MAX MODE: [On/Off]
THINKING: [Off/Low/Medium/High/XHigh/Max/N/A]
ORCHESTRATION: [None/PerPrompt/Ultracode/N/A]
```

Those are the selector's **internal reasoning model**, not the controls a user
actually sets. Every surface exposes a different set of dials, so the axes must
be mapped before they are shown in a roadmap table or a settings block.

**This mapping is not in the selector on purpose.** The selector's vocabulary is
pinned by the daily effort/thinking conformance tracker (it requires, e.g.,
`Ultracode` to read as a session setting and Cursor's `THINKING` to be `N/A`), so
encoding the display rules there would get reverted. They live here instead — and
`roadmodel`'s own `recommend_structured` applies exactly these rules, so an
offline consumer that follows this doc produces byte-identical settings.

## Claude Code → **Effort** + **Thinking**

Claude Code exposes a **single effort dial** — `Low` / `Medium` / `High` /
`XHigh` / `Max` / `Ultracode` (top) — plus a separate **Thinking on/off toggle**.
It has **no Max Mode** and **no standalone orchestration control**; never show
either.

- `ORCHESTRATION: Ultracode` → **Effort `Ultracode`**, **Thinking `On`**.
  Ultracode *is* the top of the effort ladder, so it folds into the effort value.
  Never emit a separate "Orchestration" row — `Effort: High + Orchestration:
  Ultracode` is incoherent and does not match the UI.
- `THINKING` of `Off` / `N/A` / `None` / `No` → **Effort `Low`**, **Thinking `Off`**.
- Otherwise → **Effort = the `THINKING` value**, **Thinking `On`**.

## Codex + OpenAI API → **Intelligence**

- **Intelligence = the `THINKING` value.** No Max Mode row, no separate Thinking row.
- Applies to both Codex and the direct **OpenAI API** — OpenAI's reasoning
  surfaces expose a reasoning-effort dial (surfaced as Intelligence), never Max
  Mode. (ChatGPT the consumer app has no fine dial and stays in the catch-all.)

## Cursor → **Max Mode** + **Thinking**

- **Max Mode** = `ON` when `MAX MODE` is on, else `OFF`.
- **Thinking `On`** — always. Cursor's frontier models always reason but the IDE
  exposes no thinking dial, so the selector emits `THINKING: N/A`. Shown raw that
  reads as "no controllable settings at all", which is wrong: the user's real
  dial on Cursor is Max Mode.

## Every other surface (Anthropic API, ChatGPT, …) → **Max Mode** + **Thinking**

- **Max Mode** = `ON` / `OFF`; **Thinking = the `THINKING` value**.

`MAX MODE` counts as on for `on` / `yes` / `true` / `enabled` (case-insensitive);
anything else is `OFF`.

## Conformance table

Machine-checked against `roadmodel.recommend._structured_settings` — if this
table and the code ever disagree, the test suite fails.

<!-- conformance-table:start -->

| PLATFORM | MAX MODE | THINKING | ORCHESTRATION | Displayed settings |
|---|---|---|---|---|
| Claude Code | Off | XHigh | Ultracode | effort=Ultracode; thinking=On |
| Claude Code | Off | Max | Ultracode | effort=Ultracode; thinking=On |
| Claude Code | Off | XHigh | None | effort=XHigh; thinking=On |
| Claude Code | Off | High | None | effort=High; thinking=On |
| Claude Code | Off | Off | None | effort=Low; thinking=Off |
| Claude Code | Off | N/A | None | effort=Low; thinking=Off |
| Codex | Off | High | None | intelligence=High |
| Codex | Off | XHigh | None | intelligence=XHigh |
| OpenAI API | Off | High | None | intelligence=High |
| OpenAI API | Off | XHigh | None | intelligence=XHigh |
| Cursor | On | N/A | None | max_mode=ON; thinking=On |
| Cursor | Off | N/A | None | max_mode=OFF; thinking=On |
| Anthropic API | On | High | None | max_mode=ON; thinking=High |
| ChatGPT | Off | Medium | None | max_mode=OFF; thinking=Medium |

<!-- conformance-table:end -->
