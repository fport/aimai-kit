"""Four budgets, four distinct stop reasons."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aimai_kit.agent import Agent, Budgets, ScriptedClient, StopReason, Thread
from aimai_kit.provider.pricing import ModelPricing
from aimai_kit.tools import ToolExecutor, ToolRegistry, tool


@tool
def ping(value: str) -> str:
    """Return the value.

    To do anything else, use another tool.
    """
    return value


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([ping]))


def _forever(n: int = 40) -> list:
    """A script that keeps calling tools, with DISTINCT arguments each turn.

    Distinct arguments matter: identical ones would trip loop detection
    first, and this file is testing budgets. That ordering (loop detection
    fires before a budget does) is itself correct and is covered in
    test_loop_detection.py.
    """
    return [[("ping", f'{{"value": "{i}"}}')] for i in range(n)]


def test_step_budget_stops_the_run(executor) -> None:
    client = ScriptedClient(_forever())
    agent = Agent(
        client,
        executor,
        budgets=Budgets(max_steps=3, max_seconds=None, max_tokens=None),
    )
    result = agent.run(Thread(), "loop forever")
    assert result.stop_reason is StopReason.STEP_BUDGET
    assert result.thread.step == 3


def test_token_budget_stops_the_run(executor) -> None:
    client = ScriptedClient(_forever())
    agent = Agent(
        client,
        executor,
        budgets=Budgets(max_tokens=1200, max_steps=None, max_seconds=None),
    )
    result = agent.run(Thread(), "loop forever")
    assert result.stop_reason is StopReason.TOKEN_BUDGET


def test_cost_budget_stops_the_run(executor) -> None:
    client = ScriptedClient(_forever())
    pricing = {
        "scripted-v1": ModelPricing(
            model="scripted-v1",
            input_per_mtok=Decimal("1000"),
            output_per_mtok=Decimal("1000"),
            context_window=200_000,
        )
    }
    agent = Agent(
        client,
        executor,
        pricing=pricing,
        budgets=Budgets(
            max_usd=Decimal("0.002"), max_steps=None, max_tokens=None, max_seconds=None
        ),
    )
    result = agent.run(Thread(), "loop forever")
    assert result.stop_reason is StopReason.COST_BUDGET
    assert result.thread.spend.usd > 0


def test_time_budget_stops_the_run(executor) -> None:
    """Wall clock is injected, so the test does not actually wait."""
    ticks = iter([0.0, 0.0, 5.0, 10.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0])
    client = ScriptedClient(_forever())
    agent = Agent(
        client,
        executor,
        budgets=Budgets(max_seconds=20.0, max_steps=None, max_tokens=None),
        now=lambda: next(ticks),
    )
    result = agent.run(Thread(), "loop forever")
    assert result.stop_reason is StopReason.TIME_BUDGET


def test_cost_budget_without_pricing_never_fires(executor) -> None:
    """A missing catalog leaves spend at zero; that is visible, not silent."""
    client = ScriptedClient([[("ping", '{"value": "x"}')], "done"])
    agent = Agent(
        client,
        executor,
        budgets=Budgets(max_usd=Decimal("0.000001"), max_steps=5, max_seconds=None),
    )
    result = agent.run(Thread(), "task")
    assert result.stop_reason is StopReason.FINISHED
    assert result.thread.spend.usd == Decimal(0)


def test_budget_stop_still_produces_an_answer(executor) -> None:
    """Cutting the run dead would leave the user with nothing."""
    # Two tool turns fill the step budget; the third entry is what the
    # tool-free final turn consumes.
    client = ScriptedClient(_forever(2) + ["partial answer"])
    budgets = Budgets(max_steps=2, max_seconds=None, max_tokens=None)
    agent = Agent(client, executor, budgets=budgets)
    result = agent.run(Thread(), "task")
    assert result.stop_reason is StopReason.STEP_BUDGET
    assert result.answer, "the final tool-free turn must produce something"
    assert any(e.kind == "final_turn" for e in result.thread.trace)


def test_final_turn_disables_tools(executor) -> None:
    client = ScriptedClient(_forever(2) + ["partial"])
    budgets = Budgets(max_steps=2, max_seconds=None, max_tokens=None)
    agent = Agent(client, executor, budgets=budgets)
    agent.run(Thread(), "task")
    assert client.requests[-1].tool_choice == "none"
    assert not client.requests[-1].tools


def test_stop_reason_classification() -> None:
    assert StopReason.FINISHED.is_success
    assert not StopReason.STEP_BUDGET.is_success
    assert StopReason.TOKEN_BUDGET.is_budget
    assert not StopReason.LOOP_DETECTED.is_budget
