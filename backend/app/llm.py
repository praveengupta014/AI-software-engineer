"""The one place that talks to Claude."""

from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Turn:
    assistant_content: Any  # appended to history unchanged (thinking blocks must round-trip)
    tool_calls: list[ToolCall]
    text: str
    stop_reason: str | None
    model: str
    request_id: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    refusal: dict[str, Any] = field(default_factory=dict)


class LLM(Protocol):
    def turn(
        self,
        *,
        agent: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        effort: str,
    ) -> Turn: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def turn(self, *, agent, system, messages, tools, effort) -> Turn:
        # Tools use strict: true rather than eager_input_streaming. Nothing here renders
        # partial tool input, and a proposal must never contain a silently cut-off file,
        # which eager streaming's unvalidated parsing can produce.
        with self._client.beta.messages.stream(
            model=self._model,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        ) as stream:
            message = stream.get_final_message()
            request_id = stream.request_id

        details = getattr(message, "stop_details", None)
        return Turn(
            assistant_content=message.content,
            tool_calls=[
                ToolCall(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"
            ],
            text="".join(b.text for b in message.content if b.type == "text"),
            stop_reason=message.stop_reason,
            model=message.model,
            request_id=request_id,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            refusal=(
                {"category": details.category, "explanation": details.explanation}
                if details
                else {}
            ),
        )


def check_key(api_key: str, model: str) -> str | None:
    """Return a problem with this key, or None if it works. Costs no tokens."""
    try:
        anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=15).models.retrieve(model)
    except anthropic.AuthenticationError:
        return "Anthropic rejected this API key"
    except anthropic.PermissionDeniedError:
        return "This API key does not have access to the Claude API"
    except anthropic.NotFoundError:
        return f"This account cannot use the model {model}"
    except anthropic.APIConnectionError:
        return "Could not reach Anthropic. Check the server's internet connection."
    except anthropic.APIStatusError as exc:
        return f"Anthropic returned an error ({exc.status_code})"
    return None
