"""The loop's invariants: every call answered, errors fed back, no half turns."""

from __future__ import annotations

import json

import pytest

from aimai_kit.agent import Agent, Budgets, ScriptedClient, StopReason, Thread
from aimai_kit.provider.types import Role
from aimai_kit.tools import CallContext, ToolExecutor, ToolRegistry, tool
from aimai_kit.tools.idempotency import call_signature

CALLS: list[str] = []


@tool
def lookup(order_id: str) -> str:
    """Fetch an order by id.

    To search without an id, use another tool.
    """
    CALLS.append(order_id)
    return f"order {order_id} is open"


@tool
def failing(x: int) -> str:
    """Always fail."""
    raise RuntimeError("upstream is down")


@tool(side_effect=True, requires_approval=True)
def cancel(order_id: str) -> str:
    """Cancel an order. Has a side effect."""
    CALLS.append(f"cancel:{order_id}")
    return f"cancelled {order_id}"


@pytest.fixture(autouse=True)
def _reset():
    CALLS.clear()
    yield
    CALLS.clear()


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([lookup, failing, cancel]))


def _tool_messages(thread: Thread) -> list[dict]:
    return [json.loads(m.content) for m in thread.messages if m.role is Role.TOOL]


def test_a_simple_task_completes(executor) -> None:
    client = ScriptedClient(
        [[("lookup", '{"order_id": "1002"}')], "Order 1002 is open."]
    )
    result = Agent(client, executor).run(Thread(), "status of 1002?")
    assert result.stop_reason is StopReason.FINISHED
    assert result.answer == "Order 1002 is open."
    assert CALLS == ["1002"]


def test_answer_without_tools_finishes_immediately(executor) -> None:
    client = ScriptedClient(["No tool needed."])
    result = Agent(client, executor).run(Thread(), "hello")
    assert result.stop_reason is StopReason.FINISHED
    assert result.thread.step == 1
    assert CALLS == []


def test_every_tool_call_gets_a_result(executor) -> None:
    """A turn with three calls and two results is a broken conversation."""
    client = ScriptedClient(
        [
            [
                ("lookup", '{"order_id": "1"}'),
                ("lookup", "{broken json"),
                ("nonexistent", "{}"),
            ],
            "done",
        ]
    )
    result = Agent(client, executor).run(Thread(), "task")
    results = _tool_messages(result.thread)
    assert len(results) == 3
    assert [r["ok"] for r in results] == [True, False, False]
    assert [r["error_code"] for r in results] == [None, "bad_json", "no_such_tool"]


def test_tool_error_reaches_the_model(executor) -> None:
    """The model can only recover from an error it is shown."""
    client = ScriptedClient([[("failing", '{"x": 1}')], "I could not do that."])
    result = Agent(client, executor).run(Thread(), "task")
    (payload,) = _tool_messages(result.thread)
    assert payload["ok"] is False
    assert "upstream is down" in payload["content"]
    assert result.stop_reason is StopReason.FINISHED


def test_tool_error_ceiling_stops_the_run(executor) -> None:
    client = ScriptedClient(
        [[("failing", f'{{"x": {i}}}')] for i in range(10)] + ["giving up"]
    )
    agent = Agent(client, executor, max_tool_errors=3, budgets=Budgets(max_steps=20))
    result = agent.run(Thread(), "task")
    assert result.stop_reason is StopReason.TOOL_ERROR_CEILING
    assert result.thread.spend.tool_errors >= 3


def test_approval_gate_pauses_the_run(executor) -> None:
    client = ScriptedClient([[("cancel", '{"order_id": "1002"}')], "done"])
    result = Agent(client, executor).run(Thread(), "cancel 1002")
    assert result.stop_reason is StopReason.NEEDS_APPROVAL
    assert result.thread.pending_approval == call_signature(
        "cancel", {"order_id": "1002"}
    )
    assert CALLS == [], "the side effect must not have happened"


def test_run_resumes_after_approval(executor) -> None:
    """The same thread continues once the call is approved.

    The model asks for the same call again on the resumed run, which is what
    a real one does: from its side nothing has happened yet.
    """
    client = ScriptedClient(
        [
            [("cancel", '{"order_id": "1002"}')],
            [("cancel", '{"order_id": "1002"}')],
            "cancelled",
        ]
    )
    thread = Thread()
    first = Agent(client, executor).run(thread, "cancel 1002")
    assert first.stop_reason is StopReason.NEEDS_APPROVAL

    approved = CallContext(approved_calls=frozenset({thread.pending_approval}))
    second = Agent(client, executor).run(thread, ctx=approved)
    assert second.stop_reason is StopReason.FINISHED
    assert CALLS == ["cancel:1002"]


def test_allowlist_narrows_the_declared_tools(executor) -> None:
    client = ScriptedClient(["done"])
    agent = Agent(client, executor, allowlist=["lookup"])
    agent.run(Thread(), "task")
    declared = {t["name"] for t in client.requests[0].tools}
    assert declared == {"lookup"}


def test_spend_is_accounted_in_one_place(executor) -> None:
    client = ScriptedClient([[("lookup", '{"order_id": "1"}')], "done"])
    result = Agent(client, executor).run(Thread(), "task")
    # Two model calls at 600 tokens each.
    assert result.thread.spend.tokens == 1200
    assert result.thread.spend.steps == 2


def test_events_are_emitted(executor) -> None:
    seen: list[str] = []
    client = ScriptedClient([[("lookup", '{"order_id": "1"}')], "done"])
    agent = Agent(client, executor, on_event=lambda e: seen.append(e.kind))
    agent.run(Thread(), "task")
    assert "step" in seen and "tool_result" in seen and "finished" in seen


def test_model_failure_does_not_crash_the_run(executor) -> None:
    class Exploding(ScriptedClient):
        def complete(self, req):
            raise RuntimeError("network gone")

    result = Agent(Exploding([]), executor).run(Thread(), "task")
    assert result.stop_reason is StopReason.CANCELLED
    assert any(e.kind == "model_error" for e in result.thread.trace)
