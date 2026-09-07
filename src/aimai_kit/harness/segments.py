"""Segments — the atomic unit of context is not a message.

A tool call and its result are one thing. Dropping the result while keeping
the call leaves the model looking at a request it never got an answer to;
dropping the call while keeping the result leaves an answer to a question
nobody asked. Most providers reject the first shape outright, and the ones
that do not produce confused output.

So the unit that gets trimmed is a SEGMENT: one or more messages that must
live or die together. Everything downstream — the fill ratio, the trim order,
compaction — operates on segments, and the pairing invariant is then free
rather than something each of those has to remember.

`droppable` marks what may be removed. The prefix (system prompt, tool
declarations, the original task) is never droppable, which is what makes
"trim from the end" a safe rule rather than a hopeful one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from ..provider.types import Message, Role

__all__ = ["SegmentKind", "Segment", "segments_from_messages"]


class SegmentKind(StrEnum):
    SYSTEM = "system"
    TASK = "task"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_TURN = "tool_turn"
    COMPACTED = "compacted"


@dataclass
class Segment:
    """A group of messages that must be kept or dropped together."""

    kind: SegmentKind
    messages: list[Message] = field(default_factory=list)
    tokens: int = 0
    droppable: bool = True
    step: int = 0

    @property
    def text(self) -> str:
        return "\n".join(m.content for m in self.messages)

    def __len__(self) -> int:
        return len(self.messages)


def segments_from_messages(
    messages: Sequence[Message], *, counter=None, keep_first_user: bool = True
) -> list[Segment]:
    """Group a flat message list into segments.

    An assistant turn that requested tools is joined to the tool results that
    followed it. That grouping is done here rather than tracked as the
    conversation is built, so a thread restored from a checkpoint segments the
    same way as a live one.

    `keep_first_user` marks the original task as non-droppable. An agent that
    forgets what it was asked will confidently answer a different question,
    and that failure is invisible in every metric except the answer itself.
    """
    segments: list[Segment] = []
    seen_user = False

    for message in messages:
        if message.role is Role.SYSTEM:
            segments.append(Segment(SegmentKind.SYSTEM, [message], droppable=False))
            continue

        if message.role is Role.USER:
            first = not seen_user
            seen_user = True
            segments.append(
                Segment(
                    SegmentKind.TASK if first else SegmentKind.USER,
                    [message],
                    droppable=not (first and keep_first_user),
                )
            )
            continue

        if message.role is Role.TOOL:
            # Attach to the assistant turn that requested it; if there is no
            # such turn (a restored partial thread), stand alone rather than
            # silently discard.
            if segments and segments[-1].kind in (
                SegmentKind.ASSISTANT,
                SegmentKind.TOOL_TURN,
            ):
                segments[-1].kind = SegmentKind.TOOL_TURN
                segments[-1].messages.append(message)
            else:
                segments.append(Segment(SegmentKind.TOOL_TURN, [message]))
            continue

        segments.append(Segment(SegmentKind.ASSISTANT, [message]))

    if counter is not None:
        for segment in segments:
            segment.tokens = counter.count_messages(
                [m.as_dict() for m in segment.messages]
            )
    return segments
