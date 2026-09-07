"""Tool layer: declaration, export, and safe execution.

The three responsibilities are deliberately separate files, because they are
answers to three different questions:

    declaration (`decorator`, `registry`) — what exists, and who may see it
    export      (`export`)                — how each provider wants to be told
    execution   (`executor`)              — what actually happens, and safely

Collapsing them into one class is the common shortcut, and it is why tool
authorization so often ends up living inside the agent loop, where it cannot
be tested on its own.
"""

from .decorator import tool
from .executor import CallContext, ToolExecutor
from .export import export_for, to_anthropic, to_openai_chat, to_openai_responses
from .idempotency import IdempotencyStore, call_signature
from .registry import ToolRegistry
from .spec import ERROR_CODES, ToolResult, ToolSpec

__all__ = [
    "tool",
    "CallContext",
    "ToolExecutor",
    "export_for",
    "to_anthropic",
    "to_openai_chat",
    "to_openai_responses",
    "IdempotencyStore",
    "call_signature",
    "ToolRegistry",
    "ERROR_CODES",
    "ToolResult",
    "ToolSpec",
]
