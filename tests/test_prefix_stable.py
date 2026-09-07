"""Is the cache prefix byte-stable?

The value of this test shows up the day it breaks: the moment a timestamp, a
request id or an unsorted dict leaks into the system prompt, the cache hit
rate drops to zero and the bill quietly multiplies. The system keeps working,
so nobody notices — except this test.
"""

from __future__ import annotations

from aimai_kit.prompts.blocks import (
    prefix_signature,
    prefix_text,
    stable_system_blocks,
)
from aimai_kit.prompts.guard import TRUST_BOUNDARY_INSTRUCTION
from aimai_kit.prompts.pipeline import build_request
from aimai_kit.prompts.registry import PromptRegistry
from aimai_kit.prompts.schemas import ContractSummary

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}

# Pinned DELIBERATELY. If you need to change it, first ask whether you meant
# to change the prefix; if yes, updating this is one line.
EXPECTED_SIGNATURE = "49672143fb759d1f"


def _blocks() -> tuple[str, ...]:
    return stable_system_blocks(
        "You are a legal assistant.",
        trust_instruction=TRUST_BOUNDARY_INSTRUCTION,
        schema=SCHEMA,
        examples=("input -> output",),
    )


def test_prefix_is_byte_identical() -> None:
    assert prefix_text(_blocks()) == prefix_text(_blocks())


def test_signature_equals_a_pinned_value() -> None:
    assert prefix_signature(_blocks()) == EXPECTED_SIGNATURE


def test_schema_key_order_does_not_change_the_prefix() -> None:
    """Without `sort_keys` the same schema would produce different bytes."""
    reordered = {"properties": {"a": {"type": "string"}}, "type": "object"}
    a = stable_system_blocks("S", schema=SCHEMA)
    b = stable_system_blocks("S", schema=reordered)
    assert prefix_signature(a) == prefix_signature(b)


def test_a_variable_field_breaks_the_signature() -> None:
    """The inverse check that proves this test does something."""
    leaky = stable_system_blocks(
        "You are a legal assistant. Today is 2026-09-07.",
        trust_instruction=TRUST_BOUNDARY_INSTRUCTION,
        schema=SCHEMA,
        examples=("input -> output",),
    )
    assert prefix_signature(leaky) != EXPECTED_SIGNATURE


def test_different_documents_share_the_same_system_prefix() -> None:
    """The core claim: two different documents, one cache prefix."""
    registry = PromptRegistry("prompts")
    a = build_request(
        registry, "extract_contract@v2", "first document", schema=ContractSummary
    )
    b = build_request(
        registry,
        "extract_contract@v2",
        "a completely different second document",
        schema=ContractSummary,
    )
    assert a.req.system == b.req.system
    assert a.prefix_signature == b.prefix_signature
    assert a.req.messages[0].content != b.req.messages[0].content


def test_schema_lives_inside_the_prefix() -> None:
    registry = PromptRegistry("prompts")
    built = build_request(
        registry, "extract_contract@v2", "document", schema=ContractSummary
    )
    assert "amount_minor" in built.req.system
