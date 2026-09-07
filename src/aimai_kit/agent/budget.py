"""Four budgets and one stop reason.

An agent that runs until it decides it is finished is not a system, it is a
bet. Four budgets bound it, and they bound different failure modes:

    steps    a loop that makes progress but never converges
    tokens   a loop that grows its own context until the window bursts
    cost     the one the finance team asks about
    seconds  the one the user experiences

Three of them are cheap to check and one is not: cost requires a pricing
catalog, so it is optional. A missing catalog does not silently disable the
budget — `Spend.usd` simply stays at zero and the cost budget never fires,
which is visible in the metrics.

`StopReason` is a closed set because it is what the caller branches on. Half
of these values mean "the work is not done"; only `finished` means it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

__all__ = ["Budgets", "Spend", "StopReason"]


class StopReason(StrEnum):
    """Why a run ended. Exactly one value per run."""

    FINISHED = "finished"
    STEP_BUDGET = "step_budget"
    TOKEN_BUDGET = "token_budget"
    COST_BUDGET = "cost_budget"
    TIME_BUDGET = "time_budget"
    LOOP_DETECTED = "loop_detected"
    TOOL_ERROR_CEILING = "tool_error_ceiling"
    NEEDS_APPROVAL = "needs_approval"
    CANCELLED = "cancelled"

    @property
    def is_success(self) -> bool:
        return self is StopReason.FINISHED

    @property
    def is_budget(self) -> bool:
        return self in {
            StopReason.STEP_BUDGET,
            StopReason.TOKEN_BUDGET,
            StopReason.COST_BUDGET,
            StopReason.TIME_BUDGET,
        }


@dataclass(frozen=True, slots=True)
class Budgets:
    """The ceilings for one run.

    `max_seconds` is wall-clock, not CPU: what bounds a user's patience is
    the clock, and most of the time here is spent waiting on a network call
    anyway.

    Leaving a budget at `None` disables it. That is allowed but should be
    deliberate — an agent with no step budget will eventually find an input
    that makes it run forever.
    """

    max_steps: int | None = 12
    max_tokens: int | None = 120_000
    max_usd: Decimal | None = None
    max_seconds: float | None = 120.0

    def exceeded_by(self, spend: Spend) -> StopReason | None:
        """Which budget, if any, this spend has already crossed.

        Checked BEFORE a step, not after: knowing you are over budget after
        spending the money is an audit, not a budget.
        """
        if self.max_steps is not None and spend.steps >= self.max_steps:
            return StopReason.STEP_BUDGET
        if self.max_tokens is not None and spend.tokens >= self.max_tokens:
            return StopReason.TOKEN_BUDGET
        if self.max_usd is not None and spend.usd >= self.max_usd:
            return StopReason.COST_BUDGET
        if self.max_seconds is not None and spend.seconds >= self.max_seconds:
            return StopReason.TIME_BUDGET
        return None


@dataclass
class Spend:
    """What a run has consumed so far."""

    steps: int = 0
    tokens: int = 0
    usd: Decimal = field(default_factory=lambda: Decimal(0))
    seconds: float = 0.0
    tool_errors: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "steps": self.steps,
            "tokens": self.tokens,
            "usd": str(self.usd),
            "seconds": round(self.seconds, 3),
            "tool_errors": self.tool_errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Spend:
        return cls(
            steps=int(data.get("steps", 0)),
            tokens=int(data.get("tokens", 0)),
            usd=Decimal(str(data.get("usd", "0"))),
            seconds=float(data.get("seconds", 0.0)),
            tool_errors=int(data.get("tool_errors", 0)),
        )
