"""Binding a schema to the model, and a bounded repair loop.

Two jobs:

1. BINDING — turn a Pydantic model into a provider-agnostic
   `JsonSchemaSpec` and attach it to the `ChatRequest`. The adapter wraps it
   in its own parameter (OpenAI `text.format`, Anthropic
   `output_config.format`, Gemini `response_json_schema`). This file knows no
   vendor names.

2. REPAIR — even with a schema bound, output can be invalid: cross-field
   rules (end_date > start_date) live outside the provider's JSON Schema
   enforcement because they are Pydantic validators, not schema.

Three rules for the repair loop:

- BOUNDED. Two or three attempts. An unbounded loop turns a bad prompt into
  an expensive infinite one; the bound pushes the problem back to the prompt.
- The ERROR LIST must be READABLE. Sending the model a raw `ValidationError`
  repr does not help; a line-by-line "write a valid date in end_date" does.
- The "DO NOT INVENT" instruction is mandatory. A repair request nudges the
  model toward FILLING the missing field, which is the shortest path to
  output that passes validation and is fabricated.

Every attempt produces its own `UsageRecord` (`attempt` field). The "average
attempts" metric comes from there, and a rise in the repair rate is the
earliest signal of a prompt or schema regression.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ValidationError

from ..provider.client import LLMClient
from ..provider.types import ChatRequest, ChatResult, JsonSchemaSpec, Message, Role
from .schemas import strict_json_schema

__all__ = [
    "REPAIR_INSTRUCTION",
    "RepairResult",
    "SchemaBindingFailed",
    "bind_schema",
    "format_errors",
    "generate_structured",
]

REPAIR_INSTRUCTION = (
    "Your previous answer failed validation with the errors below. Fix ONLY "
    "those errors and return a single JSON object matching the schema.\n\n"
    "Rules:\n"
    "- Do NOT invent new information. Never write a value that is not in the "
    "document.\n"
    "- Leave a field null when you are unsure; null beats a wrong value.\n"
    "- Keep the fields that were already correct exactly as they were.\n"
    "- No commentary, no apology, no markdown fences; JSON only.\n\n"
    "Errors:\n{errors}\n\n"
    "Your invalid answer:\n{raw}"
)


class SchemaBindingFailed(Exception):
    """The model could not produce valid output within the attempt budget."""

    def __init__(self, attempts: int, last_errors: list[str], last_raw: str) -> None:
        super().__init__(
            f"no valid output after {attempts} attempts. "
            f"Last errors: {'; '.join(last_errors)}"
        )
        self.attempts = attempts
        self.last_errors = last_errors
        self.last_raw = last_raw


@dataclass
class RepairResult[T: BaseModel]:
    """The validated object plus how we got there.

    `attempts` is published as a metric. An average near 1.0 is healthy; a
    climb means the schema grew more complex or the prompt drifted.
    """

    value: T
    attempts: int
    history: list[tuple[str, list[str]]] = field(default_factory=list)
    results: list[ChatResult] = field(default_factory=list)

    @property
    def first_try(self) -> bool:
        return self.attempts == 1


def bind_schema(req: ChatRequest, model: type[BaseModel]) -> ChatRequest:
    """Attach the schema to the request.

    The schema goes on `ChatRequest`, NOT into a message. Cache is the
    reason: the schema is a fixed part of the prefix and lives inside the
    system block; rewriting it into the message body on every request would
    change the prefix.
    """
    return replace(
        req,
        json_schema=JsonSchemaSpec(
            name=model.__name__, schema=strict_json_schema(model)
        ),
    )


def format_errors(error: ValidationError) -> list[str]:
    """Turn Pydantic errors into lines a model can act on.

    A raw `ValidationError` contains fragments like
    `[type=date_from_datetime_parsing, input_value='2025-13-45',
    input_type=str]`, which is noise to a model. Field path, a human
    sentence, and the offending value are enough.
    """
    lines: list[str] = []
    for e in error.errors():
        location = ".".join(str(p) for p in e["loc"]) or "(root)"
        given = e.get("input")
        given_text = ""
        if given is not None and not isinstance(given, dict | list):
            given_text = f" (you wrote: {given!r})"
        lines.append(f"- {location}: {e['msg']}{given_text}")
    return lines


def _parse_json(text: str) -> dict:
    """Parse the model's output as JSON.

    Even with a schema bound, some models wrap output in ```json ... ```. One
    line of cleanup saves a repair round — and the money that call costs.
    """
    trimmed = text.strip()
    if trimmed.startswith("```"):
        trimmed = trimmed.split("\n", 1)[-1] if "\n" in trimmed else trimmed
        trimmed = trimmed.rsplit("```", 1)[0]
    return json.loads(trimmed.strip())


def generate_structured[T: BaseModel](
    client: LLMClient,
    req: ChatRequest,
    model: type[T],
    *,
    max_attempts: int = 3,
) -> RepairResult[T]:
    """Produce an object matching the schema, repairing a bounded number of
    times if necessary."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    bound = bind_schema(req, model)
    history: list[tuple[str, list[str]]] = []
    results: list[ChatResult] = []
    messages = list(bound.messages)

    for attempt in range(1, max_attempts + 1):
        result = client.complete(replace(bound, messages=messages))
        results.append(result)

        try:
            value = model.model_validate(_parse_json(result.text))
        except (ValidationError, json.JSONDecodeError, ValueError) as error:
            errors = (
                format_errors(error)
                if isinstance(error, ValidationError)
                else [f"- (root): output is not valid JSON: {error}"]
            )
            history.append((result.text, errors))

            if attempt == max_attempts:
                raise SchemaBindingFailed(attempt, errors, result.text) from error

            # Repair round: APPEND the invalid answer and the errors to the
            # conversation. Starting a fresh conversation makes the model
            # regenerate the fields it already got right, usually worse.
            messages = [
                *messages,
                Message(role=Role.ASSISTANT, content=result.text),
                Message(
                    role=Role.USER,
                    content=REPAIR_INSTRUCTION.format(
                        errors="\n".join(errors), raw=result.text
                    ),
                ),
            ]
            continue

        return RepairResult(
            value=value, attempts=attempt, history=history, results=results
        )

    raise AssertionError("unreachable")  # pragma: no cover
