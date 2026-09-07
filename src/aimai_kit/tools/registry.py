"""Tool registry and the allowlist.

The registry is the operator's side of the boundary: it decides which tools
exist and, per call, which of them a given caller may see. That second part
is `visible(allowlist)`, and it filters the DECLARATION, not just the
execution.

Filtering at declaration time rather than at execution time is the whole
point. If a tool the caller may not use is still advertised to the model, the
model will eventually call it, the executor will refuse, and the loop burns a
step on a refusal it could have avoided. Worse, the refusal message teaches
the model that the tool exists.

This is also the answer to "what happens when I have twenty tools": you do
not send twenty. You send the subset this request is allowed to use.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .spec import ToolSpec

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """Holds tool specs and answers "which tools may this caller see?"."""

    def __init__(self, tools: Iterable[Callable[..., object] | ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for item in tools:
            self.register(item)

    def register(self, item: Callable[..., object] | ToolSpec) -> ToolSpec:
        """Accept a `@tool`-decorated function or a `ToolSpec`.

        A bare function is rejected: without the decorator there is no schema,
        and a tool without a schema is a promise the model cannot keep.
        """
        spec = item if isinstance(item, ToolSpec) else getattr(item, "tool_spec", None)
        if spec is None:
            raise TypeError(
                f"{getattr(item, '__name__', item)!r} is not a tool. Decorate "
                "it with @tool so a schema can be derived from its signature."
            )
        if spec.name in self._tools:
            raise ValueError(f"a tool named {spec.name!r} is already registered")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def visible(self, allowlist: Sequence[str] | None = None) -> list[ToolSpec]:
        """The tools this caller may see, in a STABLE order.

        Sorting is not cosmetic: the tool declarations sit inside the cached
        prompt prefix, and a set-ordered list would produce different bytes on
        every process restart, silently destroying the cache hit rate.
        """
        if allowlist is None:
            return [self._tools[n] for n in sorted(self._tools)]
        allowed = set(allowlist)
        return [self._tools[n] for n in sorted(self._tools) if n in allowed]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools
