"""Context manager — fill ratio, trim order, and a prefix that never moves.

Two rules, and the second one is the reason the first one is safe:

    trim from the END, always
    never touch the prefix

Trimming from the end preserves the cache prefix, and the cache prefix is
worth more than the tokens the trim recovers. Dropping something from the
middle of the conversation invalidates every cached token after it, so a trim
that saves 2,000 tokens can cost 40,000 in reprocessing.

The fill ratio is reported per step rather than only when something goes
wrong. A run that sits at 0.92 for thirty steps has not failed, but it is one
long tool result away from failing, and the only way to know that in advance
is to have been watching the ratio.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..provider.counters import COUNTERS
from ..provider.counting import TokenCounter
from ..provider.types import Message
from .segments import Segment, SegmentKind, segments_from_messages

__all__ = ["ContextStats", "ContextManager"]


@dataclass
class ContextStats:
    """What one step's context looked like. Emitted every step, not on failure."""

    step: int = 0
    input_tokens: int = 0
    fill_ratio: float = 0.0
    segments: int = 0
    dropped_segments: int = 0
    compacted: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "input_tokens": self.input_tokens,
            "fill_ratio": round(self.fill_ratio, 3),
            "segments": self.segments,
            "dropped_segments": self.dropped_segments,
            "compacted": self.compacted,
        }


@dataclass
class ContextManager:
    """Turns a thread's messages into the message list that goes to the model."""

    window: int = 200_000
    output_reserve: int = 4_000
    counter: TokenCounter = field(default_factory=lambda: TokenCounter("gpt-4o"))
    history: list[ContextStats] = field(default_factory=list)

    @property
    def limit(self) -> int:
        return max(0, self.window - self.output_reserve)

    def build(
        self, messages: Sequence[Message], *, step: int = 0
    ) -> tuple[list[Message], ContextStats]:
        """Fit the conversation into the window, trimming from the end.

        "From the end" means the OLDEST droppable segments after the prefix
        are removed first. The prefix stays, the most recent turns stay, and
        what goes is the middle-aged history — which is also what compaction
        is for, and why the two work on the same segment list.
        """
        segments = segments_from_messages(messages, counter=self.counter)
        total = sum(s.tokens for s in segments)
        dropped = 0

        if total > self.limit:
            # Walk oldest-first through the droppable segments only.
            for segment in segments:
                if total <= self.limit:
                    break
                if not segment.droppable:
                    continue
                if segment is segments[-1]:
                    # Never drop the most recent turn; without it the model
                    # has no idea what it was just doing.
                    continue
                total -= segment.tokens
                segment.messages = []
                dropped += 1
                COUNTERS.increment(
                    "context_segments_dropped_total", kind=segment.kind.value
                )

        kept = [m for s in segments for m in s.messages]
        stats = ContextStats(
            step=step,
            input_tokens=total,
            fill_ratio=total / self.limit if self.limit else 0.0,
            segments=sum(1 for s in segments if s.messages),
            dropped_segments=dropped,
        )
        self.history.append(stats)
        return kept, stats

    @property
    def peak_fill_ratio(self) -> float:
        return max((s.fill_ratio for s in self.history), default=0.0)

    def fill_percentile(self, p: int = 95) -> float:
        """p95 fill ratio.

        Sitting above 0.9 consistently does not mean the run failed; it means
        the budget is wrong and the next long tool result will make it fail.
        """
        if not self.history:
            return 0.0
        ordered = sorted(s.fill_ratio for s in self.history)
        index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered)) - 1))
        return round(ordered[index], 3)


def prefix_segments(segments: Sequence[Segment]) -> list[Segment]:
    """The segments that must never move: system blocks and the original task."""
    return [
        s
        for s in segments
        if not s.droppable or s.kind in (SegmentKind.SYSTEM, SegmentKind.TASK)
    ]
