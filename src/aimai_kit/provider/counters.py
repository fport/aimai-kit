"""In-process counters — not a replacement for Prometheus, a preparation.

The need right now is small: "how often did we fall back?", "which section
did we trim and how often?" — answers readable from a test and from the CLI.

Labeled counters rather than flat names, because "a trim happened" is not
useful; WHICH section was trimmed is. A counter that does not carry labels
from the start has to be rewritten the moment something goes wrong.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Mapping

__all__ = ["Counters", "COUNTERS"]


class Counters:
    """Thread-safe labeled counter store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()

    @staticmethod
    def _key(name: str, labels: Mapping[str, str]) -> tuple:
        return (name, tuple(sorted(labels.items())))

    def increment(self, name: str, /, value: int = 1, **labels: str) -> None:
        with self._lock:
            self._values[self._key(name, labels)] += value

    def get(self, name: str, **labels: str) -> int:
        with self._lock:
            return self._values[self._key(name, labels)]

    def total(self, name: str) -> int:
        """Sum across all label combinations."""
        with self._lock:
            return sum(v for (n, _), v in self._values.items() if n == name)

    def snapshot(self) -> dict[str, int]:
        """Flattened copy for reporting: 'name{k=v,k=v}' -> value."""
        with self._lock:
            out = {}
            for (name, labels), value in sorted(self._values.items()):
                if labels:
                    suffix = ",".join(f"{k}={v}" for k, v in labels)
                    out[f"{name}{{{suffix}}}"] = value
                else:
                    out[name] = value
            return out

    def reset(self) -> None:
        """Tests only. Counters are never reset in production."""
        with self._lock:
            self._values.clear()


COUNTERS = Counters()
