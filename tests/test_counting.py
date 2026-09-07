"""Token counting."""

from aimai_kit.provider.counting import TokenCounter


def test_unknown_model_falls_back() -> None:
    # `encoding_for_model` misses, so it should fall back to o200k_base.
    counter = TokenCounter("unknown-model-2099")
    assert counter.count_text("hello") > 0


def test_non_english_text_is_counted() -> None:
    counter = TokenCounter("gpt-4o")
    assert counter.count_text("degerlendirilebilecegini") > 1


def test_empty_text_is_zero() -> None:
    assert TokenCounter("gpt-4o").count_text("") == 0


def test_message_overhead_is_added() -> None:
    """`count_messages` must exceed the sum of the contents alone."""
    counter = TokenCounter("gpt-4o")
    messages = [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "Hello, how are you?"},
    ]
    raw = sum(counter.count_text(m["content"]) for m in messages)
    assert counter.count_messages(messages) > raw


def test_empty_message_list() -> None:
    assert TokenCounter("gpt-4o").count_messages([]) >= 0


def test_truncate_respects_token_limit() -> None:
    """A character estimate is systematically wrong for non-English text."""
    counter = TokenCounter("gpt-4o")
    text = "degerlendirilebilecegini " * 50
    truncated = counter.truncate(text, 30)
    assert counter.count_text(truncated) <= 30


def test_truncate_returns_text_when_it_fits() -> None:
    counter = TokenCounter("gpt-4o")
    assert counter.truncate("short text", 1000) == "short text"
