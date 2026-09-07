"""Tool result and tool specification types.

`ToolResult` is the only thing the agent loop looks at, which is why it is
deliberately flat: a boolean, a string the model reads, and an error code the
loop can branch on. Anything richer would push tool-specific knowledge into
the loop.

Why `side_effect` and `requires_approval` live on the SPEC and not in the
JSON Schema: the schema is what the model sees, and neither of these is
something the model should decide. A model that can set
`requires_approval=false` on its own call is not an approval gate. Keeping
them out of the schema also keeps them out of the cached prefix churn — the
executor reads them from the registry, where the operator put them.

`raw` never enters the context. It goes to the trace, so a debugging session
can see the full API payload while the model only ever sees `content`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

__all__ = ["ToolResult", "ToolSpec", "ErrorCode", "ERROR_CODES"]

# Error codes are a closed set on purpose. The loop branches on them, the
# metrics are labeled with them, and a free-form string would make both
# untestable.
ERROR_CODES = (
    "no_such_tool",
    "not_allowed",
    "bad_json",
    "bad_args",
    "needs_approval",
    "timeout",
    "tool_error",
)
ErrorCode = str


@dataclass(slots=True)
class ToolResult:
    """The outcome of one tool call.

    `content` is what the model reads; it is always a string, including on
    failure. Returning a traceback here would be both a leak and useless to
    the model — what helps is a sentence describing how to fix the call.

    `retryable` is not the same thing as `ok`. A schema error is retryable
    (the model can correct the arguments); a permission error is not (trying
    again changes nothing, and the loop should stop rather than burn steps).
    """

    ok: bool
    content: str
    error_code: ErrorCode | None = None
    retryable: bool = False
    raw: Any = None
    elapsed_ms: float = 0.0

    @classmethod
    def failure(
        cls, code: ErrorCode, content: str, *, retryable: bool = False
    ) -> ToolResult:
        return cls(ok=False, content=content, error_code=code, retryable=retryable)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Everything the system knows about one tool.

    `parameters` is provider-agnostic JSON Schema generated from the function
    signature; `export.py` wraps it per provider.

    `max_result_chars` exists because a tool that returns 200 KB of JSON does
    not fail — it quietly eats the context window and the next few turns
    degrade for no visible reason. Truncation is applied here and announced in
    the content.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    fn: Callable[..., Any]
    args_model: type[BaseModel]
    side_effect: bool = False
    requires_approval: bool = False
    timeout_s: float = 20.0
    max_result_chars: int = 8_000
    context_params: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_read_only(self) -> bool:
        return not self.side_effect
