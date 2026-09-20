# Bring Your Own API Key

roadmodel calls **your** AI provider account on every `recommend`
invocation; the project itself ships with no built-in key and runs
no inference backend. This guide walks through generating a key with
each supported provider, where to store it, and how to verify the
setup works end-to-end.

## Choosing a provider

You need a key for exactly one provider for the CLI to work — the
rest are optional. **Anthropic is the recommended default**:
roadmodel's prompt is structurally close to Claude's strengths
(long-context reasoning, structured-output adherence) and the
[private roadmap](../private/ROADMAP.md) selects Claude (Opus 4.7) as
the default frontier model for the eventual hosted tier. OpenAI is a
solid alternative when you already pay for ChatGPT and want to keep
spend on one provider; Google is cheapest per token but has the
weakest reasoning on this prompt shape based on the bundled
benchmarks. Those three use each vendor's native SDK. Every other
provider — DeepSeek, xAI, Groq, Mistral, Z.ai, OpenRouter, Together,
a local Ollama server, or any `custom` endpoint — is reached through
one generic [OpenAI-compatible adapter](#openai-compatible-providers);
see the [verified engines](#verified-engines) table before relying on
one, because the recommender needs strict labeled-block output and
smaller models often do not deliver it. You can configure more than
one key and switch with `--provider <name>` per invocation.

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

## OpenAI-compatible providers

These providers expose only a Chat Completions endpoint, so roadmodel
talks to all of them through one adapter
(`roadmodel.providers.openai_compatible`) that reuses the `openai` SDK
from the `recommend` extra with `base_url` pointed at the provider —
no extra dependency. Each is selected by its key being present (auto,
in the order of the table) or explicitly with `--provider <name>` /
`ROADMODEL_PROVIDER=<name>`. `--model` (or `ROADMODEL_MODEL`)
overrides the default model; the two aggregators have no sensible
default and require it.

| `--provider` | Key env              | Base URL (from the provider's docs)  | Default model         | Reasoning dial forwarded from `--thinking-budget` |
| ------------ | -------------------- | ------------------------------------ | --------------------- | ------------------------------------------------- |
| `deepseek`   | `DEEPSEEK_API_KEY`   | `https://api.deepseek.com` ([docs][ds]) | `deepseek-v4-pro`  | `thinking: {type: enabled/disabled}` + `reasoning_effort: low` ([thinking-mode guide][ds-think]) |
| `xai`        | `XAI_API_KEY`        | `https://api.x.ai/v1` ([docs][xai])  | `grok-4.6`            | none (grok-4.x chat documents no effort field)    |
| `groq`       | `GROQ_API_KEY`       | `https://api.groq.com/openai/v1` ([docs][groq]) | `openai/gpt-oss-120b` | `reasoning_effort: low` ([reasoning docs][groq-r]) |
| `mistral`    | `MISTRAL_API_KEY`    | `https://api.mistral.ai/v1` ([docs][mistral]) | `mistral-medium-latest` | `reasoning_effort: none` (budget 0) / `low` |
| `zai`        | `ZAI_API_KEY`        | `https://api.z.ai/api/paas/v4` ([docs][zai]) | `glm-5.2`       | `thinking: {type: enabled/disabled}` + `reasoning_effort: low` ([chat reference][zai-chat]) |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` ([docs][or]) | — (`--model` required) | none (models are heterogeneous)           |
| `together`   | `TOGETHER_API_KEY`   | `https://api.together.ai/v1` ([docs][tg]) | — (`--model` required) | none                                          |
| `ollama`     | none (`OLLAMA_API_KEY` optional) | `http://localhost:11434/v1`, or `OLLAMA_HOST` ([docs][ollama]) | — (`--model` required) | `reasoning_effort: none` (budget 0) / `low` |
| `custom`     | `ROADMODEL_API_KEY`  | `ROADMODEL_BASE_URL`                 | `ROADMODEL_MODEL` (required) | none                                     |

[ds]: https://api-docs.deepseek.com/
[ds-think]: https://api-docs.deepseek.com/guides/thinking_mode
[xai]: https://docs.x.ai/docs/guides/chat
[groq]: https://console.groq.com/docs/openai
[groq-r]: https://console.groq.com/docs/reasoning
[mistral]: https://docs.mistral.ai/api/
[zai]: https://docs.z.ai/guides/overview/quick-start
[zai-chat]: https://docs.z.ai/api-reference/llm/chat-completion
[or]: https://openrouter.ai/docs/quickstart
[tg]: https://docs.together.ai/docs/openai-api-compatibility
[ollama]: https://docs.ollama.com/openai

A `--thinking-budget` that is unset forwards nothing (the provider's
default applies); `0` selects the documented "off / lowest" rung and
any positive value the lowest effort — the recommender is a
structured-classification task, and on these endpoints reasoning
tokens count against `--max-output-tokens`, so an uncapped thinking
model can spend its entire budget thinking and return no visible
text (the CLI reports that case by name). `--temperature` is
forwarded when set. Keys go in the env var or under
`[providers.<name>]` in `config.toml` exactly like the native three.

**Hosted providers.** Generate the key in the provider's console
(DeepSeek [platform.deepseek.com](https://platform.deepseek.com/),
xAI [console.x.ai](https://console.x.ai/), Groq
[console.groq.com/keys](https://console.groq.com/keys), Mistral
[console.mistral.ai](https://console.mistral.ai/), Z.ai
[z.ai/manage-apikey](https://z.ai/manage-apikey/apikey-list),
OpenRouter [openrouter.ai/keys](https://openrouter.ai/keys), Together
[api.together.ai/settings/api-keys](https://api.together.ai/settings/api-keys)),
export it, and run:

```sh
export DEEPSEEK_API_KEY=sk-...
roadmodel recommend --provider deepseek "hello"
# aggregators need a model id in the provider's own namespace:
OPENROUTER_API_KEY=... roadmodel recommend --provider openrouter --model deepseek/deepseek-v4-pro "hello"
```

**Local Ollama.** No key. Pull a model whose context window is at
least 64k tokens — the recommender prompt (selector + tier scale +
your user-context) is ~55k tokens, and Ollama silently truncates a
prompt that exceeds the loaded context, dropping the instructions
first. Then:

```sh
ollama pull gemma3:12b            # 128k context
export ROADMODEL_PROVIDER=ollama ROADMODEL_MODEL=gemma3:12b
roadmodel recommend "Refactor auth middleware across 12 files"
```

`OLLAMA_HOST` (Ollama's own variable, `host:port` or a URL) redirects
to a remote server; `OLLAMA_API_KEY` is sent as the bearer token if
that server sits behind an authenticating proxy. If a model's full
context does not fit in memory (a 32B model at 256k needs tens of GB
of KV cache), derive a smaller-context tag —
`printf 'FROM qwen3-vl:32b\nPARAMETER num_ctx 65536\n' > Modelfile && ollama create qwen3-vl-64k -f Modelfile`
— and name that tag in `ROADMODEL_MODEL`. Thinking models (Qwen3,
DeepSeek-R1 distills) also need `--max-output-tokens 4096` or more,
or `--thinking-budget 0` where the model honors it (Qwen3-VL on
Ollama 0.32 keeps reasoning regardless). Expect minutes per call:
the first request pre-fills the ~55k-token prompt (about 9 minutes
for a 32B model on Apple silicon, ~1 minute for a 12B), later
requests reuse the cached prefix. `ollama` and `custom` calls get a
30-minute timeout with no automatic retries (the SDK default of 10
minutes plus two retries silently redid slow generations).

Two different things can involve Ollama, and they are configured in
two different places. `--provider ollama` (above) makes a local model
the **engine** that answers `roadmodel recommend` — that is what the
64k-context requirement is about. Being **recommended** to run a model
locally is the catalog side: the `ollama` access method in
`<access-methods>` (`PLATFORM: Ollama (local)`, $0 per token) is
funded only for the models you list in the "Local models (Ollama)"
table of your user-context file, and any such pick carries a
quantization caveat in its rationale. The two are independent — you
can be recommended `gpt-oss-20b` on Ollama while a hosted engine did
the recommending, and vice versa. See
[`user-context-setup.md`](user-context-setup.md), "Local models
(Ollama)".

**Custom endpoint.** Any other OpenAI-compatible server — vLLM, LM
Studio, llama.cpp's server, a corporate gateway:

```sh
export ROADMODEL_PROVIDER=custom
export ROADMODEL_BASE_URL=http://localhost:8000/v1   # must end in the /v1 (or equivalent) prefix
export ROADMODEL_API_KEY=none                        # required by the SDK; any string if the server ignores it
export ROADMODEL_MODEL=my-served-model
roadmodel recommend "hello"
```

Nothing provider-specific is sent on the `custom` path (no reasoning
dial), so it works against the strictest endpoints.

## Verified engines

The recommender depends on strict labeled-block output (`MODEL:` /
`PLATFORM:` / the setting fields / `CONVERSATION:` / `RATIONALE:` —
three of them in ladder mode), so "the endpoint answers" is not the
bar; **adherence** is. `scripts/eval_recommend_engines.py` runs the
12-probe anon battery through every configured engine and scores
parse rate, ladder health, on-catalog picks and four instruction
checks. The table below is the run of 2026-09-20
([raw JSONL](eval/2026-09-20-openai-compatible-engines.jsonl) ·
[report](eval/2026-09-20-openai-compatible-engines.md)); rows are
reproducible with `--engines <key>` / `--extra provider:model`.

| Engine (`--provider` : model)      | Parsed | On-catalog picks | Mean latency | Verdict |
| ---------------------------------- | -----: | ---------------: | -----------: | ------- |
| `openai` : gpt-5-mini (control)    |  12/12 |             100% |        6.9 s | **Verified** — the anon-tier reference engine |
| `google` : gemini-2.5-flash (control) | 12/12 |          100% |        3.1 s | **Verified** |
| `ollama` : gemma3:12b (128k ctx, Apple silicon) | 10/12 | 70% | 11.8 s (after the ~1 min first-call prefill) | **Works, with caveats** — 2/12 malformed blocks, 2/12 unhealthy ladders, and 3/10 parsed runs named retired models the catalog does not carry (`Claude 3 Opus`, `gpt-4`, `gpt-3.5-turbo`). Fine for a private, keyless try-out; not a drop-in for a hosted engine. |
| `ollama` : qwen3-vl:32b (64k-ctx tag, thinking on) | 0/5 | — | 230–830 s | **Not viable** — spent the whole output budget reasoning on every probe, at 3072 *and* 8192 tokens; `reasoning_effort: none` / `think: false` do not silence it on Ollama 0.32. |
| `deepseek`, `xai`, `groq`, `mistral`, `zai`, `openrouter`, `together` | — | — | — | **Configured, unverified** — the adapter, key resolution and reasoning dials are unit-tested against the SDK contract and the base URLs are taken from each provider's docs, but no run has been made with a real key. Run the eval with your key (`DEEPSEEK_API_KEY=... python scripts/eval_recommend_engines.py --engines deepseek-flash`) before relying on one, and treat a first `Malformed provider response` as the engine's verdict, not a wiring bug. |
| `custom`                            | — | — | — | Depends entirely on the model behind the endpoint; same advice as above. |

The controls confirm the harness: both hosted engines that the hosted
service already uses score 100% on every check. Local models are a
different class — the prompt is ~55k tokens of catalog and rules,
and a 12B quantized model follows it most of the time but not always,
while a thinking 32B model never gets to the answer on this hardware.
Prefer a hosted engine for anything you will act on; use `ollama` when
keylessness or data residency matters more than reliability.

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
`anthropic` → `openai` → `google` → `deepseek` → `xai` → `groq` →
`mistral` → `zai` → `openrouter` → `together`. `ollama` and `custom`
are never auto-selected. Override with `--provider` or by setting the
`ROADMODEL_PROVIDER` env var. `ROADMODEL_MODEL` is the env form of
`--model` for every provider (the flag wins).

## Verifying

Once you have a key set, set up your user-context file per
[user-context-setup.md](user-context-setup.md) and then run:

```sh
roadmodel recommend "hello"
```

A successful call exits with status `0` and prints a labeled
`MODEL / BACKUP / PLATFORM / CONVERSATION / RATIONALE` block to
stdout, plus the setting fields the chosen platform exposes — e.g.
`EFFORT` + `THINKING` on Claude Code or Codex, `MAX MODE` on Cursor.
A dial the platform does not have is simply absent from the block, so
the exact field list varies with the platform that got picked; the
five fields above are the ones always present. If you see:

- **`No provider key found. Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY ...`**
  — the env var is not exported in the shell you ran the command
  in. Run `echo $ANTHROPIC_API_KEY` to confirm, then re-export it
  or move it to `~/.config/roadmodel/config.toml`.
- **`Provider 'ollama' has no default model: pass --model or set ROADMODEL_MODEL.`**
  (or the same for `custom` / `openrouter` / `together`) — name the
  model; these providers have no sane default.
- **`Provider 'custom' selected but ROADMODEL_BASE_URL is not set.`**
  — export the endpoint (with its `/v1` prefix) as well as
  `ROADMODEL_API_KEY` and `ROADMODEL_MODEL`.
- **`Ollama response contained reasoning but no visible text`** — a
  thinking model spent the whole output budget reasoning; raise
  `--max-output-tokens` or pass `--thinking-budget 0`.
- **`Invalid API key`** (or HTTP 401) — the key value is malformed
  or has been revoked. Re-create in the provider console.
- **A stderr message about `user-context.md`** — the key worked but
  the user-context file has not been bootstrapped yet. Follow the
  prompt and re-run.

If exit `0` and a parsed recommendation block: you are done.
