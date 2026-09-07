"""Request construction — registry + blocks + guard + budget in one path.

The CLI and the eval harness must build the same request; if they each built
their own, what you measure and what you run would drift apart silently. This
module is that single path.

Block order (rationale in `blocks.py`):
    [SYSTEM]  prompt text -> trust-boundary instruction -> schema
    [USER]    wrapped document -> question
The system side does not change across requests; that is the cache prefix.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from ..provider.counting import TokenCounter
from ..provider.types import ChatRequest, Message, Role
from .blocks import prefix_signature, prefix_text, stable_system_blocks
from .budget import ContextBudget, Section, TrimReport
from .guard import TRUST_BOUNDARY_INSTRUCTION, untrusted_document
from .registry import PromptRef, PromptRegistry
from .schemas import strict_json_schema

__all__ = ["BuiltRequest", "build_request"]


@dataclass(frozen=True)
class BuiltRequest:
    req: ChatRequest
    ref: PromptRef
    report: TrimReport
    prefix_signature: str


def build_request(
    registry: PromptRegistry,
    prompt_key: str,
    document: str,
    *,
    doc_id: str = "1",
    question: str | None = None,
    schema: type[BaseModel] | None = None,
    window: int = 200_000,
    max_output_tokens: int = 2048,
    model: str = "gpt-4o",
    operation: str = "extract",
    **prompt_vars: object,
) -> BuiltRequest:
    """Render the prompt, block it, wrap the data, fit the budget, build the
    request."""
    system_text, ref = registry.render(prompt_key, **prompt_vars)

    blocks = stable_system_blocks(
        system_text,
        trust_instruction=TRUST_BOUNDARY_INSTRUCTION,
        schema=strict_json_schema(schema) if schema else None,
    )
    system = prefix_text(blocks)

    counter = TokenCounter(model)
    budget = ContextBudget(window, max_output_tokens, counter=counter)
    placement = budget.place(
        [
            # The system block is NON-TRIMMABLE: a system that continues with
            # half its instructions cannot explain a wrong answer.
            Section("system", system, priority=1, trimmable=False),
            Section(
                "document",
                untrusted_document(document, doc_id),
                priority=20,
                min_tokens=200,
            ),
            Section("question", question or "", priority=2, trimmable=False),
        ]
    )
    parts = dict(placement.parts)

    user_content = parts["document"]
    if parts.get("question"):
        user_content = f"{user_content}\n\n{parts['question']}"

    return BuiltRequest(
        req=ChatRequest(
            messages=[Message(role=Role.USER, content=user_content)],
            system=parts["system"],
            max_output_tokens=max_output_tokens,
            prompt_ref=str(ref),
            operation=operation,
        ),
        ref=ref,
        report=placement.report,
        prefix_signature=prefix_signature(blocks),
    )
