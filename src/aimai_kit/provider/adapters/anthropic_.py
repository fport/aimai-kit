"""Anthropic adapter — Messages API.

Three differences from OpenAI, all normalized here:

1. `system` is a TOP-LEVEL parameter, not an entry in the message list.
2. `max_tokens` is REQUIRED. OpenAI lets you omit it; omitting it here is a
   400. That is why `ChatRequest.max_output_tokens` defaults to 1024 rather
   than 0.
3. The response is a BLOCK LIST (`content`), not a single string. Joining the
   text blocks has to happen somewhere; doing it in the layer above would
   mean every caller writing the same loop.

And a fourth one, the sneakiest for accounting:
`cache_read_input_tokens` is NOT included in `input_tokens`. The
package-wide rule (see `pricing.py`) is that cached tokens are a subset of
input; the conversion happens here, otherwise Anthropic costs would be
systematically understated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..errors import AuthError, InvalidRequest, LLMError, RateLimited, TransientError
from ..types import ChatRequest, ChatResult, Role, ToolCall, Usage
from ._shared import retry_after_seconds

__all__ = ["AnthropicAdapter"]


class AnthropicAdapter:
    provider = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        client: Any = None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
        else:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=api_key, max_retries=0, timeout=timeout_s
            )

    def _request_kwargs(self, req: ChatRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": req.max_output_tokens,  # required
            "messages": [
                {"role": m.role.value, "content": m.content}
                for m in req.messages
                if m.role is not Role.SYSTEM
            ],
        }
        if req.system:
            kwargs["system"] = req.system  # top level, not a message
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.stop:
            kwargs["stop_sequences"] = list(req.stop)  # not `stop`
        if req.tools:
            kwargs["tools"] = list(req.tools)
        if req.tool_choice:
            kwargs["tool_choice"] = (
                {"type": "none"} if req.tool_choice == "none" else {"type": "auto"}
            )
        if req.json_schema is not None:
            kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": dict(req.json_schema.schema),
                }
            }
        kwargs.update(req.extra.get("anthropic", {}))
        return kwargs

    def _translate_error(self, error: Exception) -> LLMError:
        import anthropic

        common = {"provider": self.provider, "model": self.model, "cause": error}
        status = getattr(error, "status_code", None)

        if isinstance(error, anthropic.RateLimitError):
            return RateLimited(
                str(error),
                retry_after_s=retry_after_seconds(error),
                status_code=status,
                **common,
            )
        if isinstance(
            error, anthropic.AuthenticationError | anthropic.PermissionDeniedError
        ):
            return AuthError(str(error), status_code=status, **common)
        if isinstance(error, anthropic.BadRequestError | anthropic.NotFoundError):
            return InvalidRequest(str(error), status_code=status, **common)
        if isinstance(error, anthropic.APIConnectionError | anthropic.APITimeoutError):
            return TransientError(str(error), **common)
        if isinstance(error, anthropic.APIStatusError):
            if status and status >= 500:
                return TransientError(str(error), status_code=status, **common)
            return InvalidRequest(str(error), status_code=status, **common)
        return LLMError(str(error), **common)

    @staticmethod
    def _text_of(response: Any) -> str:
        """Reduce the block list to a single string.

        Checking `block.type` is required: the response may also contain a
        thinking block, where `.text` either raises or mixes reasoning into
        the answer.
        """
        return "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        )

    @staticmethod
    def _tool_calls(response: Any) -> list[ToolCall]:
        """Collect `tool_use` blocks.

        Anthropic hands the arguments back already parsed, while OpenAI sends
        a JSON string. The internal format keeps the string form so the
        executor sees the same shape from every provider — and so a malformed
        blob can still be reported to the model verbatim.
        """
        calls: list[ToolCall] = []
        for block in response.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            raw = getattr(block, "input", {})
            calls.append(
                ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    arguments=raw
                    if isinstance(raw, str)
                    else json.dumps(raw, ensure_ascii=False),
                )
            )
        return calls

    def complete(self, req: ChatRequest) -> ChatResult:
        try:
            response = self._client.messages.create(**self._request_kwargs(req))
        except Exception as error:
            raise self._translate_error(error) from error

        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        # NORMALIZATION: fold Anthropic's separately reported cache reads into
        # input so the package-wide "cached is a subset of input" rule holds.
        # Cache WRITES are folded in too, because those tokens are billed at
        # full price (1.25x, in fact).
        return ChatResult(
            text=self._text_of(response),
            usage=Usage(
                input_tokens=usage.input_tokens + cache_read + cache_write,
                output_tokens=usage.output_tokens,
                cached_input_tokens=cache_read,
            ),
            provider=self.provider,
            model=self.model,
            finish_reason=response.stop_reason or "end_turn",
            prompt_ref=req.prompt_ref,
            tool_calls=self._tool_calls(response),
            raw=response,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        try:
            with self._client.messages.stream(**self._request_kwargs(req)) as stream:
                yield from stream.text_stream
        except Exception as error:
            raise self._translate_error(error) from error
