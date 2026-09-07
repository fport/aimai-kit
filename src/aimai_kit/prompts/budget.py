"""Context budget — turning trimming from implicit behavior into a decision.

`documents[:10]` is not a budget, it is a guess. If the eleventh document was
the one that changes the answer, there is no way to find out: the trim leaves
no trace. Leaving that trace is this module's only job.

Three rules:

1. PRIORITY decides placement order, not OUTPUT order. The distinction
   matters: the system prompt has to win the budget, but it also has to sit
   before the documents in the prompt. Tying both to one number breaks the
   prompt layout while trying to "put the important thing first".

2. NON-TRIMMABLE sections (system prompt, user question, schema) are never
   silently cut — `BudgetExceeded` is raised. A system that continues with
   half its instructions cannot explain why it answered wrongly.

3. Every decision produces a REPORT LINE. Not "trimming happened" but
   "section contract_text went from 8,400 tokens to 3,100".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..provider.counters import COUNTERS
from ..provider.counting import TokenCounter
from ..provider.errors import InvalidRequest

__all__ = [
    "Section",
    "TrimDecision",
    "TrimReport",
    "BudgetExceeded",
    "Placement",
    "ContextBudget",
]

Decision = Literal["kept", "trimmed", "dropped"]


class BudgetExceeded(InvalidRequest):
    """The non-trimmable sections alone do not fit the window.

    Derives from `InvalidRequest`: a retry cannot fix it. The fix is a model
    with a larger window, a smaller output reserve, or marking one of the
    sections trimmable.
    """

    def __init__(self, needed: int, limit: int, sections: Sequence[str]) -> None:
        super().__init__(
            f"non-trimmable sections need {needed} tokens, limit is {limit}. "
            f"Does not fit: {', '.join(sections)}"
        )
        self.needed = needed
        self.limit = limit
        self.sections = list(sections)


@dataclass(frozen=True, slots=True)
class Section:
    """One piece destined for the prompt.

    `priority`: a SMALLER number is placed first (1 = highest priority). Not
    inverted like Unix `nice` — in everyday language "first priority" is also
    the highest one.
    """

    name: str
    text: str
    priority: int = 50
    trimmable: bool = True
    min_tokens: int = 0  # drop entirely rather than trim below this


@dataclass(frozen=True, slots=True)
class TrimDecision:
    section: str
    decision: Decision
    original_tokens: int
    kept_tokens: int

    @property
    def dropped_tokens(self) -> int:
        return self.original_tokens - self.kept_tokens

    def __str__(self) -> str:
        if self.decision == "kept":
            return f"{self.section}: kept in full ({self.original_tokens} tok)"
        if self.decision == "trimmed":
            return (
                f"{self.section}: {self.original_tokens} -> {self.kept_tokens} tok "
                f"({self.dropped_tokens} dropped)"
            )
        return f"{self.section}: DROPPED ({self.original_tokens} tok)"


@dataclass(frozen=True, slots=True)
class TrimReport:
    decisions: list[TrimDecision] = field(default_factory=list)
    limit: int = 0
    used: int = 0

    @property
    def trimmed(self) -> bool:
        return any(d.decision != "kept" for d in self.decisions)

    @property
    def total_dropped(self) -> int:
        return sum(d.dropped_tokens for d in self.decisions)

    def lines(self) -> list[str]:
        return [str(d) for d in self.decisions]

    def summary(self) -> str:
        state = "trimming applied" if self.trimmed else "no trimming"
        detail = f" ({self.total_dropped} tok dropped)" if self.trimmed else ""
        return f"{self.used}/{self.limit} tokens used, {state}{detail}"


@dataclass(frozen=True, slots=True)
class Placement:
    """The placement result: text parts plus why they look that way."""

    parts: list[tuple[str, str]]  # (section name, text) in OUTPUT order
    report: TrimReport

    def join(self, separator: str = "\n\n") -> str:
        return separator.join(text for _, text in self.parts if text)


class ContextBudget:
    """window - output reserve - safety margin = usable limit.

    Why a safety margin: local token counting is an ESTIMATE (see the first
    paragraph of `counting.py`). On Anthropic and Gemini tiktoken can drift
    10-20%. Filling right up to the limit means a provider 400 whenever the
    estimate comes in low. The margin is the price of that drift; 5% by
    default.
    """

    def __init__(
        self,
        window: int,
        output_reserve: int,
        *,
        safety_margin: int | None = None,
        counter: TokenCounter | None = None,
        model: str = "gpt-4o",
    ) -> None:
        if output_reserve >= window:
            raise ValueError(
                f"output reserve ({output_reserve}) cannot exceed the window "
                f"({window}); nothing would be left for the input"
            )
        self.window = window
        self.output_reserve = output_reserve
        self.safety_margin = (
            safety_margin if safety_margin is not None else max(1, window // 20)
        )
        self.counter = counter or TokenCounter(model)

    @property
    def limit(self) -> int:
        """Tokens available for input. The arithmetic stays in the open."""
        return max(0, self.window - self.output_reserve - self.safety_margin)

    def place(self, sections: Sequence[Section]) -> Placement:
        """Fit the sections into the budget and report every decision."""
        limit = self.limit
        token_counts = {s.name: self.counter.count_text(s.text) for s in sections}

        # 1) Non-trimmable sections first and in full. If they do not fit
        #    there is no point continuing — trimming them would be a silent
        #    error.
        fixed = [s for s in sections if not s.trimmable]
        fixed_total = sum(token_counts[s.name] for s in fixed)
        if fixed_total > limit:
            raise BudgetExceeded(fixed_total, limit, [s.name for s in fixed])

        remaining = limit - fixed_total
        decisions: dict[str, TrimDecision] = {
            s.name: TrimDecision(
                s.name, "kept", token_counts[s.name], token_counts[s.name]
            )
            for s in fixed
        }
        texts: dict[str, str] = {s.name: s.text for s in fixed}

        # 2) Trimmable sections by priority. The sort is stable, so equal
        #    priorities keep call order and the result is deterministic.
        flexible = sorted(
            (s for s in sections if s.trimmable), key=lambda s: s.priority
        )
        for section in flexible:
            needed = token_counts[section.name]
            if needed <= remaining:
                texts[section.name] = section.text
                decisions[section.name] = TrimDecision(
                    section.name, "kept", needed, needed
                )
                remaining -= needed
                continue

            # Does not fit: trim or drop.
            if remaining <= 0 or remaining < section.min_tokens:
                texts[section.name] = ""
                decisions[section.name] = TrimDecision(
                    section.name, "dropped", needed, 0
                )
                COUNTERS.increment(
                    "context_trim_total", section=section.name, decision="dropped"
                )
                continue

            truncated = self.counter.truncate(section.text, remaining)
            actual = self.counter.count_text(truncated)
            texts[section.name] = truncated
            decisions[section.name] = TrimDecision(
                section.name, "trimmed", needed, actual
            )
            COUNTERS.increment(
                "context_trim_total", section=section.name, decision="trimmed"
            )
            remaining -= actual

        # 3) Output follows the CALLER's order; priority was only a budget
        #    decision.
        return Placement(
            parts=[(s.name, texts[s.name]) for s in sections],
            report=TrimReport(
                decisions=[decisions[s.name] for s in sections],
                limit=limit,
                used=limit - remaining,
            ),
        )
