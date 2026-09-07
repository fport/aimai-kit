"""The `@tool` decorator — a JSON Schema derived from the function signature.

Writing the schema by hand and the function separately guarantees they drift
apart: someone renames a parameter, the schema still advertises the old name,
and the model keeps sending arguments that no longer bind. Deriving the schema
from `inspect.signature` makes that class of bug impossible.

Supported types are restricted on purpose: `str`, `int`, `float`, `bool`,
`Literal`, `date` and lists of those. An unsupported annotation raises at
import time rather than producing a schema the provider will reject at
runtime. The restriction is not a limitation of the technique but a design
choice — a tool that needs a deeply nested argument object is usually two
tools.

The docstring becomes the description. An empty docstring is an error,
because the description is the only thing the model has to decide WHEN to
call this tool; leaving it blank guarantees wrong tool selection.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, Literal, get_args, get_origin, get_type_hints

from pydantic import Field, create_model

from .spec import ToolSpec

__all__ = ["tool", "SUPPORTED_SCALARS"]

SUPPORTED_SCALARS = (str, int, float, bool, date)

# Parameters with these names are injected by the executor from the server-side
# call context and are removed from the schema. The model must never be able to
# claim it is a different tenant, so tenancy cannot be a model-supplied field.
CONTEXT_PARAM_NAMES = ("ctx", "user_id", "tenant_id")


def _check_type(annotation: Any, tool_name: str, param: str) -> None:
    if annotation in SUPPORTED_SCALARS:
        return
    origin = get_origin(annotation)
    if origin is Literal:
        return
    if origin in (list, set, tuple):
        args = get_args(annotation)
        if args and all(
            a in SUPPORTED_SCALARS or get_origin(a) is Literal for a in args
        ):
            return
    if origin is not None and type(None) in get_args(annotation):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        if len(inner) == 1:
            _check_type(inner[0], tool_name, param)
            return
    raise TypeError(
        f"{tool_name}.{param}: unsupported annotation {annotation!r}. Use "
        f"str, int, float, bool, date, Literal, or a list of those. A tool "
        "that needs a nested argument object is usually two tools."
    )


def _strip_unsupported(node: Any) -> Any:
    """Remove JSON Schema keywords providers reject in strict mode."""
    if isinstance(node, dict):
        out = {
            k: _strip_unsupported(v)
            for k, v in node.items()
            if k not in ("title", "default", "format")
        }
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(node, list):
        return [_strip_unsupported(x) for x in node]
    return node


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    side_effect: bool = False,
    requires_approval: bool = False,
    timeout_s: float = 20.0,
    max_result_chars: int = 8_000,
) -> Callable[..., Any]:
    """Turn a plain function into a `ToolSpec`.

    Usable bare (`@tool`) or with arguments
    (`@tool(side_effect=True, requires_approval=True)`).
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or func.__name__
        description = inspect.getdoc(func) or ""
        if not description.strip():
            raise ValueError(
                f"{tool_name}: a tool needs a docstring. The description is "
                "the only signal the model has for deciding when to call it."
            )

        signature = inspect.signature(func)
        # `get_type_hints` rather than `param.annotation`: with
        # `from __future__ import annotations` in effect every annotation
        # arrives as a string, and a string is not a type we can build a
        # schema from. `include_extras=True` keeps the `Annotated` metadata
        # that carries the field descriptions.
        try:
            hints = get_type_hints(func, include_extras=True)
        except NameError as error:
            # A name that only exists in an enclosing function's scope cannot
            # be resolved from a string annotation. Say so plainly instead of
            # letting a bare NameError surface from deep inside typing.
            raise TypeError(
                f"{tool_name}: cannot resolve type annotations ({error}). "
                "Types used in a tool signature must be importable at module "
                "level, not defined inside the enclosing function."
            ) from error
        fields: dict[str, Any] = {}
        context_params: list[str] = []

        for param_name, param in signature.parameters.items():
            if param_name in CONTEXT_PARAM_NAMES:
                context_params.append(param_name)
                continue
            if param_name not in hints:
                raise TypeError(
                    f"{tool_name}.{param_name}: missing type annotation. The "
                    "schema is derived from the signature, so every parameter "
                    "needs one."
                )

            annotation = hints[param_name]
            field_info: Any = ...
            if get_origin(annotation) is Annotated:
                annotation, *extras = get_args(annotation)
                field_info = next((e for e in extras if hasattr(e, "description")), ...)

            _check_type(annotation, tool_name, param_name)

            if param.default is not inspect.Parameter.empty:
                if field_info is ...:
                    field_info = Field(default=param.default)
                else:
                    field_info = Field(
                        default=param.default,
                        description=getattr(field_info, "description", None),
                    )
            fields[param_name] = (annotation, field_info)

        args_model = create_model(f"{tool_name}_Args", **fields)
        parameters = _strip_unsupported(args_model.model_json_schema())

        spec = ToolSpec(
            name=tool_name,
            description=description.strip(),
            parameters=parameters,
            fn=func,
            args_model=args_model,
            side_effect=side_effect,
            requires_approval=requires_approval,
            timeout_s=timeout_s,
            max_result_chars=max_result_chars,
            context_params=tuple(context_params),
        )
        func.tool_spec = spec  # type: ignore[attr-defined]
        return func

    if fn is not None:
        return decorate(fn)
    return decorate
