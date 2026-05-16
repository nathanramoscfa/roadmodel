# MCP Server Setup

`roadmodel-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io/)
stdio server that exposes roadmodel's recommendation engine to any MCP
client (Cursor, Claude Code, Claude Desktop, VS Code + Continue, etc.).
This guide walks through installing the server, configuring a BYO API
key, and registering the server with each supported client.

For the tool catalog — signatures, parameters, and return schemas —
see [docs/mcp-tools.md](mcp-tools.md).

## Install

The MCP runtime is an optional extra. Install with the `[mcp]`
extra to pull in the `mcp` SDK alongside roadmodel:

```sh
pip install "roadmodel[mcp]"
```

A plain `pip install roadmodel` keeps the SDK optional and does **not**
install `mcp` — `roadmodel-mcp` will exit `2` on launch with an install
hint instead of starting the server.

Verify the entrypoint is on `PATH`:

```sh
roadmodel-mcp --help
```

A successful install prints the FastMCP help banner and exits `0`. If
the command is missing, your `pip` install went to a Python whose
`bin` directory is not on your shell `PATH`; resolve that before
moving on.

## BYO API key setup

`roadmodel-mcp` calls **your** provider account on every
`recommend_model` invocation — the same as the CLI. It resolves a
key from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY`
(env var preferred), then from `~/.config/roadmodel/config.toml`,
then auto-selects a provider in fixed order. The full precedence
chain, where to generate keys, and how to verify a smoke call live in
[docs/byo-key-setup.md](byo-key-setup.md). MCP clients invoke
`roadmodel-mcp` as a subprocess, so the key must be reachable from
the subprocess's environment — set it in the client's `env` block
(shown per-client below) rather than relying on shell exports.

## Cursor

Cursor reads MCP servers from `~/.cursor/mcp.json` (user-global) or
`.cursor/mcp.json` (per-project). Add a `roadmodel` entry under
`mcpServers`:

```json
{
  "mcpServers": {
    "roadmodel": {
      "command": "roadmodel-mcp",
      "args": [],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Replace the placeholder key with your real `ANTHROPIC_API_KEY`
(or swap for `OPENAI_API_KEY` / `GOOGLE_API_KEY` — roadmodel
auto-selects a provider from whichever is present). If the
`roadmodel-mcp` script lives outside Cursor's inherited `PATH`,
use the absolute path printed by `which roadmodel-mcp` instead of
the bare command name.

**Verify in Cursor.** Open Settings (`Cmd+Shift+J` on macOS,
`Ctrl+Shift+J` on Linux/Windows) → **Features → Model Context
Protocol**. The `roadmodel` server should appear with a green
indicator and three tools listed: `recommend_model`,
`generate_phase_roadmap`, `read_catalog`. If it does not connect,
open the Output panel (`Cmd+Shift+U`) and pick **MCP Logs** from the
dropdown to read the stderr stream from `roadmodel-mcp`.

## Claude Code

Claude Code stores MCP server entries in `~/.claude.json` (local
and user scope) or in `.mcp.json` at the project root (project
scope, version-controlled). The recommended path is to register
with the `claude mcp add` CLI, which writes the entry into the
right scope for you. Pick **user scope** if you want
`roadmodel-mcp` available in every Claude Code session on this
machine:

```sh
claude mcp add \
  --transport stdio \
  --scope user \
  --env ANTHROPIC_API_KEY=sk-ant-... \
  roadmodel \
  -- roadmodel-mcp
```

The `--` separates the server name from the command Claude Code
will launch; all options must come **before** the server name (see
the [upstream docs](https://docs.anthropic.com/en/docs/claude-code/mcp)
for the option-ordering rule).

For a project-shared registration — committed to git so every
contributor on the repo gets the server automatically — write
`.mcp.json` at the repo root by hand instead:

```json
{
  "mcpServers": {
    "roadmodel": {
      "type": "stdio",
      "command": "roadmodel-mcp",
      "args": [],
      "env": {
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"
      }
    }
  }
}
```

The `${ANTHROPIC_API_KEY}` form forwards the variable from each
developer's shell so the file does not embed a key.

**Verify in Claude Code.** Run `claude mcp list` from any shell to
see registered servers and their scope, or run `/mcp` inside a
Claude Code session for live status — the panel shows the tool
count next to each connected server. A healthy `roadmodel` entry
reports three tools.

## Other MCP clients

roadmodel-mcp is a standard stdio MCP server, so any compliant
client can host it. Two common ones with their own setup guides:

- **Claude Desktop.** Edit
  `~/Library/Application Support/Claude/claude_desktop_config.json`
  (macOS) and add a `roadmodel` entry under `mcpServers` using the
  same JSON shape shown for Cursor above. Full walk-through:
  [modelcontextprotocol.io/quickstart/user](https://modelcontextprotocol.io/quickstart/user).
- **VS Code + Continue.** Add the server under `mcpServers` in
  `~/.continue/config.json` with the same JSON shape, then reload
  Continue. Full walk-through:
  [docs.continue.dev/customize/deep-dives/mcp](https://docs.continue.dev/customize/deep-dives/mcp).

## Troubleshooting

**`roadmodel-mcp: install with 'pip install roadmodel[mcp]' to enable the MCP server`**
— the `mcp` SDK is not installed. Plain `pip install roadmodel` does
not pull it in. Re-run with the extra: `pip install "roadmodel[mcp]"`.
The process exits `2`; the client will report the server failed to
start.

**`No provider key found. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY.`**
— the subprocess `roadmodel-mcp` cannot see your key. Shell
exports from `~/.zshrc` etc. usually do **not** propagate to GUI-launched
client subprocesses, so set the key inside the client's `env` block
(see the Cursor / Claude Code examples above) rather than relying on
the shell environment. Confirm with `claude mcp get roadmodel` or by
reading the Cursor MCP Logs.

**Tool call times out or returns a `ProviderCallError`.** The
provider call itself failed — most commonly because the underlying
API key is rate-limited, revoked, or out of credit. The MCP error
text wraps the provider's own message (`Anthropic API call failed:
…`, `OpenAI API call failed: …`, `Google API call failed: …`).
Re-run the same prompt through `roadmodel recommend` from the
command line to reproduce outside the MCP transport; if the CLI
also fails, the issue is your provider account, not the MCP wiring.
