"""Percentiles, latency report, cost per operation, determinism stats."""

from __future__ import annotations

from decimal import Decimal

from aimai_kit.provider.determinism import determinism_probe, stats_from_outputs
from aimai_kit.provider.telemetry import (
    UsageRecord,
    cost_per_operation,
    latency_report,
    percentiles,
)


def _record(**kwargs) -> UsageRecord:
    base = dict(
        provider="p", model="m", operation="chat", input_tokens=10, output_tokens=5
    )
    return UsageRecord(**{**base, **kwargs})


def test_percentile_returns_an_observed_value() -> None:
    """Nearest-rank: p95 must be a latency that was actually recorded."""
    values = [100.0, 200.0, 300.0, 400.0, 5000.0]
    result = percentiles(values)
    assert result[50] == 300.0
    assert result[95] in values
    assert result[99] in values


def test_empty_input_gives_empty_output() -> None:
    assert percentiles([]) == {}


def test_percentiles_expose_skew_that_the_mean_hides() -> None:
    """One run in twenty takes 10 seconds: the mean inflates, p50 stays blind.

    Under nearest-rank the p95 of twenty runs is the 19th element, still
    100 ms. A single outlier only shows up at p99. The lesson: "p95 is fine"
    does not mean "there are no bad runs" — with a small N, p95 swallows the
    outlier. Write N next to your SLO.
    """
    values = [100.0] * 19 + [10_000.0]
    mean = sum(values) / len(values)
    result = percentiles(values)
    assert result[50] == 100.0
    assert result[95] == 100.0, "at N=20 p95 cannot catch a single outlier"
    assert result[99] == 10_000.0
    assert result[50] < mean < result[99]


def test_latency_report_excludes_failed_calls() -> None:
    records = [
        _record(duration_ms=500.0, ttft_ms=100.0),
        _record(duration_ms=700.0, ttft_ms=140.0),
        _record(duration_ms=12.0, ok=False),  # a 429 returning fast
    ]
    report = latency_report(records)
    assert report["m"].n == 2
    # Nearest-rank at N=2: p50 is the first element, 500. Had the failed run's
    # 12 ms entered the list, p50 would read 12.0 and the service would look
    # faster than it has ever been.
    assert report["m"].duration_ms[50] == 500.0
    assert report["m"].duration_ms[95] == 700.0
    assert report["m"].ttft_ms[50] == 100.0


def test_cost_includes_failed_attempts() -> None:
    records = [
        _record(operation="summary", cost_usd=Decimal("0.10")),
        _record(operation="summary", cost_usd=Decimal("0.05")),
        _record(operation="extract", cost_usd=Decimal("0.20")),
        _record(operation="extract", cost_usd=Decimal("0.01"), ok=False),
    ]
    totals = cost_per_operation(records)
    assert totals["summary"] == Decimal("0.15")
    assert totals["extract"] == Decimal("0.21"), "a wasted attempt is still money"


def test_modal_share_is_more_informative_than_distinct_count() -> None:
    outputs = ["a"] * 8 + ["b", "c"]
    stats = stats_from_outputs(outputs)
    assert stats.distinct_outputs == 3
    assert stats.modal_share == 0.8
    assert stats.modal_output == "a"
    assert not stats.is_stable


def test_determinism_probe_calls_n_times() -> None:
    counter = {"n": 0}

    def call() -> str:
        counter["n"] += 1
        return "constant"

    stats = determinism_probe(call, n=4)
    assert counter["n"] == 4
    assert stats.is_stable and stats.modal_share == 1.0
