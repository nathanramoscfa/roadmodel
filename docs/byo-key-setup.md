# Bring Your Own API Key

roadmodel calls **your** AI provider account on every `recommend`
invocation; the project itself ships with no built-in key and runs
no inference backend. This guide walks through generating a key with
each supported provider, where to store it, and how to verify the
setup works end-to-end.

## Choosing a provider

You need a key for exactly one of Anthropic, OpenAI, or Google for the
CLI to work — the other two are optional. **Anthropic is the
recommended default**: roadmodel's prompt is structurally close to
Claude's strengths (long-context reasoning, structured-output
adherence) and the [private
roadmap](../private/ROADMAP.md) selects Claude (Opus 4.7) as the
default frontier model for the eventual hosted tier. OpenAI is a
solid alternative when you already pay for ChatGPT and want to keep
spend on one provider; Google is cheapest per token but has the
weakest reasoning on this prompt shape based on the bundled
benchmarks. You can configure more than one key and switch with
`--provider anthropic|openai|google` per invocation.

## Anthropic

1. Open the [Anthropic Console](https://console.anthropic.com/) and
   sign in (create an account first if you do not have one). New
   accounts require organisation setup and an initial billing
   top-up before keys will work.
2. Open the user menu (top right) → **Settings** → **API Keys**.
3. Click **Create Key**. Give it a memorable name
   (e.g. `roadmodel-cli`). Copy the key value once — Anthropic does
   not display the full key again.
4. Export it as `ANTHROPIC_API_KEY`:
   ```sh
   export ANTHROPIC_API_KEY=sk-ant-...
   ```
   Persist by adding the line to `~/.zshrc` / `~/.bashrc` /
   equivalent, or put it in `~/.config/roadmodel/config.toml` (see
   "Where to put the key" below).

## OpenAI

1. Open the [OpenAI Platform](https://platform.openai.com/) and sign
   in. You need an account with billing configured at
   [platform.openai.com/account/billing](https://platform.openai.com/account/billing)
   for the key to issue paid requests.
2. Navigate to **API keys**
   ([platform.openai.com/api-keys](https://platform.openai.com/api-keys)).
3. Click **Create new secret key**. Give it a name
   (e.g. `roadmodel-cli`), optionally scope it to a project, and
   copy the resulting `sk-...` value. OpenAI shows the key value
   once.
4. Export it as `OPENAI_API_KEY`:
   ```sh
   export OPENAI_API_KEY=sk-...
   ```

## Google

1. Open [Google AI Studio](https://aistudio.google.com/) and sign in
   with a Google account.
2. Click **Get API key** (in the left nav, or visit
   [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
   directly).
3. Click **Create API key**. Pick the Google Cloud project you want
   the key associated with (or accept the auto-created one). Copy
   the resulting `AIza...` value.
4. Export it as `GOOGLE_API_KEY`:
   ```sh
   export GOOGLE_API_KEY=AIza...
   ```

> Free-tier quotas on AI Studio are generous for the recommendation
> workload but rate-limited. If you hit `429` errors, enable billing
> on the linked Google Cloud project to lift the per-minute caps.

## Where to put the key

Two supported storage locations:

**1. Environment variable (recommended for local use).** Set the
relevant `*_API_KEY` env var in your shell, either inline for one
invocation or persisted in `~/.zshrc` / `~/.bashrc` / a `.envrc`
loaded by [direnv](https://direnv.net/). This is the cleanest
option on a personal machine.

**2. Config file (recommended for headless / CI use).** Write the
key into `~/.config/roadmodel/config.toml` (or
`$XDG_CONFIG_HOME/roadmodel/config.toml` when `XDG_CONFIG_HOME` is
set) under a `[providers.<name>]` table:

```toml
# ~/.config/roadmodel/config.toml
[providers.anthropic]
api_key = "sk-ant-..."

[providers.openai]
api_key = "sk-..."

[providers.google]
api_key = "AIza..."
```

Make the file readable only by you (`chmod 600 ~/.config/roadmodel/config.toml`).
The CLI does not log the key value and never echoes it to stdout or
stderr.

**Precedence.** When more than one source supplies a key for the same
provider, roadmodel resolves in this order:

1. The `--provider` CLI flag selects which provider to use (it does
   not itself carry a key value, but it determines which env var /
   config-file section is consulted).
2. The matching environment variable (`ANTHROPIC_API_KEY` /
   `OPENAI_API_KEY` / `GOOGLE_API_KEY`).
3. The `[providers.<name>].api_key` value in
   `~/.config/roadmodel/config.toml`.

The first non-empty source wins; the env var is preferred over the
TOML file so that ad-hoc overrides work without editing config.

If no provider is selected explicitly and multiple keys are present
in the environment, roadmodel auto-selects in fixed order:
`anthropic` → `openai` → `google`. Override with `--provider` or by
setting the `ROADMODEL_PROVIDER` env var.

## Verifying

Once you have a key set, set up your user-context file per
[user-context-setup.md](user-context-setup.md) and then run:

```sh
roadmodel recommend "hello"
```

A successful call exits with status `0` and prints a six-field
`MODEL / PLATFORM / MAX MODE / THINKING / CONVERSATION / RATIONALE`
block to stdout. If you see:

- **`No provider key found. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY.`**
  — the env var is not exported in the shell you ran the command
  in. Run `echo $ANTHROPIC_API_KEY` to confirm, then re-export it
  or move it to `~/.config/roadmodel/config.toml`.
- **`Invalid API key`** (or HTTP 401) — the key value is malformed
  or has been revoked. Re-create in the provider console.
- **A stderr message about `user-context.md`** — the key worked but
  the user-context file has not been bootstrapped yet. Follow the
  prompt and re-run.

If exit `0` and a parsed six-field block: you are done.
