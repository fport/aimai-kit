"""Repeated calls: warn on the second, stop on the third."""

from __future__ import annotations

import json

import pytest

from aimai_kit.agent import Agent, Budgets, ScriptedClient, StopReason, Thread
from aimai_kit.agent.loopdetect import LoopDetector
from aimai_kit.provider.types import Role
from aimai_kit.tools import ToolExecutor, ToolRegistry, tool


@tool
def lookup(order_id: str) -> str:
    """Fetch an order by id.

    To search without an id, use another tool.
    """
    return f"order {order_id} is open"


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([lookup]))


def _tool_contents(thread: Thread) -> list[str]:
    return [
        json.loads(m.content)["content"] for m in thread.messages if m.role is Role.TOOL
    ]


def test_detector_counts_occurrences() -> None:
    detector = LoopDetector()
    assert detector.observe("a") == 1
    assert detector.observe("a") == 2
    assert detector.observe("b") == 1


def test_detector_graduates_from_warning_to_stop() -> None:
    detector = LoopDetector()
    assert not detector.should_warn(1) and not detector.should_stop(1)
    assert detector.should_warn(2) and not detector.should_stop(2)
    assert detector.should_stop(3)


def test_second_repeat_warns_inside_the_tool_result(executor) -> None:
    """The warning goes where the model is already looking."""
    same = [("lookup", '{"order_id": "1"}')]
    client = ScriptedClient([same, same, "I will try something else."])
    result = Agent(client, executor).run(Thread(), "task")

    contents = _tool_contents(result.thread)
    assert len(contents) == 2
    assert "already made earlier" in contents[1]
    assert result.stop_reason is StopReason.FINISHED


def test_third_repeat_stops_the_run(executor) -> None:
    same = [("lookup", '{"order_id": "1"}')]
    client = ScriptedClient([same, same, same, "unreachable"])
    result = Agent(
        client, executor, budgets=Budgets(max_steps=10, max_seconds=None)
    ).run(Thread(), "task")
    assert result.stop_reason is StopReason.LOOP_DETECTED
    assert any(e.kind == "loop_detected" for e in result.thread.trace)


def test_argument_order_does_not_disguise_a_repeat(executor) -> None:
    """Reordering keys is the same call; the signature has to see that."""

    @tool
    def pair(a: str, b: str) -> str:
        """Combine two values."""
        return a + b

    ex = ToolExecutor(ToolRegistry([pair]))
    client = ScriptedClient(
        [
            [("pair", '{"a": "1", "b": "2"}')],
            [("pair", '{"b": "2", "a": "1"}')],
            [("pair", '{"a": "1", "b": "2"}')],
            "unreachable",
        ]
    )
    result = Agent(client, ex, budgets=Budgets(max_steps=10, max_seconds=None)).run(
        Thread(), "task"
    )
    assert result.stop_reason is StopReason.LOOP_DETECTED


def test_different_arguments_are_not_a_loop(executor) -> None:
    client = ScriptedClient(
        [[("lookup", f'{{"order_id": "{i}"}}')] for i in range(4)] + ["done"]
    )
    result = Agent(
        client, executor, budgets=Budgets(max_steps=10, max_seconds=None)
    ).run(Thread(), "task")
    assert result.stop_reason is StopReason.FINISHED


def test_loop_stop_still_produces_an_answer(executor) -> None:
    """A stuck run should hand back what it has, not nothing."""
    same = [("lookup", '{"order_id": "1"}')]
    client = ScriptedClient([same, same, same, "partial answer"])
    result = Agent(
        client, executor, budgets=Budgets(max_steps=10, max_seconds=None)
    ).run(Thread(), "task")
    assert result.stop_reason is StopReason.LOOP_DETECTED
    assert result.answer == "partial answer"


def test_detector_survives_serialization(executor) -> None:
    """Loop counts must survive a checkpoint, or a resumed run forgets."""
    same = [("lookup", '{"order_id": "1"}')]
    client = ScriptedClient([same, same, "done"])
    thread = Thread()
    Agent(client, executor).run(thread, "task")

    restored = Thread.from_json(thread.to_json())
    assert restored.detector.counts == thread.detector.counts
    assert restored.detector.repeated_signatures
