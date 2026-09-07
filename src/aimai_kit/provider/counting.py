"""Local token counting and a pre-flight budget check.

Why count locally: going over the network before every call to count tokens
is both slow and expensive. tiktoken runs locally. But NOTE — tiktoken is the
OpenAI vocabulary only. Anthropic and Gemini use different tokenizers and the
numbers do not line up. So this class produces an ESTIMATE; the real bill is
settled by the `usage` the adapter returns. Use it for budget checks, not for
cost reports.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import tiktoken

from .errors import InvalidRequest

__all__ = [
    "MESSAGE_OVERHEAD",
    "REPLY_PRIMING_OVERHEAD",
    "DEFAULT_ENCODING",
    "ContextBudgetExceeded",
    "TokenCounter",
    "budget_guard",
]

# Role and separator overhead. Based on OpenAI's own sample code (3 tokens
# per message) plus one token of headroom. Under-estimating and blowing past
# the window is more expensive than over-estimating and wasting a few tokens:
# the first costs a 400 and a broken user experience, the second costs
# tokens.
MESSAGE_OVERHEAD = 4
REPLY_PRIMING_OVERHEAD = 3

DEFAULT_ENCODING = "o200k_base"


@lru_cache(maxsize=32)
def _encoding(model: str):
    """Encoding for a model name; falls back to `o200k_base`.

    `lru_cache` is required: `encoding_for_model` builds the BPE table on
    every call, which is measurable on a hot path. The cache is per process
    rather than per counter instance.
    """
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(DEFAULT_ENCODING)


class ContextBudgetExceeded(InvalidRequest):
    """Estimated input plus output reserve exceeds the model's window.

    Derives from `InvalidRequest`, so `retryable = False`. That is
    deliberate: retrying the same request will not fit the same window any
    better. The fix is trimming (the prompt layer's `ContextBudget`) or a
    model with a larger window.
    """

    def __init__(self, needed: int, window: int, model: str) -> None:
        super().__init__(f"{needed} tokens needed, window is {window}", model=model)
        self.needed = needed
        self.window = window
        self.model = model


class TokenCounter:
    """Picks an encoding by model name, falling back to `o200k_base`."""

    def __init__(self, model: str) -> None:
        self.model = model
        self._encoder = _encoding(model)

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoder.encode(text, disallowed_special=()))

    def truncate(self, text: str, max_tokens: int) -> str:
        """Cut text down to a token limit. Token-based, not character-based.

        A character estimate like `text[:n*4]` is systematically wrong for
        non-English text: one Turkish word can be five tokens. Token-based
        truncation is the only way to guarantee the budget actually holds.

        Truncation always cuts at a token boundary, so the last word may be
        left partial. That is acceptable; the alternative (walking back to a
        word boundary) turns the budget into a guess again.
        """
        if max_tokens <= 0:
            return ""
        tokens = self._encoder.encode(text, disallowed_special=())
        if len(tokens) <= max_tokens:
            return text
        return self._encoder.decode(tokens[:max_tokens])

    def count_messages(self, messages: Sequence[dict[str, str]]) -> int:
        """Estimate the total token count of a message list.

        Summing the contents alone is wrong: every message carries role and
        separator overhead. That overhead is rounded UP — under-estimating
        and blowing past the window costs more than over-estimating.
        """
        if not messages:
            return 0
        total = REPLY_PRIMING_OVERHEAD
        for m in messages:
            total += MESSAGE_OVERHEAD
            total += self.count_text(m.get("role", ""))
            total += self.count_text(m.get("content", ""))
        return total


def budget_guard(
    counter: TokenCounter,
    messages: Sequence[dict[str, str]],
    max_output_tokens: int,
    context_window: int,
    model: str,
) -> int:
    """Check the window BEFORE making the call.

    Raises `ContextBudgetExceeded` if it does not fit, otherwise returns the
    estimated input token count. The value of this is learning about the
    problem at your own boundary with a clear message, instead of learning it
    from a provider 400.
    """
    estimated_input = counter.count_messages(messages)
    needed = estimated_input + max_output_tokens
    if needed > context_window:
        raise ContextBudgetExceeded(needed, context_window, model)
    return estimated_input
