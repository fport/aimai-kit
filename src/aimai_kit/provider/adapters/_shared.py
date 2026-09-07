"""Small helpers shared by the adapters.

Deliberately SMALL: writing a common base class and moving `complete` into it
is tempting but wrong. The three providers really do build requests
differently (Anthropic requires `max_tokens`, Gemini puts the system
instruction inside the config, OpenAI takes messages as `input`). Collapsing
that into a shared base is the lowest-common-denominator trap. Only what is
genuinely identical lives here: Retry-After parsing.
"""

from __future__ import annotations

__all__ = ["retry_after_seconds"]


def retry_after_seconds(error: object) -> float | None:
    """Extract the Retry-After header from an SDK error, in seconds.

    The header may hold seconds ("30") or an HTTP date; the latter is rare
    enough that it is not parsed and `None` is returned, which lets
    exponential backoff take over. Saying "I don't know" is safer than
    guessing a wrong number.
    """
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in ("retry-after", "Retry-After", "retry-after-ms"):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value / 1000 if name.endswith("-ms") else value
    return None
