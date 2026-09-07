"""Sub-agents — delegating reading so the main context stays small.

The problem is specific: a task that requires reading thirty documents fills
the main agent's window with material it needs once. By document twenty the
agent is compacting away its own findings.

A sub-agent runs the reading in its OWN thread with its OWN window, and
returns a schema-constrained report. The main agent receives a summary and
citations, not the documents. The measure of whether this is working is the
ratio of tokens spent inside the sub-agent to tokens returned — a sub-agent
that returns most of what it read has not delegated anything.

The return is schema-constrained rather than free text for the same reason
extraction is: a sub-agent that answers in prose gives the main agent
something to interpret rather than something to use. And `evidence` is
verified programmatically — a sub-agent that cites a reference nobody can
resolve is worse than one that admits it found nothing.

Only one level. A sub-agent cannot spawn a sub-agent. That restriction is not
technical; nested delegation makes cost and failure impossible to reason
about, and every attempt to allow it ends with a depth limit anyway.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..agent.budget import Budgets
from ..agent.loop import Agent
from ..agent.thread import Thread
from ..provider.client import LLMClient
from ..tools.executor import CallContext, ToolExecutor

__all__ = ["SubagentReport", "SubagentResult", "Subagent"]


class SubagentReport(BaseModel):
    """What a sub-agent is allowed to return."""

    summary: str = Field(
        description=(
            "What you found, in at most five sentences. State findings, not "
            "process; the caller does not need to know which tools you used."
        )
    )
    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Identifiers the caller can resolve: order ids, document ids, "
            "spill:// references. Never invent one; an empty list is a valid "
            "answer."
        ),
    )
    confident: bool = Field(
        default=True,
        description=(
            "False when the sources were incomplete or contradictory. The "
            "caller decides what to do with a low-confidence report; hiding "
            "the doubt removes that choice."
        ),
    )


@dataclass
class SubagentResult:
    report: SubagentReport
    tokens_spent: int
    tokens_returned: int
    verified_evidence: list[str] = field(default_factory=list)
    unverified_evidence: list[str] = field(default_factory=list)

    @property
    def compression_ratio(self) -> float:
        """Tokens spent inside per token returned. Higher is better.

        A ratio near 1.0 means the sub-agent returned everything it read,
        which is delegation in name only.
        """
        if not self.tokens_returned:
            return 0.0
        return round(self.tokens_spent / self.tokens_returned, 2)


@dataclass
class Subagent:
    """Runs a narrow task in its own thread and returns a constrained report."""

    client: LLMClient
    executor: ToolExecutor
    allowlist: Sequence[str]
    system: str = (
        "You are a research sub-agent. Investigate exactly what you are asked, "
        "then stop. Report findings, not process. Never invent an identifier."
    )
    budgets: Budgets = field(
        default_factory=lambda: Budgets(max_steps=8, max_seconds=60.0)
    )

    def run(self, task: str, *, ctx: CallContext | None = None) -> SubagentResult:
        """Run the task and return a verified report."""
        from ..prompts.structured import generate_structured
        from ..provider.types import ChatRequest, Message, Role

        thread = Thread()
        agent = Agent(
            self.client,
            self.executor,
            system=self.system,
            budgets=self.budgets,
            allowlist=list(self.allowlist),
        )
        run = agent.run(thread, task, ctx=ctx)

        # A second, schema-bound call turns the free-form ending into a
        # report. Asking for structure during the loop would fight with tool
        # calling; asking for it after is one extra cheap call.
        structured = generate_structured(
            self.client,
            ChatRequest(
                messages=[
                    Message(
                        role=Role.USER,
                        content=(
                            "Summarize your findings as a report.\n\n"
                            f"Task: {task}\n\nWhat you found:\n{run.answer}"
                        ),
                    )
                ],
                max_output_tokens=1_024,
                operation="subagent_report",
            ),
            SubagentReport,
            max_attempts=2,
        )

        report = structured.value
        verified, unverified = self._verify(report.evidence, thread)
        if unverified:
            # Rather than fail, drop the unresolvable references and lower
            # confidence. The caller sees a smaller honest report.
            report = report.model_copy(
                update={"evidence": verified, "confident": False}
            )

        return SubagentResult(
            report=report,
            tokens_spent=thread.spend.tokens,
            tokens_returned=len(report.summary) // 4,
            verified_evidence=verified,
            unverified_evidence=unverified,
        )

    @staticmethod
    def _verify(evidence: Sequence[str], thread: Thread) -> tuple[list[str], list[str]]:
        """Every cited identifier must appear in what the sub-agent actually saw."""
        transcript = "\n".join(m.content for m in thread.messages)
        verified = [ref for ref in evidence if ref and ref in transcript]
        unverified = [ref for ref in evidence if ref not in verified]
        return verified, unverified
