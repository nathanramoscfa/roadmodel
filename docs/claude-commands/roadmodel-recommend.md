---
description: Recommend the model and effort for a prompt before you start it (usage: /roadmodel-recommend <your prompt, on the lines below>)
---
Recommend the model, platform and level to run a prompt on, the way a
roadmodel roadmap recommends a step's Settings. This turn only
recommends: do not carry out the prompt or start any of its work.

The prompt is all of the text typed after the command, every line of it:

<prompt>
$ARGUMENTS
</prompt>

If it is empty, ask for the prompt in one line and stop.

## 1. Classify the prompt

Classify it from its text. Do not read, search or run anything in the
repository to size it. The one exception is a prompt that hands over a
document as the task itself ("do what docs/plan.md says"): read that
document.

- **PRIMARY category**, exactly one:
  - `coding`: implementation, debugging, refactoring, multi-file edits,
    tests, build or lint fixes
  - `planning`: architecture, design docs, multi-step plans, trade-off
    analysis, roadmaps
  - `agentic`: autonomous tool use, terminal commands, long multi-step
    execution, end-to-end agent loops
  - `multimodal`: images, video, audio or screenshots alongside text or
    code
  - `long-context`: large repo or file ingestion, codebase-wide
    reasoning, multi-document synthesis
  - `knowledge`: domain expertise, factual recall, grounded research,
    answers that must not hallucinate
  - `speed`: latency-sensitive or high-volume routine work

  When the prompt spans two, the more demanding one is PRIMARY and the
  other is SECONDARY ("audit the whole repo for race conditions":
  PRIMARY `long-context`, SECONDARY `coding`).
- **Complexity:** rate Complexity (how many interacting concerns),
  Ambiguity (judgment calls, trade-offs), Scope (localized or
  cross-cutting) and Novelty (known pattern or creative problem-solving)
  Low, Medium or High. The overall complexity is the highest of the four.
- **Novel:** only at High complexity, when the work is novel
  problem-solving or a multi-step proof rather than a known pattern.

## 2. Get the ladder

Call the roadmodel MCP tool `roadmap_settings` with `category`,
`complexity` and `novel` (leave `phase` off), and take its `markdown`.
Without that tool, run `roadmodel ladder --category <c> --complexity <x>`
(add `--novel` when novel). Both compute the same ladder in code from
this machine's roadmodel user-context, its subscriptions and keys, with
no model call. If neither is reachable, say so and that
`pip install -U roadmodel` followed by `roadmodel setup-mcp` provides
them, then stop. Never write a ladder by hand.

## 3. Answer

Reply with these five parts, in this order, and nothing else:

1. `**Best fit:** <model> · <level> on <platform> (<column> <rank>).`
   Name every option by its column and rank as the table does
   (`Quality Pick`, `Cost Runner-up`, `Balanced Backup`). Choose it on
   the prompt's merits alone, never on a usage pool's state, a Budget
   priority or which subscription has slack: the operator picks the
   option.
2. The ladder table and the note line under it, exactly as printed.
   Leave out its `**Conversation:**` line; part 5 covers it.
3. `**Why:**` the classification (PRIMARY, any SECONDARY, complexity,
   novel or not) and why, then why the best fit suits this prompt and
   what the other columns trade against it. Four sentences at most.
4. `**Here in <this agent>:**` each option of the ladder whose Platform
   is the agent you are running in, with its column and rank and how to
   switch to it.
   - Claude Code: open the model picker (`/model` on its own; in VS Code
     also the model name under the prompt box), choose the model by its
     family (`opus`, `sonnet`, `haiku` or `fable`, each its family's
     latest model) and set the level (the left and right arrows in the
     terminal, the Effort row in VS Code). Say once what is saved: in
     the terminal, `s` switches this session only and Enter saves both
     as the defaults for new sessions, as typing `/model <alias>` and
     `/effort <level>` does; in VS Code a level other than Max is saved
     as that model's default.
   - Codex, Antigravity, OpenCode and other agents: their model picker
     and reasoning setting.

   Thinking stays On wherever the agent has a Thinking toggle. When no
   option runs here, name the platforms they run on. An agent that
   reaches models through OpenRouter or an API key can run an option's
   model here too, billed per token at about its Price; say so when that
   is the case.
5. `**Start:**` switch to the option you choose and reply `go` to run
   the prompt in this conversation, or open a new conversation on those
   settings and paste the prompt. Repeat the prompt verbatim in a fenced
   block, with a fence longer than any run of backticks inside it, so
   it can be copied.

Then stop and wait.

## 4. On `go`

When the operator's next message is `go`, or otherwise says to start,
carry out the prompt as if it were the first message of this
conversation. This command's instructions end there.
