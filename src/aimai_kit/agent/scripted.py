"""A scripted client for deterministic loop tests.

Testing an agent loop against a real model tests the model. Testing it against
a scripted sequence tests the loop, which is the part that has invariants:
every tool call gets a result, the third repeat stops the run, a budget stop
still produces an answer.

The script is a list of turns. A turn is either a string (a final answer) or a
list of (tool_name, arguments_json) pairs (a tool-calling turn). When the
script runs out, the last entry repeats — which is exactly what you want for
"and now it loops forever" tests.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from ..provider.types import ChatRequest, ChatResult, ToolCall, Usage

__all__ = ["ScriptedClient", "Turn"]

Turn = str | Sequence[tuple[str, str]]


@dataclass
class ScriptedClient:
    """Replays a fixed sequence of model turns."""

    script: list[Turn]
    provider: str = "scripted"
    model: str = "scripted-v1"
    usage: Usage = field(
        default_factory=lambda: Usage(input_tokens=500, output_tokens=100)
    )
    requests: list[ChatRequest] = field(default_factory=list)

    def _turn(self) -> Turn:
        index = min(len(self.requests) - 1, len(self.script) - 1)
        return self.script[index]

    def complete(self, req: ChatRequest) -> ChatResult:
        self.requests.append(req)
        turn = self._turn()

        if isinstance(turn, str):
            return ChatResult(
                text=turn,
                usage=self.usage,
                provider=self.provider,
                model=self.model,
                finish_reason="end_turn",
            )

        return ChatResult(
            text="",
            usage=self.usage,
            provider=self.provider,
            model=self.model,
            finish_reason="tool_use",
            tool_calls=tuple(
                ToolCall(id=f"call_{len(self.requests)}_{i}", name=name, arguments=args)
                for i, (name, args) in enumerate(turn)
            ),
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        yield self.complete(req).text

    @property
    def call_count(self) -> int:
        return len(self.requests)
