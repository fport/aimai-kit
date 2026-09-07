"""A stub summarizer that follows the prompt it is given.

Needle tests need a summarizer whose behavior depends on the prompt, or the
comparison between two compaction prompts measures nothing. A real model
would do that; a stub that ignores the prompt would not.

So this one reads its instructions. When the prompt asks for a "Facts and
figures" section, it extracts identifiers and numbers from the transcript and
puts them there. When the prompt only says "keep it short", it keeps the first
sentences — which is exactly the failure mode a vague compaction prompt
produces in practice: a summary that reads fine and has quietly dropped every
number.

Not a model. It exists so the difference between two prompts is reproducible
and testable without spending anything.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from ..provider.types import ChatRequest, ChatResult, Usage

__all__ = ["StubSummarizer"]

# Identifier-shaped and quantity-shaped tokens: the things a summary must not
# paraphrase away.
# Alternation order matters: the ISO-date branch has to come before the bare
# number branch, or "2025-03-14" is captured as three separate integers and
# the date is silently destroyed by the thing meant to preserve it.
_FACT_RE = re.compile(
    r"(?:spill://[0-9a-f]+|\b\d{4}-\d{2}-\d{2}\b|\b[A-Z]{2,}-\d+\b|"
    r"\b[a-z]{2,}-\d{2,}\b|\b\d[\d,]*(?:\.\d+)?%?\b)"
)
_TRANSCRIPT_RE = re.compile(r"Conversation to compress:\s*(.*)", re.S)


@dataclass
class StubSummarizer:
    """Summarizes according to what the prompt asks for."""

    provider: str = "stub"
    model: str = "stub-summarizer-v1"
    max_facts: int = 40
    prompts_seen: list[str] = field(default_factory=list)

    def complete(self, req: ChatRequest) -> ChatResult:
        prompt = req.messages[-1].content if req.messages else ""
        self.prompts_seen.append(prompt)

        match = _TRANSCRIPT_RE.search(prompt)
        transcript = match.group(1) if match else prompt
        structured = "Facts and figures" in prompt

        if structured:
            facts = list(dict.fromkeys(_FACT_RE.findall(transcript)))[: self.max_facts]
            body = (
                "## Decisions\n- continued the task\n\n"
                "## Constraints\n- none\n\n"
                "## Facts and figures\n"
                + ("\n".join(f"- {f}" for f in facts) or "- none")
                + "\n\n## Open questions\n- none\n\n## Tried and rejected\n- none"
            )
        else:
            # The vague-prompt failure mode: prose that reads well and has
            # dropped every number.
            sentences = [s.strip() for s in transcript.split(".") if s.strip()]
            body = ". ".join(sentences[:2])[:400]

        return ChatResult(
            text=body,
            usage=Usage(input_tokens=len(prompt) // 4, output_tokens=len(body) // 4),
            provider=self.provider,
            model=self.model,
            prompt_ref=req.prompt_ref,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        yield self.complete(req).text
