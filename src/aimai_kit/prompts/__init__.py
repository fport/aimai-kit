"""Prompt and context engineering layer.

This layer disciplines WHAT we send to the model (registry, blocks, budget,
guard) and WHAT we accept back (schemas, structured, grounding). It builds on
the provider layer's `LLMClient` protocol and never touches a vendor SDK.
"""

from .budget import BudgetExceeded, ContextBudget, Section, TrimReport
from .guard import TRUST_BOUNDARY_INSTRUCTION, untrusted_document
from .pipeline import BuiltRequest, build_request
from .registry import PromptRef, PromptRegistry
from .structured import RepairResult, generate_structured

__all__ = [
    "BudgetExceeded",
    "ContextBudget",
    "Section",
    "TrimReport",
    "TRUST_BOUNDARY_INSTRUCTION",
    "untrusted_document",
    "BuiltRequest",
    "build_request",
    "PromptRef",
    "PromptRegistry",
    "RepairResult",
    "generate_structured",
]
