"""Schema regression: enum values and structure must not change silently.

The schema is the contract the model sees. Adding a value to `RiskLevel` or
turning an optional field into a required one makes every stored eval result
incomparable. This test does not forbid change — it makes change VISIBLE.
"""

from __future__ import annotations

import json

import pytest
from conftest import FakeClient
from pydantic import ValidationError

from aimai_kit.prompts.schemas import (
    CRITICAL_FIELDS,
    ContractSummary,
    RiskLevel,
    strict_json_schema,
)
from aimai_kit.provider.types import JsonSchemaSpec

# When you change the schema on purpose, update this and open a v3 schema.
EXPECTED_SCHEMA_FINGERPRINT = "90bfabf8c1f9"


def schema_fingerprint() -> str:
    """The SAME computation production uses.

    Writing a separate hash in the test is tempting and a trap: even an
    `ensure_ascii` difference separates the two values, and the test would
    then verify its own arithmetic rather than the fingerprint production
    actually writes.
    """
    return JsonSchemaSpec(
        ContractSummary.__name__, strict_json_schema(ContractSummary)
    ).fingerprint


def test_enum_values_are_pinned() -> None:
    assert [r.value for r in RiskLevel] == ["low", "medium", "high"]


def test_strict_mode_constraints() -> None:
    schema = strict_json_schema(ContractSummary)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    # Optionality is expressed as `anyOf: [type, null]`, not by omission.
    assert any(
        entry.get("type") == "null"
        for entry in schema["properties"]["end_date"]["anyOf"]
    )


def test_unsupported_keywords_are_stripped() -> None:
    raw = json.dumps(strict_json_schema(ContractSummary))
    assert '"format"' not in raw
    assert '"default"' not in raw


def test_ref_structure_is_preserved() -> None:
    schema = strict_json_schema(ContractSummary)
    assert "$defs" in schema and "RiskLevel" in schema["$defs"]
    assert "$ref" in json.dumps(schema["properties"]["risk_level"])


def test_descriptions_reach_the_model() -> None:
    """The field name is not the only signal; descriptions are instructions."""
    schema = strict_json_schema(ContractSummary)
    for name in ("amount_minor", "end_date", "termination_notice_days"):
        assert len(schema["properties"][name]["description"]) > 40, name


def test_critical_fields_exist_in_the_schema() -> None:
    schema = strict_json_schema(ContractSummary)
    for name in CRITICAL_FIELDS:
        assert name in schema["properties"]


def test_schema_fingerprint_is_pinned() -> None:
    current = schema_fingerprint()
    assert current == EXPECTED_SCHEMA_FINGERPRINT, (
        f"The schema changed. If that was intentional, set "
        f"EXPECTED_SCHEMA_FINGERPRINT = {current!r} and stop comparing old "
        "eval results against the new schema."
    )


def test_cross_rule_end_cannot_precede_start() -> None:
    with pytest.raises(ValidationError, match="start_date"):
        ContractSummary(start_date="2025-06-01", end_date="2025-01-01")


def test_cross_rule_high_risk_needs_rationale() -> None:
    with pytest.raises(ValidationError, match="risk_rationale"):
        ContractSummary(risk_level="high")
    ContractSummary(risk_level="high", risk_rationale="Penalty clause present.")


def test_cross_rule_amount_needs_currency() -> None:
    with pytest.raises(ValidationError, match="currency"):
        ContractSummary(amount_minor=125050)


def test_schema_fingerprint_is_written_to_telemetry() -> None:
    """Reading an eval row needs 'which schema' as much as 'which prompt'."""
    from aimai_kit.prompts.structured import bind_schema
    from aimai_kit.provider.resilient import ResilientClient
    from aimai_kit.provider.telemetry import UsageCollector
    from aimai_kit.provider.types import ChatRequest, Message, Role

    collector = UsageCollector()
    request = bind_schema(
        ChatRequest(messages=[Message(role=Role.USER, content="x")]), ContractSummary
    )
    ResilientClient(FakeClient(["{}"]), on_usage=collector).complete(request)

    (record,) = collector.records
    assert record.schema_fingerprint == request.json_schema.fingerprint
    assert record.schema_fingerprint == schema_fingerprint()


def test_schema_fingerprint_ignores_key_order() -> None:
    a = JsonSchemaSpec("S", {"type": "object", "properties": {}})
    b = JsonSchemaSpec("S", {"properties": {}, "type": "object"})
    assert a.fingerprint == b.fingerprint
