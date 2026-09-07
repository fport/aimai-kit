"""The tool-selection harness."""

from __future__ import annotations

import pytest
from tool_cases.cases import CASES

from aimai_kit.tools import ToolExecutor
from aimai_kit.tools.evaluation import (
    StubToolSelector,
    ToolCase,
    evaluate_selection,
)
from aimai_kit.tools.examples.orders import build_registry, seed_database


@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    db = tmp_path_factory.mktemp("tools") / "orders.sqlite3"
    seed_database(db)
    return build_registry(db)


@pytest.fixture(scope="module")
def report(registry):
    return evaluate_selection(StubToolSelector(registry), CASES, ToolExecutor(registry))


def test_golden_set_has_negative_cases() -> None:
    """A set without 'call no tool' cases cannot see an over-eager agent."""
    assert len(CASES) >= 20
    assert sum(1 for c in CASES if c.expects_no_tool) >= 3


def test_forbidden_tools_are_narrow() -> None:
    """Only genuinely dangerous tools belong on the forbidden list."""
    forbidden = {name for case in CASES for name in case.forbidden_tools}
    assert forbidden == {"cancel_order"}


def test_metrics_are_produced(report) -> None:
    assert report.cases == len(CASES)
    assert 0.0 <= report.selection_accuracy <= 1.0
    assert 0.0 <= report.forbidden_call_rate <= 1.0


def test_harness_actually_compares(registry) -> None:
    """A selector that always picks the wrong tool must score zero."""

    class AlwaysWrong(StubToolSelector):
        def select(self, case, allowlist=None):
            return ["build_report"]

    report = evaluate_selection(
        AlwaysWrong(registry),
        [c for c in CASES if c.expected_tools == ("get_order",)],
        ToolExecutor(registry),
    )
    assert report.selection_accuracy == 0.0


def test_argument_validity_is_measured_through_the_executor(registry) -> None:
    """Invalid arguments in the golden set must lower the rate."""
    bad = ToolCase(
        id="bad-1",
        query="fetch order 1002 by its id",
        expected_tools=("get_order",),
        arguments={"get_order": {"wrong_field": 1}},
    )
    report = evaluate_selection(
        StubToolSelector(registry), [bad], ToolExecutor(registry)
    )
    assert report.argument_validity_rate == 0.0


def test_no_tool_cases_are_scored_separately(report) -> None:
    assert 0.0 <= report.no_tool_accuracy <= 1.0


def test_failures_name_the_case(report) -> None:
    for line in report.failures:
        assert line.split(":")[0].startswith("tc-")
