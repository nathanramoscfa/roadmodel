# User Context

## Active subscriptions

| Subscription  | Monthly | Provider  | What it pays for |
| ------------- | ------- | --------- | ---------------- |
| Cursor Ultra  | $200    | Cursor    | Shared token pool across Cursor models. |
| claude.ai Max | $100    | Anthropic | Claude models in Claude Code and claude.ai. |
| ChatGPT Plus  | $20     | OpenAI    | GPT models in ChatGPT and Codex CLI. |

## Active API keys

| Provider  | Key present | Notes |
| --------- | ----------- | ----- |
| Anthropic | Yes         | Available as fallback. |
| OpenAI    | Yes         | Available as fallback. |
| Google    | No          | Not configured. |
| xAI       | No          | Not configured. |

## Platform preference order

1. Claude Code
2. Codex CLI
3. ChatGPT app
4. Cursor Ultra pool
5. Anthropic API direct
6. OpenAI API direct

## Default Max Mode and thinking levels

- Max Mode follows complexity rules from the selector.
- GPT reasoning defaults to medium and escalates with complexity.
- Claude extended thinking defaults to off and escalates with complexity.
