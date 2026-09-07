"""Schema derived from the function signature."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import pytest
from pydantic import Field

from aimai_kit.tools.decorator import tool
from aimai_kit.tools.executor import CallContext


@tool
def sample(
    query: Annotated[str, Field(description="What to search for.")],
    status: Literal["open", "closed"] = "open",
    limit: int = 10,
    since: date | None = None,
) -> str:
    """Search things.

    To fetch one thing by id, use another tool.
    """
    return "ok"


def test_docstring_becomes_the_description() -> None:
    assert sample.tool_spec.description.startswith("Search things.")


def test_missing_docstring_is_rejected() -> None:
    """The description is the model's only signal for when to call a tool."""
    with pytest.raises(ValueError, match="docstring"):

        @tool
        def undocumented(x: int) -> str:
            return "x"


def test_missing_annotation_is_rejected() -> None:
    with pytest.raises(TypeError, match="type annotation"):

        @tool
        def untyped(x) -> str:  # noqa: ANN001
            """Do something."""
            return "x"


def test_unsupported_type_is_rejected() -> None:
    """A tool needing a nested argument object is usually two tools."""
    with pytest.raises(TypeError, match="unsupported annotation"):

        @tool
        def nested(payload: dict) -> str:
            """Do something."""
            return "x"


def test_literal_becomes_an_enum() -> None:
    schema = sample.tool_spec.parameters
    assert schema["properties"]["status"]["enum"] == ["open", "closed"]


def test_optional_is_expressed_as_anyof_null() -> None:
    schema = sample.tool_spec.parameters
    assert any(
        entry.get("type") == "null" for entry in schema["properties"]["since"]["anyOf"]
    )


def test_strict_mode_keys_are_present() -> None:
    schema = sample.tool_spec.parameters
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_field_description_reaches_the_schema() -> None:
    schema = sample.tool_spec.parameters
    assert schema["properties"]["query"]["description"] == "What to search for."


def test_signature_change_changes_the_schema() -> None:
    """The whole point: schema and signature cannot drift apart."""

    @tool
    def variant(query: str, page: int = 1) -> str:
        """Search things."""
        return "ok"

    assert set(variant.tool_spec.parameters["properties"]) == {"query", "page"}
    assert set(sample.tool_spec.parameters["properties"]) != {"query", "page"}


def test_context_parameters_are_not_in_the_schema() -> None:
    """Tenancy in the schema would let a model claim to be another tenant."""

    @tool
    def scoped(ctx: CallContext, order_id: str) -> str:
        """Fetch an order."""
        return "ok"

    assert "ctx" not in scoped.tool_spec.parameters["properties"]
    assert scoped.tool_spec.context_params == ("ctx",)


def test_side_effect_flags_live_on_the_spec_not_the_schema() -> None:
    @tool(side_effect=True, requires_approval=True)
    def mutate(order_id: str) -> str:
        """Change something."""
        return "ok"

    spec = mutate.tool_spec
    assert spec.side_effect and spec.requires_approval
    assert "side_effect" not in spec.parameters["properties"]
    assert "requires_approval" not in spec.parameters["properties"]
