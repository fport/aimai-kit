"""One error vocabulary for three provider SDKs.

Why five classes: a retry decision is a POLICY question, not a string-match
question. Code that catches `Exception` and looks for the word "rate" breaks
silently the day a provider rewrites its message. Here the class CARRIES the
answer to "can this be retried?":

    RateLimited     -> yes, preferably honoring retry_after_s
    TransientError  -> yes, with exponential backoff
    InvalidRequest  -> no, the request is wrong; a retry gets the same 400
    AuthError       -> no, the key is wrong; a retry only pollutes the logs

`retryable` lives on the class so `resilient.py` reads the policy from one
place. Adding a new error type changes this file, not the retry logic.
"""

from __future__ import annotations

__all__ = [
    "LLMError",
    "RateLimited",
    "TransientError",
    "InvalidRequest",
    "AuthError",
    "AllProvidersFailed",
]


class LLMError(Exception):
    """Common ancestor of every provider error."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        status_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.cause = cause

    def __str__(self) -> str:
        label = "/".join(x for x in (self.provider, self.model) if x)
        body = super().__str__()
        return f"[{label}] {body}" if label else body


class RateLimited(LLMError):
    """429. When `retry_after_s` is present it wins over exponential backoff.

    The provider's own estimate beats ours; ignoring it only tightens the
    quota further.
    """

    retryable = True

    def __init__(
        self, message: str, *, retry_after_s: float | None = None, **kwargs
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after_s = retry_after_s


class TransientError(LLMError):
    """5xx, dropped connection, timeout. The same request may be retried."""

    retryable = True


class InvalidRequest(LLMError):
    """400/404/422. The request is malformed; repeating it is pointless."""

    retryable = False


class AuthError(LLMError):
    """401/403. Credential or permission problem; a retry cannot fix it."""

    retryable = False


class AllProvidersFailed(LLMError):
    """Every link in the fallback chain failed.

    Carries the whole chain so that which model failed and why does not get
    lost: `failures` is a list of (model, error) pairs.
    """

    retryable = False

    def __init__(self, failures: list[tuple[str, LLMError]]) -> None:
        summary = "; ".join(f"{model}: {err}" for model, err in failures)
        super().__init__(f"every model in the chain failed -> {summary}")
        self.failures = failures
