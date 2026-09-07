"""Harness layer: everything that keeps a long run from drowning in its own
context.

The agent loop bounds a run. This layer makes a long one survivable: segments
so trimming cannot split a tool call from its result, spill so a large result
does not have to fit in the window, compaction so history can be converted
rather than lost, a memory store with a deterministic write gate, and
sub-agents so reading-heavy work happens somewhere else.
"""

from .compaction import CompactionResult, Compactor
from .context import ContextManager, ContextStats
from .memory import MemoryKind, MemoryRecord, MemoryStore, WriteRefused
from .sandbox import Sandbox, SandboxViolation
from .segments import Segment, SegmentKind, segments_from_messages
from .spill import SpillStore, build_spill_tools
from .subagent import Subagent, SubagentReport, SubagentResult

__all__ = [
    "Compactor",
    "CompactionResult",
    "ContextManager",
    "ContextStats",
    "MemoryKind",
    "MemoryRecord",
    "MemoryStore",
    "WriteRefused",
    "Sandbox",
    "SandboxViolation",
    "Segment",
    "SegmentKind",
    "segments_from_messages",
    "SpillStore",
    "build_spill_tools",
    "Subagent",
    "SubagentReport",
    "SubagentResult",
]
