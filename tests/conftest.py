"""Shared test helpers.

`FakeClient` is the most-used tool in this suite: it satisfies the
`LLMClient` protocol without going near a real API. That it fits in a few
lines is not an accident — it is the payoff for keeping the protocol narrow.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from decimal import Decimal
from pathlib import Path

import pytest

# The golden sets under `evals/` are importable modules rather than plain data
# because a tool case carries an expected call sequence, which is code-shaped.
# Adding the directory once here keeps that detail out of every test file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from aimai_kit.provider.errors import LLMError
from aimai_kit.provider.pricing import ModelPricing
from aimai_kit.provider.types import ChatRequest, ChatResult, ToolCall, Usage


class FakeClient:
    """Returns pre-programmed responses (or raises) in order.

    An entry in `responses` that is an `Exception` is raised; anything else is
    returned as text. Once the list runs out the last entry repeats, which
    makes "and now it always succeeds" easy to express in a retry test.
    """

    def __init__(
        self,
        responses: Sequence[str | Exception | ChatResult],
        *,
        provider: str = "fake",
        model: str = "fake-model",
        usage: Usage | None = None,
    ) -> None:
        self._responses = list(responses)
        self.provider = provider
        self.model = model
        self.usage = usage or Usage(input_tokens=100, output_tokens=20)
        self.calls: list[ChatRequest] = []

    def _next(self) -> str | Exception | ChatResult:
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]

    def complete(self, req: ChatRequest) -> ChatResult:
        self.calls.append(req)
        value = self._next()
        if isinstance(value, Exception):
            raise value
        if isinstance(value, ChatResult):
            return value
        return ChatResult(
            text=value,
            usage=self.usage,
            provider=self.provider,
            model=self.model,
            prompt_ref=req.prompt_ref,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        yield self.complete(req).text

    @property
    def call_count(self) -> int:
        return len(self.calls)


def tool_response(
    calls: Sequence[tuple[str, str]], text: str = "", *, model: str = "fake-model"
) -> ChatResult:
    """Build a `ChatResult` that requests tool calls.

    Takes (name, arguments_json) pairs so a scripted agent test reads as the
    sequence of tool calls it is describing.
    """
    return ChatResult(
        text=text,
        usage=Usage(input_tokens=50, output_tokens=10),
        provider="fake",
        model=model,
        finish_reason="tool_use",
        tool_calls=tuple(
            ToolCall(id=f"call_{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(calls)
        ),
    )


@pytest.fixture
def fake_pricing() -> dict[str, ModelPricing]:
    return {
        "fake-model": ModelPricing(
            model="fake-model",
            input_per_mtok=Decimal("2.50"),
            output_per_mtok=Decimal("10.00"),
            cached_input_per_mtok=Decimal("0.25"),
            context_window=200_000,
        ),
        "backup-model": ModelPricing(
            model="backup-model",
            input_per_mtok=Decimal("1.00"),
            output_per_mtok=Decimal("5.00"),
            context_window=200_000,
        ),
    }


@pytest.fixture
def instant_sleep():
    """Disable real waiting in retry tests.

    The dependency is injected rather than patched: the production code does
    not need to know it is under test, it only needs the dependency to be
    replaceable from the outside.
    """
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)

    sleep.waits = waits  # type: ignore[attr-defined]
    return sleep


def make_error(cls: type[LLMError], **kwargs) -> LLMError:
    return cls("test error", **kwargs)
