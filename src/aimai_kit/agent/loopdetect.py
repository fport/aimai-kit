"""Signature-based loop detection.

The failure mode this catches is specific and common: an agent calls
`get_order(id=42)`, does not like the answer, and calls `get_order(id=42)`
again. Nothing errors. Every step looks healthy. The budget drains.

Detection needs a stable identity for "the same call", which the tool layer
already provides — the call signature is the tool name plus normalized
arguments, so argument reordering does not disguise a repeat.

The response is graduated, and that matters:

    2nd occurrence  a warning is injected INTO the tool result
    3rd occurrence  the run stops with `loop_detected`

Warning before stopping is the useful part. A model that is told "this call
returned the same result as before; try a different approach" frequently does
try a different approach, and the run completes. Stopping at the second
occurrence would kill runs that were about to recover; never stopping turns a
stuck run into a full budget burn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["LoopDetector", "REPEAT_WARNING"]

REPEAT_WARNING = (
    "\n\n[note: this exact call was already made earlier in this run and "
    "returned the same result. Repeating it will not produce new information. "
    "Use a different tool, different arguments, or answer with what you have.]"
)


@dataclass
class LoopDetector:
    """Counts repeated call signatures within one run."""

    warn_at: int = 2
    stop_at: int = 3
    counts: dict[str, int] = field(default_factory=dict)

    def observe(self, signature: str) -> int:
        """Record an occurrence and return how many times it has been seen."""
        self.counts[signature] = self.counts.get(signature, 0) + 1
        return self.counts[signature]

    def should_warn(self, occurrences: int) -> bool:
        return self.warn_at <= occurrences < self.stop_at

    def should_stop(self, occurrences: int) -> bool:
        return occurrences >= self.stop_at

    @property
    def repeated_signatures(self) -> list[str]:
        return [sig for sig, count in self.counts.items() if count > 1]

    def as_dict(self) -> dict[str, int]:
        return dict(self.counts)

    @classmethod
    def from_dict(
        cls, data: dict, *, warn_at: int = 2, stop_at: int = 3
    ) -> LoopDetector:
        return cls(
            warn_at=warn_at,
            stop_at=stop_at,
            counts={k: int(v) for k, v in data.items()},
        )
