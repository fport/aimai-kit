"""Retry, fallback and telemetry — is the decision driven by the error class?"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import FakeClient, make_error

from aimai_kit.provider.counters import COUNTERS
from aimai_kit.provider.errors import (
    AllProvidersFailed,
    AuthError,
    InvalidRequest,
    RateLimited,
    TransientError,
)
from aimai_kit.provider.resilient import ResilientClient, RetryPolicy
from aimai_kit.provider.telemetry import UsageCollector
from aimai_kit.provider.types import ChatRequest, Message, Role

REQUEST = ChatRequest(
    messages=[Message(role=Role.USER, content="hello")],
    prompt_ref="test@v1+abc123",
)


@pytest.fixture(autouse=True)
def _reset_counters():
    COUNTERS.reset()
    yield
    COUNTERS.reset()


def test_rate_limit_is_retried(instant_sleep) -> None:
    client = FakeClient([make_error(RateLimited), "done"])
    resilient = ResilientClient(client, sleep=instant_sleep)
    assert resilient.complete(REQUEST).text == "done"
    assert client.call_count == 2


def test_invalid_request_is_not_retried(instant_sleep) -> None:
    client = FakeClient([make_error(InvalidRequest), "never seen"])
    resilient = ResilientClient(client, sleep=instant_sleep)
    with pytest.raises(InvalidRequest):
        resilient.complete(REQUEST)
    assert client.call_count == 1, "an invalid request must not be retried"


def test_auth_error_is_not_retried(instant_sleep) -> None:
    client = FakeClient([make_error(AuthError), "never"])
    resilient = ResilientClient(client, sleep=instant_sleep)
    with pytest.raises(AuthError):
        resilient.complete(REQUEST)
    assert client.call_count == 1


def test_attempt_cap_is_respected(instant_sleep) -> None:
    client = FakeClient([make_error(TransientError)])
    resilient = ResilientClient(
        client, policy=RetryPolicy(max_attempts=3), sleep=instant_sleep
    )
    with pytest.raises(TransientError):
        resilient.complete(REQUEST)
    assert client.call_count == 3


def test_retry_after_header_is_honored(instant_sleep) -> None:
    client = FakeClient([make_error(RateLimited, retry_after_s=7.0), "done"])
    resilient = ResilientClient(client, sleep=instant_sleep)
    resilient.complete(REQUEST)
    assert instant_sleep.waits == [7.0], "the provider's own delay was ignored"


def test_total_deadline_cuts_the_wait(instant_sleep) -> None:
    """A long Retry-After beyond the deadline means giving up, not waiting."""
    client = FakeClient([make_error(RateLimited, retry_after_s=30.0), "done"])
    resilient = ResilientClient(
        client,
        policy=RetryPolicy(total_deadline_s=10.0, max_delay_s=60.0),
        sleep=instant_sleep,
    )
    with pytest.raises(RateLimited):
        resilient.complete(REQUEST)
    assert instant_sleep.waits == [], "no wait should exceed the deadline"


def test_fallback_is_used_when_primary_fails(instant_sleep) -> None:
    primary = FakeClient([make_error(TransientError)], model="fake-model")
    backup = FakeClient(["from the backup"], model="backup-model")
    events: list[tuple[str, str]] = []

    resilient = ResilientClient(
        primary,
        [backup],
        policy=RetryPolicy(max_attempts=2),
        on_fallback=lambda a, b, err: events.append((a, b)),
        sleep=instant_sleep,
    )
    assert resilient.complete(REQUEST).text == "from the backup"
    assert events == [("fake-model", "backup-model")], "falling back is an event"
    assert COUNTERS.total("llm_fallbacks_total") == 1


def test_all_failures_are_reported(instant_sleep) -> None:
    primary = FakeClient([make_error(TransientError)], model="a")
    backup = FakeClient([make_error(AuthError)], model="b")
    resilient = ResilientClient(
        primary, [backup], policy=RetryPolicy(max_attempts=1), sleep=instant_sleep
    )
    with pytest.raises(AllProvidersFailed) as excinfo:
        resilient.complete(REQUEST)
    assert [model for model, _ in excinfo.value.failures] == ["a", "b"]


def test_usage_record_is_produced_by_the_wrapper(fake_pricing, instant_sleep) -> None:
    """Telemetry is built here, not in the adapter, and carries prompt_ref."""
    collector = UsageCollector()
    client = FakeClient(["done"])
    resilient = ResilientClient(
        client, pricing=fake_pricing, on_usage=collector, sleep=instant_sleep
    )
    resilient.complete(REQUEST)

    (record,) = collector.records
    assert record.ok is True
    assert record.prompt_ref == "test@v1+abc123"
    assert record.input_tokens == 100
    # 100/1e6*2.50 + 20/1e6*10.00 = 0.00025 + 0.0002 = 0.00045
    assert record.cost_usd == Decimal("0.00045")


def test_failed_attempts_are_recorded_too(instant_sleep) -> None:
    collector = UsageCollector()
    client = FakeClient([make_error(RateLimited), "done"])
    resilient = ResilientClient(client, on_usage=collector, sleep=instant_sleep)
    resilient.complete(REQUEST)

    assert [r.ok for r in collector.records] == [False, True]
    assert [r.attempt for r in collector.records] == [1, 2]
    assert collector.records[0].error_type == "RateLimited"


def test_resilient_client_satisfies_the_protocol() -> None:
    from aimai_kit.provider.client import LLMClient

    assert isinstance(ResilientClient(FakeClient(["x"])), LLMClient)
