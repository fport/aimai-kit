"""The five gates, timeout, truncation and context injection."""

from __future__ import annotations

import time

import pytest

from aimai_kit.provider.counters import COUNTERS
from aimai_kit.tools import CallContext, ToolExecutor, ToolRegistry, tool
from aimai_kit.tools.idempotency import call_signature


@tool
def lookup(order_id: str) -> str:
    """Fetch an order by id.

    To search without an id, use another tool.
    """
    return f"order {order_id}"


@tool
def scoped(ctx: CallContext, order_id: str) -> str:
    """Fetch an order within the caller's tenant."""
    return f"{ctx.tenant_id}:{order_id}"


@tool(timeout_s=0.05)
def slow(seconds: float) -> str:
    """Sleep for a while."""
    time.sleep(seconds)
    return "finished"


@tool(max_result_chars=50)
def verbose(size: int) -> str:
    """Return a lot of text."""
    return "x" * size


@tool
def explodes(x: int) -> str:
    """Always fail."""
    raise RuntimeError("upstream is down")


@tool(side_effect=True, requires_approval=True)
def mutate(order_id: str) -> str:
    """Change something. Has a side effect."""
    return f"changed {order_id}"


@pytest.fixture(autouse=True)
def _reset_counters():
    COUNTERS.reset()
    yield
    COUNTERS.reset()


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([lookup, scoped, slow, verbose, explodes, mutate]))


# --- gate 1: does the tool exist? ---------------------------------------


def test_unknown_tool_lists_the_available_ones(executor) -> None:
    """A model that mistyped a name fixes itself on the next turn."""
    result = executor.call("get_ordr", "{}")
    assert result.error_code == "no_such_tool"
    assert "lookup" in result.content
    assert result.retryable is True


# --- gate 2: is the caller allowed? -------------------------------------


def test_disallowed_tool_is_refused(executor) -> None:
    result = executor.call("mutate", '{"order_id": "1"}', allowlist=["lookup"])
    assert result.error_code == "not_allowed"
    assert result.retryable is False


def test_refusal_does_not_disclose_the_tool_name(executor) -> None:
    """Telling an unauthorized caller a tool exists is a disclosure."""
    result = executor.call("mutate", '{"order_id": "1"}', allowlist=["lookup"])
    assert "mutate" not in result.content


# --- gate 3: is it parseable JSON? --------------------------------------


def test_malformed_json_is_reported_usefully(executor) -> None:
    result = executor.call("lookup", "{not json")
    assert result.error_code == "bad_json"
    assert result.retryable is True
    assert "JSON" in result.content


def test_non_object_json_is_rejected(executor) -> None:
    result = executor.call("lookup", "[1, 2, 3]")
    assert result.error_code == "bad_json"


# --- gate 4: does it match the schema? ----------------------------------


def test_schema_violation_names_the_field(executor) -> None:
    result = executor.call("lookup", '{"wrong_field": 1}')
    assert result.error_code == "bad_args"
    assert "order_id" in result.content
    assert result.retryable is True, "the model can correct its own arguments"


# --- gate 5: does it need approval? -------------------------------------


def test_approval_required_stops_the_call(executor) -> None:
    result = executor.call("mutate", '{"order_id": "1"}')
    assert result.error_code == "needs_approval"
    assert result.retryable is False


def test_approved_signature_passes_the_gate(executor) -> None:
    signature = call_signature("mutate", {"order_id": "1"})
    ctx = CallContext(approved_calls=frozenset({signature}))
    result = executor.call("mutate", '{"order_id": "1"}', ctx)
    assert result.ok and "changed 1" in result.content


# --- after the gates ----------------------------------------------------


def test_context_is_injected_from_the_call_not_the_arguments(executor) -> None:
    """The model cannot claim to be another tenant."""
    ctx = CallContext(user_id="u-1", tenant_id="t-9")
    result = executor.call("scoped", '{"order_id": "1"}', ctx)
    assert result.content == "t-9:1"
    assert "tenant_id" not in str(executor.registry.get("scoped").parameters)


def test_argument_supplied_tenant_is_ignored(executor) -> None:
    """Even if the model sends one, the schema rejects the extra field."""
    ctx = CallContext(tenant_id="t-1")
    result = executor.call("scoped", '{"order_id": "1", "tenant_id": "t-evil"}', ctx)
    assert result.ok
    assert result.content == "t-1:1"


def test_timeout_produces_a_result_not_a_hang(executor) -> None:
    result = executor.call("slow", '{"seconds": 1.0}')
    assert result.error_code == "timeout"
    assert result.retryable is True


def test_tool_exception_becomes_data(executor) -> None:
    """A failing tool is a result the loop can reason about, not a crash."""
    result = executor.call("explodes", '{"x": 1}')
    assert result.error_code == "tool_error"
    assert "upstream is down" in result.content
    assert result.ok is False


def test_traceback_never_reaches_the_model(executor) -> None:
    result = executor.call("explodes", '{"x": 1}')
    assert "Traceback" not in result.content
    assert 'File "' not in result.content


def test_truncation_is_announced(executor) -> None:
    """Silent truncation produces answers built on half a document."""
    result = executor.call("verbose", '{"size": 500}')
    assert result.ok
    assert "truncated" in result.content
    assert len(result.content) < 500


def test_short_result_is_not_touched(executor) -> None:
    result = executor.call("verbose", '{"size": 10}')
    assert result.content == "x" * 10


def test_raw_is_kept_off_the_content(executor) -> None:
    """`raw` goes to the trace; only `content` reaches the model."""
    result = executor.call("verbose", '{"size": 500}')
    assert result.raw is not None
    assert len(result.raw) == 500
    assert result.raw != result.content


def test_counters_are_labeled_with_the_error_code(executor) -> None:
    executor.call("lookup", '{"order_id": "1"}')
    executor.call("lookup", "{bad")
    assert COUNTERS.get("tool_calls_total", tool="lookup", code="ok") == 1
    assert COUNTERS.get("tool_calls_total", tool="lookup", code="bad_json") == 1


def test_call_many_keeps_partial_results(executor) -> None:
    """One failure must not lose the other results."""
    results = executor.call_many(
        [
            ("lookup", '{"order_id": "1"}'),
            ("lookup", "{broken"),
            ("lookup", '{"order_id": "3"}'),
        ]
    )
    assert [r.ok for r in results] == [True, False, True]
    assert results[0].content == "order 1"
    assert results[2].content == "order 3"


def test_call_many_preserves_order(executor) -> None:
    """Read-only calls run in parallel but come back in declaration order."""
    results = executor.call_many(
        [("lookup", f'{{"order_id": "{i}"}}') for i in range(5)]
    )
    assert [r.content for r in results] == [f"order {i}" for i in range(5)]
