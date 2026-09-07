"""Segments: a tool call and its result are never separated."""

from __future__ import annotations

import pytest

from aimai_kit.harness.context import ContextManager
from aimai_kit.harness.segments import SegmentKind, segments_from_messages
from aimai_kit.provider.counting import TokenCounter
from aimai_kit.provider.types import Message, Role


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


CONVERSATION = [
    _msg(Role.USER, "find the status of order 1002"),
    _msg(Role.ASSISTANT, "calling get_order"),
    _msg(Role.TOOL, '{"ok": true, "content": "order 1002 is open"}'),
    _msg(Role.ASSISTANT, "calling get_customer"),
    _msg(Role.TOOL, '{"ok": true, "content": "customer c-100"}'),
    _msg(Role.ASSISTANT, "Order 1002 is open for c-100."),
]


def test_tool_call_and_result_form_one_segment() -> None:
    segments = segments_from_messages(CONVERSATION)
    tool_turns = [s for s in segments if s.kind is SegmentKind.TOOL_TURN]
    assert len(tool_turns) == 2
    for segment in tool_turns:
        roles = [m.role for m in segment.messages]
        assert roles == [Role.ASSISTANT, Role.TOOL]


def test_the_original_task_is_not_droppable() -> None:
    """An agent that forgets the question answers a different one."""
    segments = segments_from_messages(CONVERSATION)
    task = segments[0]
    assert task.kind is SegmentKind.TASK
    assert task.droppable is False


def test_later_user_messages_are_droppable() -> None:
    messages = [*CONVERSATION, _msg(Role.USER, "and the tier?")]
    segments = segments_from_messages(messages)
    assert segments[-1].kind is SegmentKind.USER
    assert segments[-1].droppable is True


def test_system_segments_are_never_droppable() -> None:
    segments = segments_from_messages([_msg(Role.SYSTEM, "you are an assistant")])
    assert segments[0].droppable is False


def test_orphan_tool_result_stands_alone() -> None:
    """A partial thread restored from a checkpoint must not lose data."""
    segments = segments_from_messages([_msg(Role.TOOL, "orphan result")])
    assert len(segments) == 1
    assert segments[0].kind is SegmentKind.TOOL_TURN


def test_token_counts_are_attached_when_a_counter_is_given() -> None:
    segments = segments_from_messages(CONVERSATION, counter=TokenCounter("gpt-4o"))
    assert all(s.tokens > 0 for s in segments)


# --- context manager -----------------------------------------------------


@pytest.fixture
def long_conversation() -> list[Message]:
    messages = [_msg(Role.USER, "the original task")]
    for i in range(40):
        messages.append(_msg(Role.ASSISTANT, f"calling tool {i}"))
        messages.append(_msg(Role.TOOL, f"result {i}: " + "x " * 400))
    messages.append(_msg(Role.ASSISTANT, "final answer"))
    return messages


def test_context_fits_the_window(long_conversation) -> None:
    manager = ContextManager(window=4_000, output_reserve=500)
    kept, stats = manager.build(long_conversation)
    assert stats.input_tokens <= manager.limit
    assert stats.dropped_segments > 0


def test_trimming_never_splits_a_tool_pair(long_conversation) -> None:
    """The invariant the whole segment model exists to protect."""
    manager = ContextManager(window=4_000, output_reserve=500)
    kept, _ = manager.build(long_conversation)

    for index, message in enumerate(kept):
        if message.role is Role.TOOL:
            assert index > 0, "a tool result cannot be the first message"
            assert kept[index - 1].role is Role.ASSISTANT


def test_the_task_survives_any_trim(long_conversation) -> None:
    manager = ContextManager(window=2_000, output_reserve=200)
    kept, _ = manager.build(long_conversation)
    assert kept[0].content == "the original task"


def test_the_most_recent_turn_survives(long_conversation) -> None:
    """Without it the model has no idea what it was just doing."""
    manager = ContextManager(window=2_000, output_reserve=200)
    kept, _ = manager.build(long_conversation)
    assert kept[-1].content == "final answer"


def test_short_conversation_is_untouched() -> None:
    manager = ContextManager(window=200_000, output_reserve=4_000)
    kept, stats = manager.build(CONVERSATION)
    assert len(kept) == len(CONVERSATION)
    assert stats.dropped_segments == 0


def test_fill_ratio_is_recorded_every_step(long_conversation) -> None:
    """A run that sits at 0.92 has not failed yet; that is the point."""
    manager = ContextManager(window=20_000, output_reserve=2_000)
    for step in range(3):
        manager.build(long_conversation, step=step)
    assert len(manager.history) == 3
    assert manager.peak_fill_ratio > 0
    assert 0.0 <= manager.fill_percentile(95) <= 1.0
