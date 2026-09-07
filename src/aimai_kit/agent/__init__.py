"""Agent layer: a bounded loop over the tool layer.

The loop owns very little on purpose. Tool execution, request construction,
telemetry and loop detection each live behind their own seam, so each can be
tested without starting a run — and so the loop stays short enough to read in
one sitting.
"""

from .budget import Budgets, Spend, StopReason
from .loop import Agent, RunResult
from .loopdetect import LoopDetector
from .metrics import RunMetrics, run_metrics
from .scripted import ScriptedClient
from .thread import Thread, TraceEvent

__all__ = [
    "Agent",
    "Budgets",
    "LoopDetector",
    "RunMetrics",
    "RunResult",
    "ScriptedClient",
    "Spend",
    "StopReason",
    "Thread",
    "TraceEvent",
    "run_metrics",
]
