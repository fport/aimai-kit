"""The safe tool executor — five gates before anything runs.

Every gate answers a different question, and each one produces a message the
model can act on rather than a stack trace:

    1. does the tool exist?      -> no_such_tool     (lists what does exist)
    2. is the caller allowed?    -> not_allowed      (does not name the tool)
    3. is it parseable JSON?     -> bad_json         (shows what arrived)
    4. does it match the schema? -> bad_args         (names the missing field)
    5. does it need approval?    -> needs_approval   (stops the loop cleanly)

Gate 1's message deliberately lists the available tools: a model that called
`get_customer` when the tool is `fetch_customer` fixes itself on the next
turn. Gate 2's message deliberately does NOT: telling an unauthorized caller
which tools exist is a disclosure, and a model that learns a tool exists will
keep trying it.

Three things happen after the gates:

- The server context (`user_id`, `tenant_id`) is injected from the CALL, never
  from the arguments. Tenancy in the schema means a model can claim to be
  another tenant, and no amount of prompting fixes that.
- A timeout is enforced with a worker thread. A tool that hangs does not hang
  the agent; it produces a `timeout` result the loop can reason about.
- The result is truncated to `max_result_chars` and the truncation is
  ANNOUNCED. Silent truncation produces answers based on half a document with
  no indication anything was missing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..provider.counters import COUNTERS
from .idempotency import IdempotencyStore, call_signature
from .registry import ToolRegistry
from .spec import ToolResult, ToolSpec

__all__ = ["CallContext", "ToolExecutor"]


@dataclass(frozen=True, slots=True)
class CallContext:
    """Server-side facts about who is calling.

    Deliberately not part of any tool schema. These values come from the
    session, and the model has no say in them.
    """

    user_id: str = ""
    tenant_id: str = ""
    approved_calls: frozenset[str] = frozenset()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_kwargs(self, spec: ToolSpec) -> dict[str, Any]:
        """Only the context parameters this tool actually declared."""
        available = {"ctx": self, "user_id": self.user_id, "tenant_id": self.tenant_id}
        return {k: available[k] for k in spec.context_params if k in available}


class ToolExecutor:
    """Runs one tool call through the gates and returns a `ToolResult`."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        idempotency: IdempotencyStore | None = None,
        max_workers: int = 4,
    ) -> None:
        self.registry = registry
        self.idempotency = idempotency or IdempotencyStore()
        # Two pools, not one. `call_many` submits into the fan-out pool and
        # each of those calls submits again to enforce its timeout; sharing a
        # single pool means the outer tasks occupy every worker and the inner
        # ones queue behind them, so timeouts fire on work that never started.
        self._timeout_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tool-run"
        )
        self._fanout_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tool-fanout"
        )

    # --- gates ------------------------------------------------------------

    def _gate_exists(
        self, name: str, allowlist: Sequence[str] | None
    ) -> ToolResult | None:
        if self.registry.get(name) is not None:
            return None
        available = (
            ", ".join(t.name for t in self.registry.visible(allowlist)) or "none"
        )
        return ToolResult.failure(
            "no_such_tool",
            f"There is no tool named '{name}'. Available tools: {available}. "
            "Pick one of those or answer without a tool.",
            retryable=True,
        )

    def _gate_allowed(
        self, spec: ToolSpec, allowlist: Sequence[str] | None
    ) -> ToolResult | None:
        if allowlist is None or spec.name in set(allowlist):
            return None
        # Note the message does not confirm the tool exists.
        return ToolResult.failure(
            "not_allowed",
            "You are not permitted to use that tool in this context. "
            "Continue with the tools you have been given.",
            retryable=False,
        )

    @staticmethod
    def _gate_json(
        spec: ToolSpec, arguments: str
    ) -> tuple[dict | None, ToolResult | None]:
        try:
            parsed = json.loads(arguments or "{}")
        except json.JSONDecodeError as error:
            return None, ToolResult.failure(
                "bad_json",
                f"The arguments for '{spec.name}' were not valid JSON "
                f"({error.msg} at position {error.pos}). Send a single JSON "
                "object matching the tool schema.",
                retryable=True,
            )
        if not isinstance(parsed, dict):
            return None, ToolResult.failure(
                "bad_json",
                f"The arguments for '{spec.name}' must be a JSON object, got "
                f"{type(parsed).__name__}.",
                retryable=True,
            )
        return parsed, None

    @staticmethod
    def _gate_schema(spec: ToolSpec, parsed: dict) -> tuple[Any, ToolResult | None]:
        try:
            return spec.args_model.model_validate(parsed), None
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
                for e in error.errors()
            )
            return None, ToolResult.failure(
                "bad_args",
                f"The arguments for '{spec.name}' do not match its schema. "
                f"{problems}. Fix those fields and call the tool again.",
                retryable=True,
            )

    @staticmethod
    def _gate_approval(
        spec: ToolSpec, signature: str, ctx: CallContext
    ) -> ToolResult | None:
        if not spec.requires_approval or signature in ctx.approved_calls:
            return None
        return ToolResult.failure(
            "needs_approval",
            f"'{spec.name}' has a side effect and requires human approval "
            "before it can run. Stop here and explain what you intend to do "
            "and why.",
            retryable=False,
        )

    # --- execution --------------------------------------------------------

    def _truncate(self, spec: ToolSpec, content: str) -> str:
        if len(content) <= spec.max_result_chars:
            return content
        kept = content[: spec.max_result_chars]
        dropped = len(content) - spec.max_result_chars
        # Announced, never silent: an answer built on half a document with no
        # indication anything was missing is worse than a short answer.
        return (
            f"{kept}\n\n[truncated: {dropped} more characters were omitted. "
            "Narrow the query or request a specific section.]"
        )

    def call(
        self,
        name: str,
        arguments: str,
        ctx: CallContext | None = None,
        *,
        allowlist: Sequence[str] | None = None,
    ) -> ToolResult:
        """Run one call through the gates and return a result. Never raises."""
        ctx = ctx or CallContext()

        blocked = self._gate_exists(name, allowlist)
        if blocked:
            return self._record(name, blocked)
        spec = self.registry.get(name)
        assert spec is not None  # gate 1 guarantees this

        blocked = self._gate_allowed(spec, allowlist)
        if blocked:
            return self._record(name, blocked)

        parsed, blocked = self._gate_json(spec, arguments)
        if blocked:
            return self._record(name, blocked)

        validated, blocked = self._gate_schema(spec, parsed or {})
        if blocked:
            return self._record(name, blocked)

        signature = call_signature(name, parsed or {})

        blocked = self._gate_approval(spec, signature, ctx)
        if blocked:
            return self._record(name, blocked)

        # A side-effecting call that already ran returns its stored result
        # rather than running again.
        if spec.side_effect:
            cached = self.idempotency.get(signature)
            if cached is not None:
                COUNTERS.increment("tool_idempotent_hits_total", tool=name)
                return cached

        result = self._invoke(spec, validated, ctx)
        if spec.side_effect and result.ok:
            self.idempotency.put(signature, result)
        return self._record(name, result)

    def _invoke(self, spec: ToolSpec, validated: Any, ctx: CallContext) -> ToolResult:
        kwargs = validated.model_dump()
        kwargs.update(ctx.as_kwargs(spec))
        started = time.monotonic()

        future = self._timeout_pool.submit(spec.fn, **kwargs)
        try:
            raw = future.result(timeout=spec.timeout_s)
        except FutureTimeout:
            # The worker thread is left running; Python cannot kill a thread.
            # The agent is unblocked, which is what matters here — a tool that
            # needs hard cancellation belongs in a subprocess.
            return ToolResult.failure(
                "timeout",
                f"'{spec.name}' did not finish within {spec.timeout_s:g}s. "
                "Try a narrower query or a different approach.",
                retryable=True,
            )
        except Exception as error:  # noqa: BLE001 - tool failures are data
            return ToolResult(
                ok=False,
                content=(
                    f"'{spec.name}' failed: {type(error).__name__}: {error}. "
                    "Fix the inputs or use a different tool."
                ),
                error_code="tool_error",
                retryable=True,
                raw=error,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )

        content = (
            raw
            if isinstance(raw, str)
            else json.dumps(raw, ensure_ascii=False, default=str)
        )
        return ToolResult(
            ok=True,
            content=self._truncate(spec, content),
            raw=raw,
            elapsed_ms=(time.monotonic() - started) * 1000,
        )

    @staticmethod
    def _record(name: str, result: ToolResult) -> ToolResult:
        COUNTERS.increment(
            "tool_calls_total", tool=name, code=result.error_code or "ok"
        )
        return result

    def call_many(
        self,
        calls: Sequence[tuple[str, str]],
        ctx: CallContext | None = None,
        *,
        allowlist: Sequence[str] | None = None,
    ) -> list[ToolResult]:
        """Run several calls: read-only ones in parallel, side effects in order.

        Read-only calls are independent by definition, so waiting for them
        one after another wastes wall-clock time for no safety gain.

        Side-effecting calls are run SEQUENTIALLY in the order the model
        declared them, because they may depend on each other ("cancel the
        order, then notify the customer") and because a partial failure is
        much easier to reason about in a known order.

        A failure in one call never loses the others: every call gets its own
        `ToolResult`.
        """
        ctx = ctx or CallContext()
        results: dict[int, ToolResult] = {}

        read_only: list[tuple[int, str, str]] = []
        effectful: list[tuple[int, str, str]] = []
        for index, (name, arguments) in enumerate(calls):
            spec = self.registry.get(name)
            target = effectful if (spec and spec.side_effect) else read_only
            target.append((index, name, arguments))

        if read_only:
            futures = {
                self._fanout_pool.submit(
                    self.call, name, arguments, ctx, allowlist=allowlist
                ): index
                for index, name, arguments in read_only
            }
            for future, index in futures.items():
                results[index] = future.result()

        for index, name, arguments in effectful:
            results[index] = self.call(name, arguments, ctx, allowlist=allowlist)

        return [results[i] for i in range(len(calls))]

    def shutdown(self) -> None:
        self._timeout_pool.shutdown(wait=False)
        self._fanout_pool.shutdown(wait=False)
