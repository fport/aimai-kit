"""The agent loop — framework-free, four budgets, one stop reason.

The loop itself is short, and that is the design. Everything it could have
absorbed lives elsewhere:

    tool execution      the tool layer's executor (five gates, timeouts)
    request building    the prompt layer (registry, budget, cache prefix)
    telemetry           the provider layer's resilient client
    loop detection      a separate object with its own tests

What is left here is the part that is genuinely about the loop: check the
budget, call the model, hand any tool calls to the executor, feed the results
back, repeat.

Two decisions are worth reading the code for.

**Every tool call gets a result.** Even a refused one, even a timed-out one.
An assistant turn that requested three calls and received two results leaves
the conversation in a shape most providers reject, and the ones that do not
reject it produce confused output. The loop makes half-turns impossible.

**A budget stop gets one last turn without tools.** Cutting the run dead at
the ceiling leaves the user with nothing. Giving the model one final call with
tools disabled produces a partial answer that says what is missing, which is
almost always more useful — and the cost of that last turn has to be inside
the ceiling you chose, not on top of it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..provider.client import LLMClient
from ..provider.counters import COUNTERS
from ..provider.pricing import ModelPricing
from ..provider.types import ChatRequest, Role, ToolCall
from ..tools.executor import CallContext, ToolExecutor
from ..tools.export import export_for
from ..tools.idempotency import call_signature
from .budget import Budgets, StopReason
from .loopdetect import REPEAT_WARNING
from .thread import Thread, TraceEvent

__all__ = ["Agent", "RunResult"]


@dataclass
class RunResult:
    """What a finished run produced. The thread carries the details."""

    thread: Thread
    stop_reason: StopReason
    answer: str

    @property
    def ok(self) -> bool:
        return self.stop_reason is StopReason.FINISHED


class Agent:
    """A stateless agent. All state lives in the `Thread` passed to `run`.

    Stateless means one instance can serve concurrent requests, and it means
    a run can be reconstructed from its thread alone rather than from an
    object graph that no longer exists.
    """

    def __init__(
        self,
        client: LLMClient,
        executor: ToolExecutor,
        *,
        system: str = "",
        budgets: Budgets | None = None,
        pricing: dict[str, ModelPricing] | None = None,
        allowlist: Sequence[str] | None = None,
        max_tool_errors: int = 4,
        max_output_tokens: int = 2048,
        on_event: Callable[[TraceEvent], None] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.executor = executor
        self.system = system
        self.budgets = budgets or Budgets()
        self.pricing = pricing or {}
        self.allowlist = allowlist
        self.max_tool_errors = max_tool_errors
        self.max_output_tokens = max_output_tokens
        self.on_event = on_event
        self._now = now

    # --- internals --------------------------------------------------------

    def _emit(
        self, thread: Thread, kind: str, detail: str = "", *, ok: bool = True
    ) -> None:
        event = thread.record(kind, detail, ok=ok)
        if self.on_event:
            self.on_event(event)

    def _tool_declarations(self) -> list[dict]:
        visible = self.executor.registry.visible(self.allowlist)
        return export_for(self.client.provider, visible)

    def _charge(self, thread: Thread, result) -> None:
        """Accounting happens in ONE place in the loop, not per call site."""
        thread.spend.tokens += result.usage.total_tokens
        price = self.pricing.get(result.model)
        if price is not None:
            thread.spend.usd += price.cost(
                result.usage.input_tokens,
                result.usage.output_tokens,
                result.usage.cached_input_tokens,
            )

    def _request(self, thread: Thread, *, with_tools: bool) -> ChatRequest:
        return ChatRequest(
            messages=list(thread.messages),
            system=self.system or None,
            max_output_tokens=self.max_output_tokens,
            tools=self._tool_declarations() if with_tools else (),
            tool_choice=None if with_tools else "none",
            operation="agent",
        )

    def _final_turn(self, thread: Thread, reason: StopReason) -> StopReason:
        """One last call with tools disabled, so the user gets something.

        The model is told what happened and asked to answer with what it has.
        A partial answer that names the gap beats an empty response, and it
        beats an answer that pretends the gap is not there.
        """
        thread.add(
            Role.USER,
            "You have reached the limit for this task "
            f"({reason.value}). Do not call any more tools. Answer with what "
            "you already have, and state explicitly what is still missing.",
        )
        try:
            result = self.client.complete(self._request(thread, with_tools=False))
        except Exception as error:  # noqa: BLE001 - the run is already ending
            self._emit(thread, "final_turn", str(error), ok=False)
            return reason
        self._charge(thread, result)
        thread.add(Role.ASSISTANT, result.text)
        thread.answer = result.text
        # `tool_choice="none"` should make this impossible. If a provider
        # ignores it, the run ends with an empty answer and that has to be
        # visible in the trace rather than look like a normal stop.
        self._emit(
            thread,
            "final_turn",
            reason.value,
            ok=bool(result.text) and not result.wants_tools,
        )
        return reason

    def _run_tool_calls(
        self, thread: Thread, calls: Sequence[ToolCall], ctx: CallContext
    ) -> StopReason | None:
        """Execute a turn's tool calls and feed every result back.

        Returns a stop reason when the turn itself ends the run (a loop, an
        approval gate, or too many tool errors); otherwise None.
        """
        pairs = [(c.name, c.arguments) for c in calls]
        results = self.executor.call_many(pairs, ctx, allowlist=self.allowlist)

        stop: StopReason | None = None
        for call, result in zip(calls, results, strict=True):
            signature = call_signature(call.name, call.arguments)
            occurrences = thread.detector.observe(signature)

            content = result.content
            if thread.detector.should_warn(occurrences):
                # The warning goes INTO the tool result, where the model is
                # already looking, rather than into a separate system message
                # it may not weigh the same way.
                content += REPEAT_WARNING
                self._emit(thread, "repeat_warning", call.name)
            elif thread.detector.should_stop(occurrences):
                stop = stop or StopReason.LOOP_DETECTED
                self._emit(thread, "loop_detected", call.name, ok=False)

            if not result.ok:
                thread.spend.tool_errors += 1
                if result.error_code == "needs_approval":
                    thread.pending_approval = signature
                    stop = stop or StopReason.NEEDS_APPROVAL

            if result.ok and self.executor.registry.get(call.name) is not None:
                spec = self.executor.registry.get(call.name)
                if spec and spec.side_effect:
                    thread.tool_results[signature] = result.content

            # Every call gets a result, including refused and failed ones.
            thread.add(
                Role.TOOL,
                json.dumps(
                    {
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "ok": result.ok,
                        "error_code": result.error_code,
                        "content": content,
                    },
                    ensure_ascii=False,
                ),
            )
            self._emit(
                thread,
                "tool_result",
                f"{call.name}:{result.error_code or 'ok'}",
                ok=result.ok,
            )

        if thread.spend.tool_errors >= self.max_tool_errors:
            stop = stop or StopReason.TOOL_ERROR_CEILING
        return stop

    # --- public API -------------------------------------------------------

    def run(
        self, thread: Thread, task: str | None = None, *, ctx: CallContext | None = None
    ) -> RunResult:
        """Run until the task is done or a budget stops it.

        Passing an existing thread resumes it; that is what makes checkpoint
        recovery ordinary rather than special.
        """
        ctx = ctx or CallContext()
        started = self._now()
        if task:
            thread.goal = thread.goal or task
            thread.add(Role.USER, task)

        stop: StopReason | None = None
        while True:
            thread.spend.seconds = self._now() - started
            over = self.budgets.exceeded_by(thread.spend)
            if over is not None:
                COUNTERS.increment("agent_budget_stops_total", reason=over.value)
                stop = self._final_turn(thread, over)
                break

            thread.step += 1
            thread.spend.steps += 1
            self._emit(thread, "step", f"step {thread.step}")

            try:
                result = self.client.complete(self._request(thread, with_tools=True))
            except Exception as error:  # noqa: BLE001 - surface, do not crash
                self._emit(thread, "model_error", str(error), ok=False)
                stop = StopReason.CANCELLED
                break

            self._charge(thread, result)

            if not result.wants_tools:
                thread.add(Role.ASSISTANT, result.text)
                thread.answer = result.text
                stop = StopReason.FINISHED
                self._emit(thread, "finished", "no further tool calls")
                break

            thread.add(
                Role.ASSISTANT,
                result.text
                or json.dumps(
                    [
                        {"tool": c.name, "arguments": c.arguments}
                        for c in result.tool_calls
                    ],
                    ensure_ascii=False,
                ),
            )
            turn_stop = self._run_tool_calls(thread, result.tool_calls, ctx)
            if turn_stop is not None:
                if turn_stop is StopReason.NEEDS_APPROVAL:
                    stop = turn_stop
                else:
                    stop = self._final_turn(thread, turn_stop)
                break

        thread.spend.seconds = self._now() - started
        thread.stop_reason = (stop or StopReason.FINISHED).value
        COUNTERS.increment("agent_runs_total", reason=thread.stop_reason)
        return RunResult(
            thread=thread,
            stop_reason=StopReason(thread.stop_reason),
            answer=thread.answer,
        )
