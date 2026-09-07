"""Pre-flight window check."""

import pytest

from aimai_kit.provider.counting import (
    ContextBudgetExceeded,
    TokenCounter,
    budget_guard,
)

MESSAGES = [{"role": "user", "content": "a short question"}]


def test_request_that_fits_passes() -> None:
    counter = TokenCounter("gpt-4o")
    estimated = budget_guard(counter, MESSAGES, 1_000, 128_000, "gpt-4o")
    assert estimated > 0


def test_oversized_request_is_rejected_before_the_call() -> None:
    counter = TokenCounter("gpt-4o")
    with pytest.raises(ContextBudgetExceeded):
        budget_guard(counter, MESSAGES, 1_000, 50, "gpt-4o")


def test_output_reserve_counts_toward_the_window() -> None:
    """The input fits on its own but not together with the output reserve."""
    counter = TokenCounter("gpt-4o")
    estimated = counter.count_messages(MESSAGES)
    with pytest.raises(ContextBudgetExceeded):
        budget_guard(counter, MESSAGES, 500, estimated + 100, "gpt-4o")


def test_error_carries_needed_and_window() -> None:
    counter = TokenCounter("gpt-4o")
    with pytest.raises(ContextBudgetExceeded) as excinfo:
        budget_guard(counter, MESSAGES, 1_000, 50, "gpt-4o")
    assert excinfo.value.window == 50
    assert excinfo.value.needed > 50


def test_budget_error_is_not_retryable() -> None:
    """The same request will not fit the same window on a second try."""
    assert ContextBudgetExceeded(100, 50, "m").retryable is False
