"""Run metrics, and the order in which to read them.

Seven numbers, and reading them in the wrong order wastes days. The order is:

    1. loop_rate          are runs getting stuck?
    2. budget_stop_rate   are they being cut off?
    3. recovery_rate      do they survive a tool failure?

Loop rate comes first because a loop inflates everything downstream: steps,
cost, and the budget stop rate. Tuning budgets while the loop rate is high
means raising the ceiling on wasted work.

Budget stop rate comes second. A high rate with a low loop rate means the
budget is genuinely too tight; the same rate with a high loop rate means it is
doing its job.

Recovery rate comes last and is the most interesting: it is the share of runs
that hit a tool error and still finished. A low recovery rate says the error
messages the tool layer produces are not actionable — which is a prompt and
tool-description problem, not a budget one.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .budget import StopReason
from .thread import Thread

__all__ = ["RunMetrics", "run_metrics"]


@dataclass
class RunMetrics:
    runs: int = 0
    completion_rate: float = 0.0
    steps_p50: float = 0.0
    steps_p95: float = 0.0
    tool_error_rate: float = 0.0
    loop_rate: float = 0.0
    budget_stop_rate: float = 0.0
    recovery_rate: float = 0.0
    mean_usd: str = "0"

    def as_dict(self) -> dict[str, object]:
        return {
            "runs": self.runs,
            "completion_rate": self.completion_rate,
            "steps_p50": self.steps_p50,
            "steps_p95": self.steps_p95,
            "tool_error_rate": self.tool_error_rate,
            "loop_rate": self.loop_rate,
            "budget_stop_rate": self.budget_stop_rate,
            "recovery_rate": self.recovery_rate,
            "mean_usd": self.mean_usd,
        }


def _percentile(values: Sequence[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered)) - 1))
    return ordered[index]


def run_metrics(threads: Sequence[Thread]) -> RunMetrics:
    """Aggregate a batch of finished runs."""
    if not threads:
        return RunMetrics()

    total = len(threads)
    steps = [float(t.step) for t in threads]
    finished = sum(t.stop_reason == StopReason.FINISHED for t in threads)
    looped = sum(t.stop_reason == StopReason.LOOP_DETECTED for t in threads)
    budget_stopped = sum(
        StopReason(t.stop_reason).is_budget for t in threads if t.stop_reason
    )

    tool_events = [e for t in threads for e in t.trace if e.kind == "tool_result"]
    tool_errors = sum(not e.ok for e in tool_events)

    # A run "recovered" if it saw a tool error and still finished. Runs that
    # never hit an error are excluded from the denominator — including them
    # would make the rate a measure of how rarely tools fail.
    had_errors = [
        t for t in threads if any(e.kind == "tool_result" and not e.ok for e in t.trace)
    ]
    recovered = sum(t.stop_reason == StopReason.FINISHED for t in had_errors)

    mean_usd = (
        sum((t.spend.usd for t in threads), Decimal(0)) / Decimal(total)
        if total
        else Decimal(0)
    )

    return RunMetrics(
        runs=total,
        completion_rate=round(finished / total, 3),
        steps_p50=round(statistics.median(steps), 2),
        steps_p95=round(_percentile(steps, 95), 2),
        tool_error_rate=(
            round(tool_errors / len(tool_events), 3) if tool_events else 0.0
        ),
        loop_rate=round(looped / total, 3),
        budget_stop_rate=round(budget_stopped / total, 3),
        recovery_rate=round(recovered / len(had_errors), 3) if had_errors else 1.0,
        mean_usd=f"{mean_usd:.6f}",
    )
