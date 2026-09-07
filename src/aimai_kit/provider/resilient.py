"""Retry, fallback and single-point telemetry.

This class carries the "single point" claim: the usage record is produced
HERE, not in the adapter. If it were produced in the adapter, every new
provider would mean rewriting the telemetry code — and forgetting it in one
of them. An adapter does one job: turn an SDK response into a `ChatResult`.
Measuring, retrying and falling back happen here.

Retry policy is driven by the error CLASS, never by message text:
    RateLimited     -> retry, honoring Retry-After when present
    TransientError  -> retry with exponential backoff plus jitter
    InvalidRequest  -> no retry
    AuthError       -> no retry

Why jitter: if fifty concurrent clients all get a 429 and all wait exactly
two seconds, they come back at the same instant and hit the same wall
(thundering herd). Random spread breaks that up.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal

from .client import LLMClient
from .counters import COUNTERS
from .errors import AllProvidersFailed, LLMError, RateLimited
from .pricing import ModelPricing
from .telemetry import UsageRecord
from .types import ChatRequest, ChatResult

__all__ = ["RetryPolicy", "ResilientClient"]


@dataclass(frozen=True)
class RetryPolicy:
    """The whole retry behavior in one readable place.

    Why `total_deadline_s` exists: three attempts times a 60-second
    Retry-After is an HTTP request that hangs for three minutes. The user's
    browser gave up long ago. The deadline stops retrying from becoming an
    outage of its own.
    """

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 20.0
    jitter_s: float = 0.25
    total_deadline_s: float = 45.0
    honor_retry_after: bool = True

    def delay_for(self, attempt: int, error: LLMError) -> float:
        """`attempt` is 1-based: after the first failure, attempt=1."""
        if self.honor_retry_after and isinstance(error, RateLimited):
            if error.retry_after_s is not None:
                return min(error.retry_after_s, self.max_delay_s)
        backoff = self.base_delay_s * (2 ** (attempt - 1))
        return min(backoff, self.max_delay_s) + random.uniform(0, self.jitter_s)


class ResilientClient:
    """A primary client plus a fallback chain.

    It deliberately satisfies `LLMClient` ITSELF, so layers above never have
    to know whether they are talking to a bare adapter or to the resilient
    wrapper. Tests run against a fake adapter, production against the
    wrapper; the calling code is identical.
    """

    def __init__(
        self,
        primary: LLMClient,
        fallbacks: Sequence[LLMClient] = (),
        *,
        policy: RetryPolicy | None = None,
        pricing: dict[str, ModelPricing] | None = None,
        on_usage: Callable[[UsageRecord], None] | None = None,
        on_fallback: Callable[[str, str, LLMError], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._chain: list[LLMClient] = [primary, *fallbacks]
        self.policy = policy or RetryPolicy()
        self.pricing = pricing or {}
        self.on_usage = on_usage
        self.on_fallback = on_fallback
        self._sleep = sleep
        self._now = now

    @property
    def provider(self) -> str:
        return self._chain[0].provider

    @property
    def model(self) -> str:
        return self._chain[0].model

    # --- internals --------------------------------------------------------

    def _cost(self, result: ChatResult) -> Decimal:
        price = self.pricing.get(result.model)
        if price is None:
            return Decimal(0)
        return price.cost(
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.cached_input_tokens,
        )

    def _record(
        self,
        client: LLMClient,
        req: ChatRequest,
        result: ChatResult | None,
        duration_ms: float,
        ttft_ms: float | None,
        attempt: int,
        error: LLMError | None = None,
    ) -> None:
        if self.on_usage is None:
            return
        usage = result.usage if result else None
        self.on_usage(
            UsageRecord(
                provider=client.provider,
                model=client.model,
                operation=req.operation,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cached_input_tokens=usage.cached_input_tokens if usage else 0,
                cost_usd=self._cost(result) if result else Decimal(0),
                ttft_ms=ttft_ms,
                duration_ms=duration_ms,
                ok=error is None,
                prompt_ref=req.prompt_ref,
                schema_fingerprint=(
                    req.json_schema.fingerprint if req.json_schema else None
                ),
                attempt=attempt,
                error_type=type(error).__name__ if error else None,
            )
        )

    def _call_with_retry(self, client: LLMClient, req: ChatRequest) -> ChatResult:
        """Apply the retry policy on one client; raise when it runs out."""
        started = self._now()
        last_error: LLMError | None = None

        for attempt in range(1, self.policy.max_attempts + 1):
            t0 = self._now()
            try:
                result = client.complete(req)
            except LLMError as error:
                duration_ms = (self._now() - t0) * 1000
                self._record(client, req, None, duration_ms, None, attempt, error)
                COUNTERS.increment(
                    "llm_call_errors_total",
                    provider=client.provider,
                    model=client.model,
                    type=type(error).__name__,
                )
                last_error = error

                if not error.retryable or attempt == self.policy.max_attempts:
                    raise

                wait = self.policy.delay_for(attempt, error)
                elapsed = self._now() - started
                if elapsed + wait > self.policy.total_deadline_s:
                    # Waiting past the deadline is pointless: the caller has
                    # already given up. Raise immediately.
                    raise
                COUNTERS.increment(
                    "llm_retries_total",
                    provider=client.provider,
                    type=type(error).__name__,
                )
                self._sleep(wait)
                continue

            duration_ms = (self._now() - t0) * 1000
            self._record(client, req, result, duration_ms, None, attempt)
            COUNTERS.increment(
                "llm_calls_total", provider=client.provider, model=client.model
            )
            return result

        raise last_error  # pragma: no cover - loop always returns or raises

    # --- LLMClient protocol ----------------------------------------------

    def complete(self, req: ChatRequest) -> ChatResult:
        failures: list[tuple[str, LLMError]] = []

        for index, client in enumerate(self._chain):
            try:
                return self._call_with_retry(client, req)
            except LLMError as error:
                failures.append((client.model, error))
                remaining = self._chain[index + 1 :]
                if not remaining:
                    break
                nxt = remaining[0]
                # Falling back is an EVENT. A service that degrades silently
                # looks healthy even when the primary provider is completely
                # down; the rate needs an alert on it (see the docs).
                COUNTERS.increment(
                    "llm_fallbacks_total", **{"from": client.model, "to": nxt.model}
                )
                if self.on_fallback:
                    self.on_fallback(client.model, nxt.model, error)

        if len(failures) == 1:
            raise failures[0][1]
        raise AllProvidersFailed(failures)

    def stream(self, req: ChatRequest) -> Iterator[str]:
        """No retry on streaming — a deliberate boundary.

        Once the first chunk has reached the user, retrying means erasing
        half a sentence on screen and rewriting it. A streaming failure is
        the caller's UI decision; the library does not try to hide it.
        Falling back would only be meaningful if NO chunk had arrived, and
        that case is left to the caller too.
        """
        return self._chain[0].stream(req)
