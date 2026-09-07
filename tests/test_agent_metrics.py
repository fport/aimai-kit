"""Run metrics and the order they are meant to be read in."""

from __future__ import annotations

from decimal import Decimal

from aimai_kit.agent import StopReason, Thread, run_metrics
from aimai_kit.agent.thread import TraceEvent


def _thread(stop: StopReason, *, steps: int = 3, tool_ok: list[bool] | None = None):
    thread = Thread(goal="t")
    thread.step = steps
    thread.stop_reason = stop.value
    thread.spend.usd = Decimal("0.01")
    for ok in tool_ok or []:
        thread.trace.append(TraceEvent(kind="tool_result", ok=ok))
    return thread


def test_empty_input_is_safe() -> None:
    assert run_metrics([]).runs == 0


def test_completion_rate() -> None:
    threads = [
        _thread(StopReason.FINISHED),
        _thread(StopReason.FINISHED),
        _thread(StopReason.STEP_BUDGET),
        _thread(StopReason.LOOP_DETECTED),
    ]
    metrics = run_metrics(threads)
    assert metrics.runs == 4
    assert metrics.completion_rate == 0.5


def test_loop_and_budget_rates_are_separate() -> None:
    """A high budget-stop rate means something different when loops are high."""
    threads = [
        _thread(StopReason.LOOP_DETECTED),
        _thread(StopReason.STEP_BUDGET),
        _thread(StopReason.TIME_BUDGET),
        _thread(StopReason.FINISHED),
    ]
    metrics = run_metrics(threads)
    assert metrics.loop_rate == 0.25
    assert metrics.budget_stop_rate == 0.5


def test_recovery_rate_excludes_runs_that_never_failed() -> None:
    """Including them would measure how rarely tools fail, not recovery."""
    threads = [
        _thread(StopReason.FINISHED, tool_ok=[True, False]),  # recovered
        _thread(StopReason.TOOL_ERROR_CEILING, tool_ok=[False, False]),  # did not
        _thread(StopReason.FINISHED, tool_ok=[True, True]),  # never failed
    ]
    metrics = run_metrics(threads)
    assert metrics.recovery_rate == 0.5


def test_recovery_rate_is_one_when_nothing_failed() -> None:
    metrics = run_metrics([_thread(StopReason.FINISHED, tool_ok=[True])])
    assert metrics.recovery_rate == 1.0


def test_tool_error_rate_is_per_call_not_per_run() -> None:
    threads = [_thread(StopReason.FINISHED, tool_ok=[True, True, False, True])]
    assert run_metrics(threads).tool_error_rate == 0.25


def test_step_percentiles() -> None:
    threads = [_thread(StopReason.FINISHED, steps=s) for s in (1, 2, 3, 4, 100)]
    metrics = run_metrics(threads)
    assert metrics.steps_p50 == 3.0
    assert metrics.steps_p95 == 100.0


def test_mean_cost_is_reported_as_a_decimal_string() -> None:
    metrics = run_metrics([_thread(StopReason.FINISHED)] * 2)
    assert metrics.mean_usd == "0.010000"
