"""Needle tests: does compaction preserve the facts it promised to?

The test plants a known fact early in a conversation, buries it under noise
until compaction triggers, then checks whether the fact survived. Three
different needles, because a summarizer that happens to keep one number is not
the same as one that keeps numbers.

The two prompt versions are compared directly. That comparison is the point:
"we compact the context" is not a claim you can act on, while "v1 loses 3 of 3
planted facts and v2 loses 0" tells you which prompt to ship.
"""

from __future__ import annotations

import pytest

from aimai_kit.harness.compaction import Compactor
from aimai_kit.harness.segments import SegmentKind, segments_from_messages
from aimai_kit.harness.stub_summarizer import StubSummarizer
from aimai_kit.prompts.registry import PromptRegistry
from aimai_kit.provider.counting import TokenCounter
from aimai_kit.provider.types import Message, Role

NEEDLES = [
    ("order id", "The affected order is ORD-88421 and it must not be cancelled."),
    ("amount", "The agreed cap is 125,000 for the whole engagement."),
    ("date", "The contract was signed on 2025-03-14 and cannot be backdated."),
]


def _conversation(needle: str, noise_turns: int = 14) -> list[Message]:
    messages = [
        Message(role=Role.USER, content="Investigate the account and report back."),
        Message(role=Role.ASSISTANT, content=needle),
    ]
    for i in range(noise_turns):
        messages.append(Message(role=Role.ASSISTANT, content=f"checking source {i}"))
        messages.append(
            Message(role=Role.TOOL, content=f"source {i} returned nothing relevant")
        )
    messages.append(Message(role=Role.ASSISTANT, content="still working"))
    return messages


@pytest.fixture
def registry() -> PromptRegistry:
    return PromptRegistry("prompts")


def _compact(registry: PromptRegistry, prompt_key: str, needle: str):
    counter = TokenCounter("gpt-4o")
    segments = segments_from_messages(_conversation(needle), counter=counter)
    compactor = Compactor(
        StubSummarizer(), registry, prompt_key=prompt_key, keep_recent=2
    )
    return compactor.compact(segments)


@pytest.mark.parametrize(("label", "needle"), NEEDLES, ids=[n[0] for n in NEEDLES])
def test_v2_preserves_the_needle(registry, label: str, needle: str) -> None:
    result = _compact(registry, "compaction@v2", needle)
    numbers = [t.rstrip(".") for t in needle.split() if any(c.isdigit() for c in t)]
    assert numbers, "the test needs a needle containing a figure"
    assert any(n in result.summary for n in numbers), (
        f"v2 lost the {label}: {result.summary[:200]}"
    )


@pytest.mark.parametrize(("label", "needle"), NEEDLES, ids=[n[0] for n in NEEDLES])
def test_v1_loses_the_needle(registry, label: str, needle: str) -> None:
    """The comparison that makes the v2 prompt worth its length."""
    result = _compact(registry, "compaction@v1", needle)
    numbers = [t.rstrip(".") for t in needle.split() if any(c.isdigit() for c in t)]
    assert not any(n in result.summary for n in numbers), (
        f"v1 unexpectedly kept the {label}; the comparison is no longer valid"
    )


def test_compaction_reduces_tokens(registry) -> None:
    result = _compact(registry, "compaction@v2", NEEDLES[0][1])
    assert result.compacted_count > 0
    assert result.tokens_after < result.tokens_before
    assert result.saved_tokens > 0


def test_compaction_keeps_the_prefix(registry) -> None:
    """The original task is never summarized away."""
    result = _compact(registry, "compaction@v2", NEEDLES[0][1])
    first = result.segments[0]
    assert first.droppable is False
    assert "Investigate the account" in first.text


def test_compaction_keeps_recent_turns(registry) -> None:
    result = _compact(registry, "compaction@v2", NEEDLES[0][1])
    assert "still working" in result.segments[-1].text


def test_summary_segment_is_itself_droppable(registry) -> None:
    """A permanent summary would make very long runs impossible."""
    result = _compact(registry, "compaction@v2", NEEDLES[0][1])
    summary = next(s for s in result.segments if s.kind is SegmentKind.COMPACTED)
    assert summary.droppable is True


def test_summary_records_the_prompt_version(registry) -> None:
    """A lossy transform on the agent's memory has to be traceable."""
    result = _compact(registry, "compaction@v2", NEEDLES[0][1])
    summary = next(s for s in result.segments if s.kind is SegmentKind.COMPACTED)
    assert "compaction@v2+" in summary.text


def test_trigger_needs_both_pressure_and_history(registry) -> None:
    """Compacting a short conversation spends a call to save nothing."""
    compactor = Compactor(StubSummarizer(), registry, trigger_ratio=0.75, keep_recent=4)
    short = segments_from_messages(_conversation(NEEDLES[0][1], noise_turns=1))
    long = segments_from_messages(_conversation(NEEDLES[0][1], noise_turns=20))

    assert not compactor.should_compact(0.9, short), "too little history"
    assert not compactor.should_compact(0.3, long), "no pressure yet"
    assert compactor.should_compact(0.9, long)


def test_nothing_to_compact_is_a_no_op(registry) -> None:
    compactor = Compactor(StubSummarizer(), registry, keep_recent=100)
    segments = segments_from_messages(_conversation(NEEDLES[0][1]))
    result = compactor.compact(segments)
    assert result.compacted_count == 0
    assert result.segments == segments
