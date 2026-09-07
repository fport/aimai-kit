"""Provider-agnostic internal message format.

The four types in this file are the only vocabulary the rest of the package
speaks. Neither the prompt layer nor the agent loop ever sees a vendor SDK
type; those stay behind the `adapters/` boundary.

Two decisions keep this from collapsing into a lowest-common-denominator
abstraction:

1. `ChatRequest` already carries fields this layer does not use
   (`json_schema`, `tools`) and leaves them empty. Adding a field is
   backward compatible; renaming one is not. Later stages fill them in and
   the adapter signature never changes.
2. Anything provider-specific goes into `extra`. Gemini's `thinking_config`
   or OpenAI's `reasoning_effort` therefore neither pollute the internal
   model nor become unreachable.

Every type is frozen: once a `ChatRequest` is built it does not change. That
is not fastidiousness — the cache-prefix stability test relies on the
request not mutating quietly along the way.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "Role",
    "Message",
    "Usage",
    "JsonSchemaSpec",
    "ChatRequest",
    "ToolCall",
    "ChatResult",
]


class Role(StrEnum):
    """Message roles.

    `TOOL` is never produced at this layer; it is reserved for tool results.
    Differences such as Gemini naming the assistant role "model" are resolved
    in the adapter, not here.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    """A single conversation message.

    `content` is plain text. Multimodal content is out of scope; when it
    arrives, the right move is a separate `parts` field rather than turning
    `content` into a union type, because that breaks no existing caller.
    """

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        """Plain-dict view for the token counter and the adapters."""
        return {"role": self.role.value, "content": self.content}


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for one call.

    NOTE: `input_tokens` INCLUDES cached tokens (see the decision in
    `pricing.py`). Anthropic reports `cache_read_input_tokens` separately;
    the adapter normalizes that here so every layer above can rely on one
    rule.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class JsonSchemaSpec:
    """An output schema to bind to the model.

    The schema itself is provider-agnostic JSON Schema; each adapter wraps it
    under its own parameter name (OpenAI `text.format`, Anthropic
    `output_config`). `strict` should not be turned off — with it off the
    schema becomes a wish rather than a constraint.
    """

    name: str
    schema: Mapping[str, Any]
    strict: bool = True

    @property
    def fingerprint(self) -> str:
        """Short fingerprint of the schema, written to telemetry.

        `sort_keys=True` matters: if the same schema produced a different
        fingerprint depending on construction order, "did the schema change?"
        would have no answer.

        This goes into `UsageRecord` because reading an eval result requires
        knowing which schema produced it as much as which prompt. When a
        schema evolves silently, old and new records stop being comparable
        and only the fingerprint shows it.
        """
        raw = json.dumps(dict(self.schema), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """A provider-agnostic request.

    `system` is a top-level field rather than an entry in the message list.
    Anthropic and Gemini already expect it that way, and turning it into a
    message for OpenAI is a one-liner. Normalizing in the other direction
    (burying the system prompt in a message and digging it back out in the
    adapter) would mean string surgery on every call.
    """

    messages: Sequence[Message]
    system: str | None = None
    max_output_tokens: int = 1024
    temperature: float | None = None
    stop: Sequence[str] = ()
    prompt_ref: str | None = None
    json_schema: JsonSchemaSpec | None = None
    tools: Sequence[Mapping[str, Any]] = ()
    tool_choice: str | None = None
    operation: str = "chat"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def message_dicts(self) -> list[dict[str, str]]:
        """Flattened message list, system included, for token counting."""
        out: list[dict[str, str]] = []
        if self.system:
            out.append({"role": "system", "content": self.system})
        out.extend(m.as_dict() for m in self.messages)
        return out


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the model.

    `arguments` stays a raw JSON string on purpose. Parsing belongs to the
    executor, which has to turn a parse failure into an instructive message
    for the model; parsing here would either raise inside the adapter or
    swallow the error.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    """A provider-agnostic response.

    `raw` carries the original SDK object but is typed `Any`: touching it
    from a layer above is where vendor leakage starts. Use it for debugging
    only.
    """

    text: str
    usage: Usage
    provider: str
    model: str
    finish_reason: str = "stop"
    prompt_ref: str | None = None
    tool_calls: Sequence[ToolCall] = ()
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)
