"""Checkpointing: the whole run state is one serializable object."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aimai_kit.agent import Agent, ScriptedClient, StopReason, Thread
from aimai_kit.provider.types import Role
from aimai_kit.tools import CallContext, ToolExecutor, ToolRegistry, tool

SIDE_EFFECTS: list[str] = []


@tool
def lookup(order_id: str) -> str:
    """Fetch an order by id.

    To search without an id, use another tool.
    """
    return f"order {order_id} is open"


@tool(side_effect=True)
def charge(order_id: str) -> str:
    """Charge an order. Has a side effect."""
    SIDE_EFFECTS.append(order_id)
    return f"charged {order_id}"


@pytest.fixture(autouse=True)
def _reset():
    SIDE_EFFECTS.clear()
    yield
    SIDE_EFFECTS.clear()


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([lookup, charge]))


def test_thread_round_trips_through_json(executor) -> None:
    client = ScriptedClient([[("lookup", '{"order_id": "1"}')], "done"])
    thread = Thread()
    Agent(client, executor).run(thread, "task")

    restored = Thread.from_json(thread.to_json())
    assert restored.goal == thread.goal
    assert [m.content for m in restored.messages] == [
        m.content for m in thread.messages
    ]
    assert restored.step == thread.step
    assert restored.stop_reason == thread.stop_reason
    assert restored.spend.tokens == thread.spend.tokens


def test_decimal_spend_survives_the_round_trip() -> None:
    thread = Thread()
    thread.spend.usd = Decimal("0.001234")
    restored = Thread.from_json(thread.to_json())
    assert restored.spend.usd == Decimal("0.001234")
    assert isinstance(restored.spend.usd, Decimal)


def test_trace_survives_the_round_trip(executor) -> None:
    """A run you can resume but not explain is only half recovered."""
    client = ScriptedClient([[("lookup", '{"order_id": "1"}')], "done"])
    thread = Thread()
    Agent(client, executor).run(thread, "task")

    restored = Thread.from_json(thread.to_json())
    assert [e.kind for e in restored.trace] == [e.kind for e in thread.trace]
    assert [e.ok for e in restored.trace] == [e.ok for e in thread.trace]


def test_checkpoint_written_to_disk(executor, tmp_path) -> None:
    client = ScriptedClient([[("lookup", '{"order_id": "1"}')], "done"])
    thread = Thread()
    Agent(client, executor).run(thread, "task")

    path = thread.save(tmp_path / "run" / "thread.json")
    assert path.is_file()
    assert Thread.load(path).answer == thread.answer


def test_resumed_run_does_not_repeat_a_side_effect(executor) -> None:
    """The guarantee, and its limit.

    The side-effect result is cached by call signature, so a resumed run that
    replays the same call gets the stored result instead of charging twice.
    The window this does NOT close: the process can die after the tool ran and
    before the checkpoint was written. Only an idempotent tool closes that.
    """
    call = [("charge", '{"order_id": "1002"}')]
    client = ScriptedClient([call, "charged"])
    thread = Thread()
    Agent(client, executor).run(thread, "charge 1002")
    assert SIDE_EFFECTS == ["1002"]

    resumed = Thread.from_json(thread.to_json())
    client2 = ScriptedClient([call, "charged again"])
    result = Agent(client2, executor).run(resumed, ctx=CallContext())
    assert result.stop_reason is StopReason.FINISHED
    assert SIDE_EFFECTS == ["1002"], "the side effect must not run twice"


def test_resume_continues_the_same_conversation(executor) -> None:
    client = ScriptedClient([[("lookup", '{"order_id": "1"}')], "first answer"])
    thread = Thread()
    Agent(client, executor).run(thread, "first task")
    first_length = len(thread.messages)

    restored = Thread.from_json(thread.to_json())
    client2 = ScriptedClient(["second answer"])
    Agent(client2, executor).run(restored, "second task")

    assert len(restored.messages) > first_length
    assert restored.messages[0].content == "first task"
    assert restored.messages[0].role is Role.USER
    assert restored.answer == "second answer"


def test_empty_thread_round_trips() -> None:
    assert Thread.from_json(Thread().to_json()).step == 0
