"""Compaction — summarizing old turns instead of dropping them.

Trimming loses information. Compaction converts it: the oldest segments are
replaced with one summary segment, and the run continues with room to work.

Three decisions shape it.

**Threshold-triggered, not per-step.** Compacting every step spends a model
call to save tokens that were not scarce yet. The trigger is a fill ratio.

**Triggered at a step boundary, ideally while waiting for the user.** A
compaction in the middle of a tool turn would separate a call from its
result — the exact thing the segment model exists to prevent.

**The prompt is a versioned file.** Compaction is a lossy transformation
applied to the agent's own memory, so "which version of the summarizer
produced this state?" has to be answerable. It goes through the same registry
as every other prompt, with the same fingerprint.

What is preserved is stated explicitly in the prompt rather than left to the
model's judgment: decisions, constraints, numbers, open questions, failed
approaches, references. A summary that reads well and drops a number is worse
than no summary, because it looks trustworthy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..prompts.registry import PromptRegistry
from ..provider.client import LLMClient
from ..provider.counters import COUNTERS
from ..provider.types import ChatRequest, Message, Role
from .segments import Segment, SegmentKind

__all__ = ["CompactionResult", "Compactor"]


@dataclass
class CompactionResult:
    segments: list[Segment]
    compacted_count: int
    summary: str
    tokens_before: int
    tokens_after: int

    @property
    def saved_tokens(self) -> int:
        return self.tokens_before - self.tokens_after


@dataclass
class Compactor:
    """Replaces old segments with one summary segment."""

    client: LLMClient
    registry: PromptRegistry
    prompt_key: str = "compaction@v2"
    trigger_ratio: float = 0.75
    keep_recent: int = 4
    max_words: int = 400
    max_output_tokens: int = 1_200

    def should_compact(self, fill_ratio: float, segments: Sequence[Segment]) -> bool:
        """Compact when the window is filling AND there is enough history.

        Both conditions matter: compacting a short conversation spends a call
        to summarize four turns into three.
        """
        droppable = [s for s in segments if s.droppable and s.messages]
        return fill_ratio >= self.trigger_ratio and len(droppable) > self.keep_recent

    def compact(self, segments: Sequence[Segment]) -> CompactionResult:
        """Summarize everything except the prefix and the most recent turns."""
        segments = list(segments)
        tokens_before = sum(s.tokens for s in segments)

        keep_head = [s for s in segments if not s.droppable]
        droppable = [s for s in segments if s.droppable and s.messages]
        to_compact = droppable[: max(0, len(droppable) - self.keep_recent)]
        keep_tail = droppable[len(to_compact) :]

        if not to_compact:
            return CompactionResult(segments, 0, "", tokens_before, tokens_before)

        transcript = "\n\n".join(f"[{s.kind.value}] {s.text}" for s in to_compact)
        rendered, ref = self.registry.render(
            self.prompt_key, transcript=transcript, max_words=self.max_words
        )
        result = self.client.complete(
            ChatRequest(
                messages=[Message(role=Role.USER, content=rendered)],
                max_output_tokens=self.max_output_tokens,
                prompt_ref=str(ref),
                operation="compaction",
            )
        )

        summary_segment = Segment(
            kind=SegmentKind.COMPACTED,
            messages=[
                Message(
                    role=Role.USER,
                    content=(
                        "[earlier turns, compacted]\n"
                        f"{result.text}\n"
                        f"[compacted by {ref}]"
                    ),
                )
            ],
            # The summary itself is droppable: if the window fills again it
            # can be compacted a second time. Marking it permanent would make
            # long runs impossible.
            droppable=True,
        )

        COUNTERS.increment("compaction_total", prompt=str(ref))
        rebuilt = [*keep_head, summary_segment, *keep_tail]
        return CompactionResult(
            segments=rebuilt,
            compacted_count=len(to_compact),
            summary=result.text,
            tokens_before=tokens_before,
            tokens_after=sum(s.tokens for s in rebuilt),
        )
