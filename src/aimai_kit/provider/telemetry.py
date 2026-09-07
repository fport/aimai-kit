"""Usage records and latency/cost reports.

Averages lie. Latency in an LLM service is skewed; what users feel is p95.
So the report functions here return p50/p95/p99 rather than a mean.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

__all__ = [
    "UsageRecord",
    "LatencySummary",
    "percentiles",
    "latency_report",
    "cost_per_operation",
    "UsageCollector",
]


@dataclass(frozen=True)
class UsageRecord:
    """Accounting record for a single LLM call.

    `ttft_ms` and `duration_ms` are measured SEPARATELY: TTFT describes
    perceived speed, duration describes total resource consumption. Do not
    collapse them into one number.

    `prompt_ref`, `schema_fingerprint` and `attempt` exist because a repair
    loop makes several calls for one logical job. Without `attempt` the
    "average attempts" metric cannot be computed; without `prompt_ref` the
    question "is v2 better than v1?" cannot be measured. Each is one field;
    adding them later would invalidate every stored eval record.
    """

    provider: str
    model: str
    operation: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    ttft_ms: float | None = None
    duration_ms: float = 0.0
    ok: bool = True
    prompt_ref: str | None = None
    schema_fingerprint: str | None = None
    attempt: int = 1
    error_type: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class LatencySummary:
    """Latency profile for one model.

    TTFT and total duration live in separate fields. Squeezing both into one
    dict would require composite keys like "model:ttft" and string parsing on
    every read.
    """

    n: int
    ttft_ms: dict[int, float]
    duration_ms: dict[int, float]


def percentiles(
    values: Sequence[float], ps: Sequence[int] = (50, 95, 99)
) -> dict[int, float]:
    """Compute the requested percentiles. Empty input gives an empty dict.

    Nearest-rank, not linear interpolation. On a small run (N=5)
    interpolation invents a value that was never observed, and when we say
    "p95 latency is 812 ms" we want 812 to be a real measurement.
    """
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    out: dict[int, float] = {}
    for p in ps:
        rank = max(1, math.ceil(p / 100 * n))
        out[p] = ordered[rank - 1]
    return out


def latency_report(
    records: Sequence[UsageRecord], ps: Sequence[int] = (50, 95, 99)
) -> dict[str, LatencySummary]:
    """Per-model TTFT and total-duration percentiles.

    Failed calls (`ok=False`) are excluded: a 429 returning in 40 ms does not
    mean the service is fast, it means it did no work. Mixing those in
    improves p50 dishonestly.
    """
    groups: dict[str, list[UsageRecord]] = {}
    for r in records:
        if r.ok:
            groups.setdefault(r.model, []).append(r)

    return {
        model: LatencySummary(
            n=len(rows),
            ttft_ms=percentiles([r.ttft_ms for r in rows if r.ttft_ms is not None], ps),
            duration_ms=percentiles([r.duration_ms for r in rows], ps),
        )
        for model, rows in groups.items()
    }


def cost_per_operation(records: Sequence[UsageRecord]) -> dict[str, Decimal]:
    """Total cost grouped by the `operation` field.

    This answers "which feature is burning money".

    Failed calls ARE counted here: input tokens may still have been billed on
    a 500, and the wasted attempts of a repair loop are real money. Unlike
    the latency report, dropping them would make the system look cheaper than
    it is.
    """
    totals: dict[str, Decimal] = {}
    for r in records:
        totals[r.operation] = totals.get(r.operation, Decimal(0)) + r.cost_usd
    return totals


class UsageCollector:
    """A simple callback that accumulates records.

    Plugged in as `ResilientClient(on_usage=collector)`. In production a
    metrics exporter or a database writer takes its place; as long as the
    signature is the same, the caller does not change.
    """

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def __call__(self, record: UsageRecord) -> None:
        self.records.append(record)

    @property
    def total_cost(self) -> Decimal:
        return sum((r.cost_usd for r in self.records), Decimal(0))
