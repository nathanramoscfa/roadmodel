# User Context (cost-estimator fixture)

## Active subscriptions

| Subscription  | Monthly | Provider  | What it pays for                                     |
| ------------- | ------- | --------- | ---------------------------------------------------- |
| Cursor Ultra  | $200    | Cursor    | Shared token pool across every Cursor catalog model. |
| claude.ai Max | $100    | Anthropic | Claude usage in Claude Code and claude.ai web/desktop. |
| ChatGPT Pro   | $200    | OpenAI    | GPT / Codex usage across the OpenAI surfaces.        |

## Active API keys

| Provider  | Key present | Notes                                             |
| --------- | ----------- | ------------------------------------------------- |
| Anthropic | Yes         | Fallback when claude.ai Max budget is exhausted.  |
| OpenAI    | Yes         | Fallback when ChatGPT Pro caps are reached.       |
| Google    | No          | No Google AI Studio API key configured.           |
| xAI       | No          | No xAI API key configured.                        |

## Platform preference order

1. Claude Code
2. Codex
3. Cursor pool
4. Anthropic API direct
5. OpenAI API direct

## Default Max Mode and thinking levels

- Max Mode follows complexity rules from the selector.
- Claude extended thinking defaults to off and escalates with complexity.
- GPT reasoning defaults to medium.
