"""One internal spec, three provider formats."""

from __future__ import annotations

import pytest

from aimai_kit.tools import ToolRegistry, tool
from aimai_kit.tools.export import (
    export_for,
    to_anthropic,
    to_gemini,
    to_openai_chat,
    to_openai_responses,
)


@tool
def echo(text: str) -> str:
    """Echo the text back.

    To transform text, use another tool.
    """
    return text


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry([echo])


def test_openai_responses_is_flat(registry) -> None:
    (exported,) = to_openai_responses(registry.visible())
    assert exported["name"] == "echo"
    assert "parameters" in exported
    assert "function" not in exported


def test_openai_chat_is_nested(registry) -> None:
    (exported,) = to_openai_chat(registry.visible())
    assert exported["type"] == "function"
    assert exported["function"]["name"] == "echo"
    assert "parameters" in exported["function"]


def test_anthropic_renames_the_schema_key(registry) -> None:
    (exported,) = to_anthropic(registry.visible())
    assert exported["name"] == "echo"
    assert "input_schema" in exported
    assert "parameters" not in exported


def test_all_exports_carry_the_same_schema(registry) -> None:
    """The internal representation is single; only the wrapper differs."""
    spec = registry.get("echo")
    assert to_openai_responses([spec])[0]["parameters"] == dict(spec.parameters)
    assert to_openai_chat([spec])[0]["function"]["parameters"] == dict(spec.parameters)
    assert to_anthropic([spec])[0]["input_schema"] == dict(spec.parameters)
    assert to_gemini([spec])[0]["parameters"] == dict(spec.parameters)


def test_export_for_dispatches_by_provider_name(registry) -> None:
    tools = registry.visible()
    assert export_for("anthropic", tools)[0].keys() >= {"input_schema"}
    assert export_for("openai", tools)[0].keys() >= {"parameters"}
    assert export_for("azure_openai", tools) == export_for("openai", tools)


def test_unknown_provider_is_rejected(registry) -> None:
    with pytest.raises(ValueError, match="no tool exporter"):
        export_for("nonexistent", registry.visible())


def test_allowlist_filters_the_declaration_not_just_execution() -> None:
    """A tool the caller may not use must not be advertised at all."""

    @tool
    def secret(x: str) -> str:
        """Do something privileged."""
        return x

    registry = ToolRegistry([echo, secret])
    assert [t.name for t in registry.visible()] == ["echo", "secret"]
    assert [t.name for t in registry.visible(["echo"])] == ["echo"]


def test_visible_order_is_stable() -> None:
    """Declarations sit in the cached prefix; set ordering would break it."""

    @tool
    def alpha(x: str) -> str:
        """Alpha."""
        return x

    @tool
    def beta(x: str) -> str:
        """Beta."""
        return x

    registry = ToolRegistry([beta, alpha, echo])
    assert [t.name for t in registry.visible()] == ["alpha", "beta", "echo"]


def test_registering_a_bare_function_is_rejected() -> None:
    def plain(x: str) -> str:
        return x

    with pytest.raises(TypeError, match="not a tool"):
        ToolRegistry([plain])


def test_duplicate_registration_is_rejected(registry) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register(echo)
