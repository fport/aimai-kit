"""Adapter contract: one `ChatRequest`, three providers, identical claims.

Two layers:

1. `test_contract_*` runs against a FAKE SDK client and always executes. It
   verifies request construction and usage normalization. The real value is
   here: if Anthropic's `cache_read_input_tokens` stops being folded into
   input, this breaks without touching a live API.

2. `test_live_*` is marked `@pytest.mark.live`. It runs with real credentials
   under `-m live`, is excluded from the default run, and stays green in CI
   without any keys.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from aimai_kit.provider.adapters.anthropic_ import AnthropicAdapter
from aimai_kit.provider.adapters.gemini_ import GeminiAdapter
from aimai_kit.provider.adapters.openai_ import OpenAIAdapter
from aimai_kit.provider.types import ChatRequest, JsonSchemaSpec, Message, Role

REQUEST = ChatRequest(
    messages=[
        Message(
            role=Role.USER,
            content="Answer in one word: what is the capital of France?",
        )
    ],
    system="Answer briefly and precisely.",
    max_output_tokens=64,
)

SCHEMA = JsonSchemaSpec(
    name="answer",
    schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
        "additionalProperties": False,
    },
)


# --- 1) contract against a fake SDK -------------------------------------


class _FakeOpenAI:
    def __init__(self) -> None:
        self.responses = SimpleNamespace(create=self._create)
        self.last_kwargs: dict = {}

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            output_text="Paris",
            status="completed",
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=3,
                input_tokens_details=SimpleNamespace(cached_tokens=80),
                output_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = SimpleNamespace(create=self._create)
        self.last_kwargs: dict = {}

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="thinking"),
                SimpleNamespace(type="text", text="Paris"),
            ],
            stop_reason="end_turn",
            # Anthropic: cache reads are NOT included in input_tokens.
            usage=SimpleNamespace(
                input_tokens=40,
                output_tokens=3,
                cache_read_input_tokens=80,
                cache_creation_input_tokens=0,
            ),
        )


class _FakeGemini:
    def __init__(self) -> None:
        self.models = SimpleNamespace(generate_content=self._create)
        self.last_kwargs: dict = {}

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            text="Paris",
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(
                prompt_token_count=120,
                candidates_token_count=3,
                cached_content_token_count=0,
                thoughts_token_count=0,
            ),
        )


def test_contract_openai() -> None:
    fake = _FakeOpenAI()
    result = OpenAIAdapter("gpt-5.5", client=fake).complete(REQUEST)
    assert result.text == "Paris"
    assert result.usage.input_tokens == 120
    assert result.usage.cached_input_tokens == 80
    # The system prompt is its own parameter, not a message.
    assert fake.last_kwargs["instructions"] == "Answer briefly and precisely."
    assert all(m["role"] != "system" for m in fake.last_kwargs["input"])


def test_contract_anthropic_folds_cache_reads_into_input() -> None:
    """Package-wide rule: cached tokens are a SUBSET of input tokens."""
    fake = _FakeAnthropic()
    result = AnthropicAdapter("claude-opus-5", client=fake).complete(REQUEST)
    assert result.text == "Paris", "a thinking block must not leak into text"
    assert result.usage.input_tokens == 120, "40 + 80 cache reads"
    assert result.usage.cached_input_tokens == 80
    assert result.usage.cached_input_tokens <= result.usage.input_tokens
    assert fake.last_kwargs["system"] == "Answer briefly and precisely."
    assert fake.last_kwargs["max_tokens"] == 64, "required by Anthropic"


def test_contract_gemini_maps_assistant_role_to_model() -> None:
    fake = _FakeGemini()
    request = ChatRequest(
        messages=[
            Message(role=Role.USER, content="question"),
            Message(role=Role.ASSISTANT, content="answer"),
            Message(role=Role.USER, content="follow-up"),
        ],
        system="system prompt",
    )
    GeminiAdapter("gemini-3-pro", client=fake).complete(request)
    roles = [part["role"] for part in fake.last_kwargs["contents"]]
    assert roles == ["user", "model", "user"], "assistant was not mapped to model"
    assert fake.last_kwargs["config"]["system_instruction"] == "system prompt"


@pytest.mark.parametrize(
    ("adapter_cls", "fake_cls", "schema_at"),
    [
        (OpenAIAdapter, _FakeOpenAI, lambda kw: kw["text"]["format"]["schema"]),
        (
            AnthropicAdapter,
            _FakeAnthropic,
            lambda kw: kw["output_config"]["format"]["schema"],
        ),
        (GeminiAdapter, _FakeGemini, lambda kw: kw["config"]["response_json_schema"]),
    ],
    ids=["openai", "anthropic", "gemini"],
)
def test_same_schema_reaches_three_different_wrappers(
    adapter_cls, fake_cls, schema_at
) -> None:
    """The contract the prompt layer relies on: one schema, three wrappers."""
    fake = fake_cls()
    request = ChatRequest(messages=REQUEST.messages, json_schema=SCHEMA)
    adapter_cls("m", client=fake).complete(request)
    assert schema_at(fake.last_kwargs) == dict(SCHEMA.schema)


# --- 2) live contract ---------------------------------------------------

LIVE_CASES = [
    pytest.param("openai:gpt-5.5", "OPENAI_API_KEY", id="openai"),
    pytest.param("anthropic:claude-opus-5", "ANTHROPIC_API_KEY", id="anthropic"),
    pytest.param("gemini:gemini-3-pro", "GEMINI_API_KEY", id="gemini"),
]


@pytest.mark.live
@pytest.mark.parametrize(("spec", "env_var"), LIVE_CASES)
def test_live_same_request_produces_valid_result(spec: str, env_var: str) -> None:
    if not os.getenv(env_var):
        pytest.skip(f"{env_var} is not set")
    from aimai_kit.provider.adapters import make_adapter

    result = make_adapter(spec).complete(REQUEST)
    assert result.text.strip()
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.provider and result.model
    assert result.usage.cached_input_tokens <= result.usage.input_tokens
