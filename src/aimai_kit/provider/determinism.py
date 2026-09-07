"""Running the same prompt N times to measure output stability.

Why it matters: `temperature=0` does NOT mean deterministic. Batching order,
MoE routing and hardware differences can produce different output for the
same request. Measuring this before designing a feature around "let's cache
the model's answer" or "let's compare outputs as strings" prevents bug
reports nobody can explain later.

Two numbers:
  distinct_outputs — how many DIFFERENT texts came out of N runs.
  modal_share      — the share of the most frequent output. 1.0 means fully
                     stable.

`modal_share` is more informative on its own than `distinct_outputs`: three
distinct outputs in ten runs looks bad, but if eight of them are identical
(modal_share 0.8) the picture is completely different.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = ["DeterminismStats", "determinism_probe", "stats_from_outputs"]


@dataclass(frozen=True)
class DeterminismStats:
    n: int
    distinct_outputs: int
    modal_share: float
    modal_output: str = ""

    @property
    def is_stable(self) -> bool:
        return self.distinct_outputs <= 1


def stats_from_outputs(outputs: Sequence[str]) -> DeterminismStats:
    """Build stats from outputs that were already collected.

    Kept separate from `determinism_probe` because the CLI already runs N
    times to measure latency; producing the same outputs a second time would
    double the bill. The caller collects, this only counts.
    """
    if not outputs:
        return DeterminismStats(n=0, distinct_outputs=0, modal_share=0.0)
    counts = Counter(outputs)
    modal_text, modal_count = counts.most_common(1)[0]
    return DeterminismStats(
        n=len(outputs),
        distinct_outputs=len(counts),
        modal_share=modal_count / len(outputs),
        modal_output=modal_text,
    )


def determinism_probe(call: Callable[[], str], n: int = 5) -> DeterminismStats:
    """Run `call` n times and measure stability."""
    if n < 1:
        raise ValueError("n must be at least 1")
    return stats_from_outputs([call() for _ in range(n)])
