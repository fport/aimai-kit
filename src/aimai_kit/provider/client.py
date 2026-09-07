"""The LLMClient protocol — the seam everything else binds to.

This protocol is the single dependency of every layer above. It is
deliberately NARROW: two methods, two types. What needs to grow is the
request object, not the protocol.

`Protocol` rather than an abstract base class: adapters conform without
inheriting anything, and a fake client is three lines in a test file.
Conformance is checked by the type checker, not at runtime.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from .types import ChatRequest, ChatResult

__all__ = ["LLMClient"]


@runtime_checkable
class LLMClient(Protocol):
    """A synchronous client bound to one provider/model pair.

    `provider` and `model` are fields because the code that builds the
    telemetry record (`resilient.py`) has to know which client was called;
    asking the client is the right place, rather than returning it from every
    call.
    """

    provider: str
    model: str

    def complete(self, req: ChatRequest) -> ChatResult:
        """Complete the request and return a single result."""
        ...

    def stream(self, req: ChatRequest) -> Iterator[str]:
        """Yield the response as text chunks.

        Text chunks only. Tool-call events, thinking blocks and partial JSON
        would bind the protocol to an event model nobody needs yet.
        """
        ...
