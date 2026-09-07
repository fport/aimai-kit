"""Context budget: is trimming a decision, or a silent loss?"""

from __future__ import annotations

import pytest

from aimai_kit.prompts.budget import BudgetExceeded, ContextBudget, Section
from aimai_kit.provider.counters import COUNTERS


@pytest.fixture(autouse=True)
def _reset_counters():
    COUNTERS.reset()
    yield
    COUNTERS.reset()


@pytest.fixture
def budget() -> ContextBudget:
    return ContextBudget(window=400, output_reserve=100, safety_margin=0)


def test_limit_is_explicit(budget) -> None:
    assert budget.limit == 300


def test_default_safety_margin_is_five_percent() -> None:
    b = ContextBudget(window=1000, output_reserve=100)
    assert b.safety_margin == 50
    assert b.limit == 850


def test_content_that_fits_is_not_trimmed(budget) -> None:
    placement = budget.place([Section("short", "two words", priority=10)])
    assert not placement.report.trimmed
    assert placement.report.decisions[0].decision == "kept"


def test_trim_report_names_the_right_section(budget) -> None:
    placement = budget.place(
        [
            Section("system", "short instruction", priority=1, trimmable=False),
            Section("documents", "long document text " * 200, priority=30),
        ]
    )
    trimmed = [d for d in placement.report.decisions if d.decision == "trimmed"]
    assert [d.section for d in trimmed] == ["documents"]
    assert trimmed[0].dropped_tokens > 0
    assert "documents" in placement.report.lines()[1]


def test_priority_decides_what_gets_trimmed(budget) -> None:
    """Proves priority actually does something."""
    a = Section("A", "aaaa " * 100, priority=1)
    b = Section("B", "bbbb " * 100, priority=99)
    first = {d.section: d.decision for d in budget.place([a, b]).report.decisions}
    swapped = {
        d.section: d.decision
        for d in budget.place(
            [Section("A", a.text, priority=99), Section("B", b.text, priority=1)]
        ).report.decisions
    }
    assert first["A"] == "kept" and first["B"] != "kept"
    assert swapped["B"] == "kept" and swapped["A"] != "kept"


def test_output_order_is_independent_of_priority(budget) -> None:
    """Priority is a BUDGET decision; layout follows the caller's order."""
    placement = budget.place(
        [
            Section("appears_first", "x", priority=90),
            Section("appears_second", "y", priority=1),
        ]
    )
    assert [name for name, _ in placement.parts] == [
        "appears_first",
        "appears_second",
    ]


def test_unfittable_fixed_section_raises_instead_of_trimming() -> None:
    with pytest.raises(BudgetExceeded) as excinfo:
        ContextBudget(window=60, output_reserve=20, safety_margin=0).place(
            [Section("system", "a very long system instruction " * 40, trimmable=False)]
        )
    assert excinfo.value.sections == ["system"]
    assert excinfo.value.needed > excinfo.value.limit


def test_budget_error_is_not_retryable() -> None:
    """Retrying the same request will not fit the same window."""
    assert BudgetExceeded(500, 100, ["system"]).retryable is False


def test_section_below_min_tokens_is_dropped(budget) -> None:
    placement = budget.place(
        [
            Section("filler", "filler " * 250, priority=1),
            Section("crumb", "crumb " * 50, priority=50, min_tokens=100),
        ]
    )
    decisions = {d.section: d.decision for d in placement.report.decisions}
    assert decisions["crumb"] == "dropped", "drop it rather than keep 20 useless tokens"


def test_trim_counter_is_labeled_by_section(budget) -> None:
    budget.place(
        [
            Section("system", "short", priority=1, trimmable=False),
            Section("documents", "long " * 400, priority=30),
        ]
    )
    assert (
        COUNTERS.get("context_trim_total", section="documents", decision="trimmed") == 1
    )
    assert COUNTERS.total("context_trim_total") == 1


def test_output_reserve_cannot_exceed_the_window() -> None:
    with pytest.raises(ValueError, match="output reserve"):
        ContextBudget(window=100, output_reserve=100)
