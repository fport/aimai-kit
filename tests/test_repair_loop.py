"""The repair loop: is it bounded, and is the attempt count reported right?"""

from __future__ import annotations

import json

import pytest
from conftest import FakeClient

from aimai_kit.prompts.schemas import ContractSummary
from aimai_kit.prompts.structured import (
    REPAIR_INSTRUCTION,
    SchemaBindingFailed,
    bind_schema,
    format_errors,
    generate_structured,
)
from aimai_kit.provider.types import ChatRequest, Message, Role

REQUEST = ChatRequest(messages=[Message(role=Role.USER, content="document")])

VALID = json.dumps(
    {
        "parties": ["Arcadia Technologies Ltd."],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "amount_minor": 125050,
        "currency": "USD",
        "termination_notice_days": 30,
        "auto_renewal": None,
        "jurisdiction": None,
        "risk_level": "medium",
        "risk_rationale": None,
        "citations": {},
    },
    ensure_ascii=False,
)
# Cross-field violation: end before start. The shape is valid JSON Schema, so
# the provider's enforcement CANNOT catch it. That is exactly why the repair
# loop exists.
REVERSED_DATES = VALID.replace('"2025-12-31"', '"2024-01-01"')
BROKEN_JSON = "```json\n{ this is not valid json\n```"


def test_valid_first_response_needs_one_attempt() -> None:
    client = FakeClient([VALID])
    result = generate_structured(client, REQUEST, ContractSummary)
    assert result.attempts == 1 and result.first_try
    assert client.call_count == 1


def test_invalid_then_valid_takes_exactly_two_attempts() -> None:
    client = FakeClient([REVERSED_DATES, VALID])
    result = generate_structured(client, REQUEST, ContractSummary)
    assert result.attempts == 2
    assert client.call_count == 2
    assert result.value.amount_minor == 125050


def test_repair_message_carries_errors_and_the_no_invention_rule() -> None:
    client = FakeClient([REVERSED_DATES, VALID])
    generate_structured(client, REQUEST, ContractSummary)
    second = client.calls[1]
    repair = second.messages[-1].content
    assert "start_date" in repair, "the Pydantic error must reach the model"
    assert "do NOT invent" in repair.lower() or "Do NOT invent" in repair
    assert "null" in repair
    # The invalid answer is APPENDED; the conversation is not rebuilt.
    assert second.messages[-2].role is Role.ASSISTANT


def test_attempts_are_capped() -> None:
    client = FakeClient([REVERSED_DATES])
    with pytest.raises(SchemaBindingFailed) as excinfo:
        generate_structured(client, REQUEST, ContractSummary, max_attempts=3)
    assert client.call_count == 3
    assert excinfo.value.attempts == 3


def test_markdown_fence_is_stripped() -> None:
    """One line of cleanup that saves a repair round, and its cost."""
    client = FakeClient([f"```json\n{VALID}\n```"])
    result = generate_structured(client, REQUEST, ContractSummary)
    assert result.attempts == 1


def test_broken_json_is_also_repaired() -> None:
    client = FakeClient([BROKEN_JSON, VALID])
    result = generate_structured(client, REQUEST, ContractSummary)
    assert result.attempts == 2
    assert "not valid JSON" in result.history[0][1][0]


def test_error_formatting_is_readable() -> None:
    from pydantic import ValidationError

    try:
        ContractSummary(start_date="2025-06-01", end_date="2020-01-01")
    except ValidationError as error:
        lines = format_errors(error)
    assert lines and lines[0].startswith("- ")
    assert "type=" not in lines[0], "raw Pydantic noise must not reach the model"


def test_schema_binds_to_the_request_not_the_messages() -> None:
    """The schema belongs in the prefix, not rewritten into every message."""
    bound = bind_schema(REQUEST, ContractSummary)
    assert bound.json_schema is not None
    assert bound.json_schema.name == "ContractSummary"
    assert bound.json_schema.strict is True
    assert bound.messages == REQUEST.messages


def test_every_attempt_produces_its_own_result() -> None:
    """Wasted attempts are real money; they belong in the accounting."""
    client = FakeClient([REVERSED_DATES, VALID])
    result = generate_structured(client, REQUEST, ContractSummary)
    assert len(result.results) == 2
    assert REPAIR_INSTRUCTION  # the constant is exported and visible in tests
