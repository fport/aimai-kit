"""Run state — everything an agent knows, in one serializable object.

The `Agent` is stateless and the `Thread` holds everything. That split is not
stylistic: a stateless agent can be shared across concurrent requests, and a
run whose entire state is one object has a checkpoint for free.

"Checkpointing" here is not a subsystem. It is `to_dict` and `from_dict`. If
state were spread across the agent, the executor and a few module-level
caches, checkpointing would need a design; keeping it in one object means it
needs a serializer.

The trace is part of the state rather than a logging side channel, for the
same reason: a run you can resume but not explain is only half recoverable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..provider.types import Message, Role
from .budget import Spend
from .loopdetect import LoopDetector

__all__ = ["TraceEvent", "Thread"]


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One thing that happened, in a shape a dashboard can group by.

    `ok` is separate from `kind` because "a tool ran" and "a tool ran and
    failed" are the same event with different outcomes, and forcing them into
    different kinds makes every consumer special-case them.
    """

    kind: str
    detail: str = ""
    ok: bool = True
    step: int = 0
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "ok": self.ok,
            "step": self.step,
            "at": self.at,
        }


@dataclass
class Thread:
    """All state for one run.

    `tool_results` caches side-effecting results by call signature so a run
    resumed from a checkpoint does not repeat work that already happened. The
    limit is worth stating plainly: the process can die after the tool ran and
    before the checkpoint was written. This narrows the window; only an
    idempotent tool closes it.
    """

    goal: str = ""
    messages: list[Message] = field(default_factory=list)
    step: int = 0
    spend: Spend = field(default_factory=Spend)
    trace: list[TraceEvent] = field(default_factory=list)
    tool_results: dict[str, str] = field(default_factory=dict)
    detector: LoopDetector = field(default_factory=LoopDetector)
    stop_reason: str | None = None
    answer: str = ""
    pending_approval: str | None = None
    compaction_count: int = 0

    # --- mutation ---------------------------------------------------------

    def add(self, role: Role, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

    def record(self, kind: str, detail: str = "", *, ok: bool = True) -> TraceEvent:
        event = TraceEvent(kind=kind, detail=detail, ok=ok, step=self.step)
        self.trace.append(event)
        return event

    # --- serialization ----------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in self.messages
            ],
            "step": self.step,
            "spend": self.spend.as_dict(),
            "trace": [e.as_dict() for e in self.trace],
            "tool_results": self.tool_results,
            "detector": self.detector.as_dict(),
            "stop_reason": self.stop_reason,
            "answer": self.answer,
            "pending_approval": self.pending_approval,
            "compaction_count": self.compaction_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Thread:
        return cls(
            goal=data.get("goal", ""),
            messages=[
                Message(role=Role(m["role"]), content=m["content"])
                for m in data.get("messages", [])
            ],
            step=int(data.get("step", 0)),
            spend=Spend.from_dict(data.get("spend", {})),
            trace=[TraceEvent(**e) for e in data.get("trace", [])],
            tool_results=dict(data.get("tool_results", {})),
            detector=LoopDetector.from_dict(data.get("detector", {})),
            stop_reason=data.get("stop_reason"),
            answer=data.get("answer", ""),
            pending_approval=data.get("pending_approval"),
            compaction_count=int(data.get("compaction_count", 0)),
        )

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, raw: str) -> Thread:
        return cls.from_dict(json.loads(raw))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> Thread:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
