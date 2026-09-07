"""OpenAI adapter — Responses API.

Why Responses rather than Chat Completions: Responses carries text,
structured output and tool calls through one shape, so the tool layer did not
need a second code path.

Naming differences are called out in comments so all three adapters can be
read side by side; the "usage field names" trap lives right there.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..errors import AuthError, InvalidRequest, LLMError, RateLimited, TransientError
from ..types import ChatRequest, ChatResult, Role, ToolCall, Usage
from ._shared import retry_after_seconds

__all__ = ["OpenAIAdapter"]


class OpenAIAdapter:
    """One model, one client. The client is built ONCE and shared.

    Constructing `OpenAI()` per call opens a fresh HTTP connection pool; on a
    hot path the TCP+TLS handshake is a visible share of latency.

    `max_retries=0`: the SDK's own retry is OFF. Two layers of retry turn the
    real attempt count into a product (3 x 2 = 6) and make the deadline in
    `ResilientClient` meaningless. Exactly one place decides to retry.
    """

    provider = "openai"

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
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)

    # --- request construction ---------------------------------------------

    def _request_kwargs(self, req: ChatRequest) -> dict[str, Any]:
        # In OpenAI the system prompt is its own parameter: `instructions`.
        payload = [
            {"role": m.role.value, "content": m.content}
            for m in req.messages
            if m.role is not Role.SYSTEM
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": payload,
            "max_output_tokens": req.max_output_tokens,
        }
        if req.system:
            kwargs["instructions"] = req.system
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.tools:
            kwargs["tools"] = list(req.tools)
        if req.tool_choice:
            kwargs["tool_choice"] = req.tool_choice
        if req.json_schema is not None:
            # The schema goes under `text.format` here; Anthropic wants
            # `output_config.format` and Gemini `response_json_schema`.
            # Same JSON Schema, three different wrappers.
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": req.json_schema.name,
                    "schema": dict(req.json_schema.schema),
                    "strict": req.json_schema.strict,
                }
            }
        kwargs.update(req.extra.get("openai", {}))
        return kwargs

    # --- error translation -------------------------------------------------

    def _translate_error(self, error: Exception) -> LLMError:
        import openai

        common = {"provider": self.provider, "model": self.model, "cause": error}
        status = getattr(error, "status_code", None)

        if isinstance(error, openai.RateLimitError):
            return RateLimited(
                str(error),
                retry_after_s=retry_after_seconds(error),
                status_code=status,
                **common,
            )
        if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
            return AuthError(str(error), status_code=status, **common)
        if isinstance(error, openai.BadRequestError | openai.NotFoundError):
            return InvalidRequest(str(error), status_code=status, **common)
        if isinstance(error, openai.APIConnectionError | openai.APITimeoutError):
            return TransientError(str(error), **common)
        if isinstance(error, openai.APIStatusError):
            # 5xx is transient, other 4xx are request errors. The line is
            # drawn on the status code alone; no string matching.
            if status and status >= 500:
                return TransientError(str(error), status_code=status, **common)
            return InvalidRequest(str(error), status_code=status, **common)
        return LLMError(str(error), **common)

    @staticmethod
    def _tool_calls(response: Any) -> list[ToolCall]:
        """Pull function calls out of the response output list.

        Arguments stay a raw JSON string: turning a malformed argument blob
        into an instructive message for the model is the executor's job, and
        parsing here would either raise inside the adapter or hide the error.
        """
        calls: list[ToolCall] = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", "") != "function_call":
                continue
            arguments = getattr(item, "arguments", "") or "{}"
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            calls.append(
                ToolCall(
                    id=getattr(item, "call_id", "") or getattr(item, "id", ""),
                    name=getattr(item, "name", ""),
                    arguments=arguments,
                )
            )
        return calls

    # --- LLMClient protocol ------------------------------------------------

    def complete(self, req: ChatRequest) -> ChatResult:
        try:
            response = self._client.responses.create(**self._request_kwargs(req))
        except Exception as error:
            raise self._translate_error(error) from error

        usage = response.usage
        # OpenAI: cached tokens live INSIDE input_tokens, under a detail obj.
        cached = (
            getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0)
            or 0
        )
        reasoning = (
            getattr(
                getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0
            )
            or 0
        )

        return ChatResult(
            text=response.output_text or "",
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=cached,
                reasoning_tokens=reasoning,
            ),
            provider=self.provider,
            model=self.model,
            finish_reason=getattr(response, "status", "completed") or "completed",
            prompt_ref=req.prompt_ref,
            tool_calls=self._tool_calls(response),
            raw=response,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        try:
            with self._client.responses.stream(**self._request_kwargs(req)) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        yield event.delta
        except Exception as error:
            raise self._translate_error(error) from error
