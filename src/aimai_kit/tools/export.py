"""Exporting one internal tool spec to three provider formats.

The three providers disagree about where the schema goes and what the key is
called, and about nothing else:

    OpenAI Responses      flat: name / description / parameters
    OpenAI Chat           nested under {"type": "function", "function": {...}}
    Anthropic             the schema key is `input_schema`, not `parameters`

That is the entire difference, and it is exactly the kind of difference that,
left unabstracted, ends up copied into every call site. One internal
representation, three thin exporters.

Gemini's function declarations match the OpenAI Responses shape closely
enough that the same exporter serves both; the adapter wraps the list in
`{"function_declarations": [...]}`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .spec import ToolSpec

__all__ = [
    "to_openai_responses",
    "to_openai_chat",
    "to_anthropic",
    "to_gemini",
    "export_for",
]


def to_openai_responses(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": dict(t.parameters),
        }
        for t in tools
    ]


def to_openai_chat(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": dict(t.parameters),
            },
        }
        for t in tools
    ]


def to_anthropic(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": dict(t.parameters),
        }
        for t in tools
    ]


def to_gemini(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": dict(t.parameters),
        }
        for t in tools
    ]


_EXPORTERS = {
    "openai": to_openai_responses,
    "azure_openai": to_openai_responses,
    "openai_chat": to_openai_chat,
    "anthropic": to_anthropic,
    "gemini": to_gemini,
    # The test doubles speak the flat shape. Listing them here rather than
    # special-casing them at the call site keeps `export_for` total: any
    # client that reaches the loop has an exporter.
    "scripted": to_openai_responses,
    "stub": to_openai_responses,
    "fake": to_openai_responses,
}


def export_for(provider: str, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Pick the exporter by provider name.

    The agent loop reads `client.provider` and calls this; that is the only
    place provider identity is consulted above the adapter layer, and it
    consults a name rather than a type.
    """
    exporter = _EXPORTERS.get(provider)
    if exporter is None:
        raise ValueError(
            f"no tool exporter for provider {provider!r}. Known: "
            f"{', '.join(sorted(_EXPORTERS))}"
        )
    return exporter(tools)
