"""Call signatures and the side-effect guard."""

from __future__ import annotations

import pytest

from aimai_kit.tools import CallContext, ToolExecutor, ToolRegistry, tool
from aimai_kit.tools.idempotency import IdempotencyStore, call_signature

CALLS: list[str] = []


@tool(side_effect=True)
def charge(order_id: str, amount_minor: int) -> str:
    """Charge an order. Has a side effect."""
    CALLS.append(order_id)
    return f"charged {order_id}"


@tool
def read(order_id: str) -> str:
    """Read an order."""
    CALLS.append(order_id)
    return f"read {order_id}"


@pytest.fixture(autouse=True)
def _reset():
    CALLS.clear()
    yield
    CALLS.clear()


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([charge, read]))


def test_signature_ignores_argument_order() -> None:
    """`{"a":1,"b":2}` and `{"b":2,"a":1}` are the same call."""
    assert call_signature("t", {"a": 1, "b": 2}) == call_signature(
        "t", {"b": 2, "a": 1}
    )


def test_signature_accepts_a_json_string() -> None:
    assert call_signature("t", '{"a": 1}') == call_signature("t", {"a": 1})


def test_different_arguments_give_different_signatures() -> None:
    assert call_signature("t", {"a": 1}) != call_signature("t", {"a": 2})


def test_different_tools_give_different_signatures() -> None:
    assert call_signature("a", {"x": 1}) != call_signature("b", {"x": 1})


def test_malformed_json_still_has_a_stable_signature() -> None:
    """Two identical malformed calls should still look identical."""
    assert call_signature("t", "{broken") == call_signature("t", "{broken")


def test_side_effect_runs_once_for_the_same_call(executor) -> None:
    args = '{"order_id": "1", "amount_minor": 100}'
    first = executor.call("charge", args)
    second = executor.call("charge", args)
    assert first.ok and second.ok
    assert CALLS == ["1"], "the side effect must not happen twice"


def test_different_arguments_run_again(executor) -> None:
    executor.call("charge", '{"order_id": "1", "amount_minor": 100}')
    executor.call("charge", '{"order_id": "2", "amount_minor": 100}')
    assert CALLS == ["1", "2"]


def test_read_only_calls_are_not_cached(executor) -> None:
    """Caching a read would hide data that changed between calls."""
    executor.call("read", '{"order_id": "1"}')
    executor.call("read", '{"order_id": "1"}')
    assert CALLS == ["1", "1"]


def test_failed_side_effect_is_not_stored() -> None:
    """A failure must not be replayed as if it were the answer."""

    @tool(side_effect=True)
    def flaky(order_id: str) -> str:
        """Fail once. Has a side effect."""
        CALLS.append(order_id)
        if len(CALLS) == 1:
            raise RuntimeError("transient")
        return "ok now"

    executor = ToolExecutor(ToolRegistry([flaky]))
    first = executor.call("flaky", '{"order_id": "1"}')
    second = executor.call("flaky", '{"order_id": "1"}')
    assert first.ok is False
    assert second.ok is True


def test_store_expires_entries() -> None:
    store = IdempotencyStore(ttl_s=0.0)
    from aimai_kit.tools.spec import ToolResult

    store.put("sig", ToolResult(ok=True, content="x"))
    assert store.get("sig") is None


def test_approval_is_keyed_by_signature() -> None:
    """Approving one call must not approve a different one."""

    @tool(side_effect=True, requires_approval=True)
    def cancel(order_id: str) -> str:
        """Cancel an order. Has a side effect."""
        return f"cancelled {order_id}"

    executor = ToolExecutor(ToolRegistry([cancel]))
    approved = call_signature("cancel", {"order_id": "1"})
    ctx = CallContext(approved_calls=frozenset({approved}))

    assert executor.call("cancel", '{"order_id": "1"}', ctx).ok
    assert (
        executor.call("cancel", '{"order_id": "2"}', ctx).error_code == "needs_approval"
    )
