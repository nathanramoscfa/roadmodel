# update/opus_turn.py
"""One place where the refresh crons talk to Opus and insist on a FINISHED turn.

Every cron here asks Opus to emit a whole regenerated file inside a JSON
string, then parses the result. That makes an unfinished turn indistinguishable
from malformed output at the parse site — which is exactly how the catalog
refresh failed silently for fifteen days and the Claude Code refresh for
twenty-four: both reported "Model did not return valid JSON" while the real
answer was "the model never got to finish".

Two ways a turn ends early, neither of which raises:

- ``stop_reason == "max_tokens"``. The answer is cut mid-token. The selector
  payload crossed 64k output tokens in 2026-08 (measured at 66,690 on
  2026-09-04), so the ceiling every cron had been carrying since it was written
  quietly became too small. Fatal here, with the number in the message.
- ``stop_reason == "pause_turn"``. Only with server-side tools: the API's own
  sampling loop hit its iteration cap and handed back a partial answer. The fix
  is to re-send the conversation with the paused turn appended (no synthetic
  "Continue." message — the trailing server_tool_use block is what tells the
  server where to resume). Recoverable, bounded by MAX_TURN_CONTINUATIONS.

Callers get the concatenated assistant text of a turn that actually ended, or
an exception naming why it didn't.
"""

from __future__ import annotations

import sys
from typing import Any

from anthropic.types import TextBlock

# Opus 4.7 accepts up to 128K output tokens and the SDK requires streaming at
# that size, which every caller here already does. This is a ceiling, not a
# spend: raising it costs nothing on turns that finish sooner.
MAX_OUTPUT_TOKENS = 128000

# A server-tool loop that has not converged after this many resumes is stuck,
# not slow.
MAX_TURN_CONTINUATIONS = 4


class OpusTurnIncomplete(RuntimeError):
    """Opus stopped before finishing its answer (truncated / paused / refused).

    Distinct from a JSON parse failure on purpose: the output is not malformed,
    it is UNFINISHED. Conflating the two is what made a token-ceiling problem
    read as a parser problem for three weeks.
    """


def stream_until_complete(
    client: Any,
    *,
    model: str,
    max_tokens: int,
    system: list[dict[str, Any]],
    user_message: str,
    tools: list[dict[str, Any]] | None = None,
    label: str = "",
) -> str:
    """Return the assistant text of a COMPLETED turn.

    Raises:
        OpusTurnIncomplete: the turn ended without a complete answer —
            ``max_tokens`` truncation, a refusal, or still paused after
            ``MAX_TURN_CONTINUATIONS`` resumes.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    tag = f"{label} " if label else ""
    chunks: list[str] = []

    for turn in range(MAX_TURN_CONTINUATIONS + 1):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        with client.messages.stream(**kwargs) as stream:
            response = stream.get_final_message()

        chunks.append(
            "".join(block.text for block in response.content if isinstance(block, TextBlock))
        )
        sys.stderr.write(
            f"opus_turn: {tag}turn {turn + 1} stop_reason={response.stop_reason!r} "
            f"output_tokens={response.usage.output_tokens} (max_tokens={max_tokens})\n"
        )

        if response.stop_reason == "pause_turn":
            # Re-send the original request plus the paused turn; the server
            # resumes its tool loop where it left off.
            messages = [messages[0], {"role": "assistant", "content": response.content}]
            continue
        if response.stop_reason == "max_tokens":
            raise OpusTurnIncomplete(
                f"{tag}output hit max_tokens={max_tokens} — the answer is truncated. "
                f"Opus 4.7 allows up to {MAX_OUTPUT_TOKENS}; raise the ceiling or "
                "split the pass."
            )
        if response.stop_reason == "refusal":
            raise OpusTurnIncomplete(f"{tag}the model refused this request.")
        break
    else:
        raise OpusTurnIncomplete(
            f"{tag}still paused after {MAX_TURN_CONTINUATIONS} continuations "
            "(stop_reason='pause_turn') — the server-side tool loop never converged."
        )

    return "".join(chunks)
