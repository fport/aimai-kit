"""Measuring tool selection.

Three numbers, and the first one is the one people skip:

    selection accuracy      did it call the right tool, in the right order?
    argument validity rate  did the arguments pass the schema?
    forbidden-call rate     did it call something it was told not to?

Argument validity is the easy one and the least interesting: a model that
never calls the right tool can still have a 100% argument validity rate.
Forbidden-call rate is the one that belongs on a dashboard, because it is the
only one that is a security signal rather than a quality signal.

`StubToolSelector` exists for the same reason the prompt layer has a stub
extractor: so this harness can be exercised without credentials, and so the
"does a better description improve selection?" experiment can be run
deterministically. It scores a query against each tool's description with
plain word overlap and honours the negative signal in a "do not use this
for..." sentence. That is a crude model of what a real model does — and
crude is enough to show that the description text is what moves the number.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .executor import CallContext, ToolExecutor
from .registry import ToolRegistry

__all__ = ["ToolCase", "SelectionReport", "StubToolSelector", "evaluate_selection"]

_WORD_RE = re.compile(r"[a-z_][a-z0-9_]+")
_STOPWORDS = frozenset(
    """the a an of for to and or in on is are use used using this that with
    when it its by from as at be do does not you your instead more less than
    tool read only has side effect""".split()
)


@dataclass(frozen=True, slots=True)
class ToolCase:
    """One golden case for tool selection.

    `expected_tools` is a SEQUENCE, not a set: for a multi-step task the order
    matters, and a run that gets the right tools in the wrong order has not
    solved the task.

    `forbidden_tools` is separate from "not expected". Some tools are merely
    unnecessary; others must never be reached from this input. Only the second
    kind belongs here, so the forbidden-call rate stays a meaningful signal.
    """

    id: str
    query: str
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    arguments: dict[str, dict] = field(default_factory=dict)
    note: str = ""

    @property
    def expects_no_tool(self) -> bool:
        return not self.expected_tools


@dataclass
class SelectionReport:
    cases: int = 0
    selection_accuracy: float = 0.0
    argument_validity_rate: float = 0.0
    forbidden_call_rate: float = 0.0
    no_tool_accuracy: float = 0.0
    failures: list[str] = field(default_factory=list)


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


_BOUNDARY_MARKERS = (
    "to fetch",
    "to search",
    "for their",
    "for individual",
    "never use",
    "never call",
)


class StubToolSelector:
    """Picks tools by word overlap with their descriptions.

    Not a model. It exists to prove the harness measures something and to make
    the description-quality experiment reproducible.

    The scoring has three parts, and the third is what a boundary sentence
    actually does:

        name match      words of the tool name found in the query
        body match      words of the descriptive part found in the query
        redirection     a "use X instead" sentence moves score TO X

    Modeling the boundary sentence as a redirection rather than a penalty is
    the point. Treating it as a penalty on the tool that contains it is wrong
    in a way that is easy to miss: `get_order` saying "to search, use
    find_orders" would then penalise `get_order` for the word "search",
    which is the opposite of what the sentence is for.
    """

    # A single weak word overlap is not enough to justify a tool call. The
    # threshold is what makes the "no tool needed" cases measurable at all:
    # without it, any query containing a common word picks something.
    MIN_SCORE = 1.5
    # Redirection is a nudge, not a verdict. Weighted above a body match but
    # below a name match, so "use find_orders instead" can break a tie without
    # overriding a query that clearly names another tool.
    REDIRECT_WEIGHT = 0.75

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._names = set(registry.names())

    def _split(self, description: str) -> tuple[str, str]:
        lowered = description.lower()
        positions = [
            lowered.find(marker) for marker in _BOUNDARY_MARKERS if marker in lowered
        ]
        if not positions:
            return description, ""
        cut = min(positions)
        return description[:cut], description[cut:]

    def select(
        self, case: ToolCase, allowlist: Sequence[str] | None = None
    ) -> list[str]:
        query_words = _keywords(case.query)
        tools = self.registry.visible(allowlist)
        scores = {spec.name: 0.0 for spec in tools}

        for spec in tools:
            body, boundary = self._split(spec.description)
            # The name is split on underscores: `build_report` has to match
            # the word "report" in a query, not the token "build_report".
            name_words = _keywords(spec.name.replace("_", " "))
            scores[spec.name] += 2.0 * len(query_words & name_words)
            scores[spec.name] += len(query_words & _keywords(body))

            if not boundary:
                continue
            # The boundary sentence names the neighbour to use instead; the
            # overlap it attracts belongs to that neighbour.
            overlap = len(query_words & _keywords(boundary))
            for other in self._names:
                if other != spec.name and other in boundary and other in scores:
                    scores[other] += self.REDIRECT_WEIGHT * overlap

        best = max(scores.values(), default=0.0)
        if best < self.MIN_SCORE:
            return []
        return sorted(name for name, score in scores.items() if score == best)[:1]


def evaluate_selection(
    selector: StubToolSelector,
    cases: Sequence[ToolCase],
    executor: ToolExecutor,
    *,
    ctx: CallContext | None = None,
    allowlist: Sequence[str] | None = None,
) -> SelectionReport:
    """Run the golden cases and compute the three rates."""
    ctx = ctx or CallContext(user_id="u-1", tenant_id="t-1")
    correct = 0
    no_tool_total = 0
    no_tool_correct = 0
    forbidden_hits = 0
    argument_checks = 0
    argument_ok = 0
    failures: list[str] = []

    for case in cases:
        chosen = selector.select(case, allowlist)

        if case.expects_no_tool:
            no_tool_total += 1
            if not chosen:
                no_tool_correct += 1
                correct += 1
            else:
                failures.append(f"{case.id}: expected no tool, chose {chosen}")
        elif tuple(chosen) == case.expected_tools:
            correct += 1
        else:
            failures.append(
                f"{case.id}: expected {list(case.expected_tools)}, chose {chosen}"
            )

        if set(chosen) & set(case.forbidden_tools):
            forbidden_hits += 1
            failures.append(f"{case.id}: called a forbidden tool {chosen}")

        for name in chosen:
            arguments = case.arguments.get(name)
            if arguments is None:
                continue
            argument_checks += 1
            result = executor.call(
                name, json.dumps(arguments), ctx, allowlist=allowlist
            )
            if result.error_code not in ("bad_json", "bad_args"):
                argument_ok += 1

    total = len(cases) or 1
    return SelectionReport(
        cases=len(cases),
        selection_accuracy=round(correct / total, 3),
        argument_validity_rate=(
            round(argument_ok / argument_checks, 3) if argument_checks else 1.0
        ),
        forbidden_call_rate=round(forbidden_hits / total, 3),
        no_tool_accuracy=(
            round(no_tool_correct / no_tool_total, 3) if no_tool_total else 1.0
        ),
        failures=failures,
    )
